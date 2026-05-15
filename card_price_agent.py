"""
card_price_agent.py — pulls "actual" card prices from SportsCardsPro for every
active listing and writes them to sportscardspro_prices.json for the dashboard.

How matching works:
  1. Parse the listing title into structured tokens (player, year, set brand,
     card number, grade).
  2. Build a search query and hit /api/products (returns the top ~20 hits).
  3. Score every candidate against the parsed tokens and pick the best match.
  4. Fetch the matching product's full price row via /api/product?id=<id>.
  5. Pick the grade price that matches the grade detected in the title
     (PSA 10 / PSA 9 / BGS 10 / raw / etc.) and record it as "actual_price".

eBay = "market price" (what people are listing/selling for).
SportsCardsPro = "actual price" (the canonical guide value for that grade).
The dashboard renders both and lets you toggle which one drives the gap badge.

Usage:
    python card_price_agent.py                    # refresh stale entries
    python card_price_agent.py --force            # refetch every listing
    python card_price_agent.py --item 306913311444  # one listing
    python card_price_agent.py --limit 20         # smoke-test on first 20
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import requests

import promote

REPO_ROOT       = Path(__file__).parent
LISTINGS_PATH   = REPO_ROOT / "output" / "listings_snapshot.json"
OUTPUT_PATH     = REPO_ROOT / "sportscardspro_prices.json"
TTL_SECONDS     = 7 * 24 * 3600      # refetch after a week
API_BASE        = "https://www.sportscardspro.com"   # scopes search to cards only

# Set brands worth weighting in match scoring.
SET_BRANDS = {
    "topps", "bowman", "panini", "donruss", "fleer", "upper deck", "score",
    "prizm", "optic", "mosaic", "select", "chrome", "stadium club", "leaf",
    "pinnacle", "skybox", "hoops", "metal", "finest", "pokemon", "magic",
    "yugioh", "yu-gi-oh", "mtg", "tcg", "rookie",
}

# Words that should NOT be treated as part of a player/character name.
NAME_STOPWORDS = {
    "psa", "bgs", "cgc", "sgc", "gem", "mint", "rookie", "rc", "card",
    "cards", "lot", "graded", "raw", "near", "auto", "autograph", "patch",
    "rookie", "holo", "refractor", "prizm", "optic", "mosaic", "the", "and",
    "vintage", "vintage", "topps", "panini", "bowman", "donruss", "fleer",
    "upper", "deck", "score", "select", "chrome", "stadium", "club", "leaf",
    "pokemon", "japanese", "english", "promo", "magic", "gathering", "yugioh",
    "yu", "gi", "oh", "rare", "ultra", "common", "uncommon", "foil", "nm",
    "sealed", "set", "edition", "first", "1st", "2nd", "free", "shipping",
}


CONFIDENCE_FLOOR = 0.40    # below this, we don't record an actual_price


def is_lot_listing(title: str) -> bool:
    """Detect multi-card lots that can't have a single SCP 'actual' price."""
    t = title.lower()
    if re.search(r"\blot\b", t):                         return True
    if re.search(r"\bincluding\b", t):                   return True
    if re.search(r"\(\s*\d+\s*cards?\s*\)", t):          return True
    # Leading count: "13 Junior Seau Cards", "3 Marshall Faulk Cards"
    if re.match(r"^\s*\d+\s+\w+", title) and "cards" in t:
        return True
    # Generic "Player Cards" with no specific card # → almost certainly a lot
    if re.search(r"\bcards\b", t) and not re.search(r"#\s*\d+", t):
        if not re.search(r"\bcard\b\s+#?\s*\d+", t):
            return True
    return False


# --------------------------------------------------------------------------- #
# Title parsing                                                               #
# --------------------------------------------------------------------------- #

def parse_title(title: str) -> dict:
    """Return a dict of {player, year, set_tokens, card_number, grade}."""
    t_lower = title.lower()

    year_match = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", title)
    year = year_match.group(1) if year_match else None

    # Card number: "#57", "No. 57", "/250", etc. — prefer the #N form.
    card_num = None
    m = re.search(r"#\s*(\d{1,4})\b", title)
    if m:
        card_num = m.group(1)
    else:
        m = re.search(r"\bno\.?\s*(\d{1,4})\b", t_lower)
        if m:
            card_num = m.group(1)

    grade = promote._detect_card_grade(title)

    set_tokens = [b for b in SET_BRANDS if b in t_lower]

    # Player/character: take title-cased multi-word runs, drop stopwords.
    # Strip trailing inventory noise so "Michael Jordan #57 PSA 9" → "Michael Jordan".
    cleaned = re.sub(r"#\s*\d+.*$", "", title)
    cleaned = re.sub(r"\b(psa|bgs|cgc|sgc)\b.*$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(19[5-9]\d|20[0-3]\d)\b", "", cleaned)
    tokens = re.findall(r"[A-Z][a-zA-Z'\-\.]+", cleaned)
    name_tokens = [t for t in tokens if t.lower() not in NAME_STOPWORDS]
    player = " ".join(name_tokens[:3]).strip()  # cap at 3 words to avoid noise

    return {
        "player":      player,
        "year":        year,
        "set_tokens":  set_tokens,
        "card_number": card_num,
        "grade":       grade,
    }


def build_query(parsed: dict, raw_title: str) -> str:
    """Build a compact query string for /api/products."""
    parts = []
    if parsed["player"]:
        parts.append(parsed["player"])
    if parsed["year"]:
        parts.append(parsed["year"])
    parts.extend(parsed["set_tokens"][:2])
    if parsed["card_number"]:
        parts.append(f"#{parsed['card_number']}")
    q = " ".join(parts).strip()
    # Fall back to raw title if we couldn't parse anything useful.
    if len(q) < 4:
        q = promote._market_query(raw_title)
    return q[:100]


# --------------------------------------------------------------------------- #
# Match scoring                                                               #
# --------------------------------------------------------------------------- #

def score_match(parsed: dict, candidate: dict) -> float:
    """Higher is better. 0.0 = nothing matches, ~1.0 = strong match."""
    pname = (candidate.get("product-name") or "").lower()
    cname = (candidate.get("console-name") or "").lower()
    haystack = f"{pname} {cname}"

    score = 0.0

    if parsed["player"]:
        # Fuzzy name match against product-name only.
        ratio = SequenceMatcher(None, parsed["player"].lower(), pname).ratio()
        score += ratio * 0.45
        # Strong bonus if every name token appears literally.
        if all(tok.lower() in pname for tok in parsed["player"].split() if len(tok) > 2):
            score += 0.15

    if parsed["year"] and parsed["year"] in cname:
        score += 0.20

    if parsed["card_number"]:
        if re.search(rf"#\s*{re.escape(parsed['card_number'])}\b", pname):
            score += 0.15

    for brand in parsed["set_tokens"]:
        if brand in cname:
            score += 0.05

    # Penalize obvious mismatches: checklist/promo/header cards when title
    # doesn't mention them.
    raw_lower = " ".join([parsed["player"] or "", " ".join(parsed["set_tokens"])]).lower()
    for noise in ("checklist", "header", "team card", "leaders"):
        if noise in pname and noise not in raw_lower:
            score -= 0.10

    return max(0.0, min(1.0, score))


# --------------------------------------------------------------------------- #
# SportsCardsPro API calls                                                    #
# --------------------------------------------------------------------------- #

def search_products(query: str, token: str) -> list[dict]:
    promote._pricecharting_throttle()
    try:
        r = requests.get(
            f"{API_BASE}/api/products",
            params={"t": token, "q": query},
            timeout=15,
        )
        if r.status_code != 200:
            return []
        d = r.json()
        if d.get("status") != "success":
            return []
        return d.get("products", []) or []
    except Exception as e:
        print(f"  search error: {e}", file=sys.stderr)
        return []


def fetch_product(product_id: str, token: str) -> dict | None:
    promote._pricecharting_throttle()
    try:
        r = requests.get(
            f"{API_BASE}/api/product",
            params={"t": token, "id": product_id},
            timeout=15,
        )
        if r.status_code != 200:
            return None
        d = r.json()
        if d.get("status") != "success":
            return None
        return d
    except Exception as e:
        print(f"  product-fetch error: {e}", file=sys.stderr)
        return None


def extract_grades(product: dict) -> dict[str, float]:
    """Pull every grade-priced field out of an /api/product response, in USD."""
    grades: dict[str, float] = {}
    for grade_key, field in promote._PRICECHARTING_GRADE_FIELDS:
        v = product.get(field)
        if isinstance(v, (int, float)) and v > 0:
            grades[grade_key] = round(v / 100.0, 2)
    return grades


# --------------------------------------------------------------------------- #
# Per-listing pricing                                                         #
# --------------------------------------------------------------------------- #

def price_listing(listing: dict, token: str) -> dict | None:
    title  = listing.get("title") or ""

    if is_lot_listing(title):
        return {
            "title":           title,
            "is_lot":          True,
            "matched_product": None,
            "confidence":      0.0,
            "fetched_at":      int(time.time()),
            "note":            "lot listing — SCP guide prices single cards only",
        }

    parsed = parse_title(title)
    query  = build_query(parsed, title)

    candidates = search_products(query, token)
    if not candidates:
        return {
            "title":           title,
            "query":           query,
            "parsed":          parsed,
            "matched_product": None,
            "confidence":      0.0,
            "fetched_at":      int(time.time()),
            "note":            "no search results",
        }

    scored = sorted(
        ((score_match(parsed, c), c) for c in candidates),
        key=lambda x: x[0],
        reverse=True,
    )
    best_score, best = scored[0]

    # Confidence threshold — below this we still record the best guess but flag low.
    if best_score < CONFIDENCE_FLOOR:
        return {
            "title":           title,
            "query":           query,
            "parsed":          parsed,
            "matched_product": best.get("product-name"),
            "matched_set":     best.get("console-name"),
            "product_id":      best.get("id"),
            "scp_url":         f"https://www.sportscardspro.com/game/sportscardspro/{best.get('id')}" if best.get("id") else "",
            "confidence":      round(best_score, 3),
            "fetched_at":      int(time.time()),
            "note":            "low confidence — no price recorded",
        }

    product = fetch_product(best["id"], token)
    if not product:
        return None

    grades   = extract_grades(product)
    detected = parsed["grade"]
    if detected and detected in grades:
        actual_price = grades[detected]
        used_grade   = detected
    elif "raw" in grades:
        actual_price = grades["raw"]
        used_grade   = "raw"
    elif grades:
        used_grade   = min(grades, key=lambda k: grades[k])
        actual_price = grades[used_grade]
    else:
        actual_price = None
        used_grade   = None

    return {
        "title":           title,
        "query":           query,
        "parsed":          parsed,
        "matched_product": product.get("product-name"),
        "matched_set":     product.get("console-name"),
        "product_id":      product.get("id"),
        "scp_url":         f"https://www.sportscardspro.com/game/sportscardspro/{product.get('id')}",
        "confidence":      round(best_score, 3),
        "detected_grade":  detected,
        "used_grade":      used_grade,
        "actual_price":    actual_price,
        "grades":          grades,
        "sales_volume":    product.get("sales-volume"),
        "release_date":    product.get("release-date"),
        "fetched_at":      int(time.time()),
    }


# --------------------------------------------------------------------------- #
# Driver                                                                      #
# --------------------------------------------------------------------------- #

def load_listings() -> list[dict]:
    if not LISTINGS_PATH.exists():
        sys.exit(f"Missing {LISTINGS_PATH}. Run promote.py first to snapshot listings.")
    data = json.loads(LISTINGS_PATH.read_text())
    return data if isinstance(data, list) else data.get("listings", [])


def load_store() -> dict:
    if not OUTPUT_PATH.exists():
        return {}
    try:
        return json.loads(OUTPUT_PATH.read_text())
    except Exception:
        return {}


def save_store(store: dict) -> None:
    OUTPUT_PATH.write_text(json.dumps(store, indent=2, ensure_ascii=False))


def load_token() -> str:
    cfg = json.loads((REPO_ROOT / "configuration.json").read_text())
    tok = cfg.get("pricecharting_api_key") or ""
    if not tok:
        sys.exit("No pricecharting_api_key in configuration.json")
    return tok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Refetch every listing")
    ap.add_argument("--item",  help="Only price this item_id")
    ap.add_argument("--limit", type=int, help="Cap how many listings to process")
    args = ap.parse_args()

    token    = load_token()
    listings = load_listings()
    store    = load_store()

    if args.item:
        listings = [l for l in listings if str(l.get("item_id")) == str(args.item)]

    now = int(time.time())
    todo = []
    for l in listings:
        iid = str(l.get("item_id"))
        prev = store.get(iid)
        is_stale = args.force or not prev or (now - prev.get("fetched_at", 0)) > TTL_SECONDS
        if is_stale:
            todo.append(l)

    if args.limit:
        todo = todo[: args.limit]

    print(f"Pricing {len(todo)} listings (of {len(listings)} total). Rate: 1 req/sec.")
    print(f"Estimated runtime: ~{len(todo) * 2.1:.0f}s (2 API calls each).\n")

    matched = low_conf = no_match = lots = 0
    for i, l in enumerate(todo, 1):
        iid = str(l.get("item_id"))
        title = l.get("title", "")[:70]
        print(f"[{i}/{len(todo)}] {iid}  {title}")
        try:
            rec = price_listing(l, token)
        except Exception as e:
            print(f"    ERROR: {e}")
            continue
        if not rec:
            continue
        store[iid] = rec
        if rec.get("is_lot"):
            lots += 1
            print(f"    → lot listing — skipped")
        elif rec.get("actual_price"):
            matched += 1
            print(f"    → {rec['matched_product']} · {rec.get('used_grade')} ${rec['actual_price']:.2f} · conf {rec['confidence']:.2f}")
        elif rec.get("matched_product"):
            low_conf += 1
            print(f"    → low conf ({rec['confidence']:.2f}): {rec['matched_product']}")
        else:
            no_match += 1
            print(f"    → no match")
        # Persist incrementally so a Ctrl-C doesn't lose progress.
        if i % 10 == 0:
            save_store(store)

    save_store(store)
    print(f"\nDone. matched={matched}  low_conf={low_conf}  no_match={no_match}  lots={lots}")
    print(f"Wrote {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
