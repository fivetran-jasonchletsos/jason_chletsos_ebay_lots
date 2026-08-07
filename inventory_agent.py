"""
inventory_agent.py — your unlisted-card inventory, ready to list on eBay.

Reads `inventory.csv` (export from SportsCardsPro "My Collection", or
hand-maintain). For each card:
  • Match to PriceCharting / SCP cache for a current market price
  • Suggest an eBay-best-practices title (year + brand + player + parallel + sport)
  • Map to one of the 8 store custom categories (matches website)
  • Render row with a "Generate Listing" button → opens a modal with
    AddItem XML and a Copy-Listing-Info block ready to paste into eBay UI
  • Optional Phase 2: live AddItem POST via Trading API

CSV columns (extras ignored):
  name, year, set, card_number, player, sport, parallel, grade, grader,
  condition, quantity, acquired_price, image_url, notes

Output:
  output/inventory_plan.json
  docs/inventory.html
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote

REPO_ROOT = Path(__file__).parent
CSV_PATH  = REPO_ROOT / "inventory.csv"
PLAN_PATH = REPO_ROOT / "output" / "inventory_plan.json"
REPORT    = REPO_ROOT / "docs"   / "inventory.html"
SCP_CACHE = REPO_ROOT / "sportscardspro_prices.json"

# eBay primary category IDs — modernized to the post-2024 trading-card taxonomy.
# Sports trading card singles all live under 261328 ("Trading Card Singles"
# inside Sports Mem > Sports Trading Cards). The old per-sport parent nodes
# (215/214/213/216) were deprecated; eBay auto-migrates but rejects ConditionID
# 1000 against them. Pokemon retains its TCG-specific category.
EBAY_CATEGORY = {
    "Football":   "261328",
    "Basketball": "261328",
    "Baseball":   "261328",
    "Hockey":     "261328",
    "Pokemon":    "183454",  # Toys & Hobbies > Collectible Card Games > Pokemon TCG
    "Other":      "261328",
}


# --------------------------------------------------------------------------- #
# CSV load                                                                     #
# --------------------------------------------------------------------------- #

def load_inventory() -> list[dict]:
    if not CSV_PATH.exists():
        print(f"  No {CSV_PATH.name} found — create it with these columns:")
        print(f"  name,year,set,card_number,player,sport,parallel,grade,grader,condition,quantity,acquired_price,image_url,notes")
        return []
    rows: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("name"):
                continue
            rows.append(r)
    return rows


# --------------------------------------------------------------------------- #
# Enrichment                                                                   #
# --------------------------------------------------------------------------- #

def _load_scp_cache() -> dict[str, dict]:
    """SCP cache is keyed by item_id (eBay listings). We can't directly look up
    by inventory row, but we'll fuzz-match by title tokens."""
    try:
        return json.loads(SCP_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", (s or "").lower()) if len(t) > 1}


def _scp_match(row: dict, cache: dict) -> dict | None:
    """Best-effort match — find SCP entries whose title shares >=4 distinct
    tokens with the inventory row's name."""
    row_toks = _tokens(row.get("name", ""))
    if len(row_toks) < 4:
        return None
    best, best_overlap = None, 0
    for v in cache.values():
        cand_toks = _tokens(v.get("matched_product") or v.get("title") or "")
        overlap = len(row_toks & cand_toks)
        if overlap > best_overlap:
            best_overlap, best = overlap, v
    return best if best_overlap >= 4 else None


def _category(row: dict) -> tuple[str, str]:
    """Returns (display_name, ebay_category_id) for the row."""
    sport = (row.get("sport") or "").strip().title()
    if sport in EBAY_CATEGORY:
        return sport, EBAY_CATEGORY[sport]
    # Try to infer from the name
    name = row.get("name", "").lower()
    if "pokemon" in name or "pikachu" in name or "charizard" in name:
        return "Pokemon", EBAY_CATEGORY["Pokemon"]
    if any(w in name for w in ("nfl", "football", "panini prizm", "topps chrome")):
        return "Football", EBAY_CATEGORY["Football"]
    if "nba" in name or "basketball" in name:
        return "Basketball", EBAY_CATEGORY["Basketball"]
    if "mlb" in name or "baseball" in name:
        return "Baseball", EBAY_CATEGORY["Baseball"]
    return "Other", EBAY_CATEGORY["Other"]


def _suggest_title(row: dict) -> str:
    """eBay best-practices title: year + set + player + parallel + sport.
    Caps at 80 chars (eBay max)."""
    parts: list[str] = []
    year = (row.get("year") or "").strip()
    set_ = (row.get("set") or "").strip()
    # Skip year if `set` already leads with it (CollX exports are shaped that way).
    if year and not set_.startswith(year):
        parts.append(year)
    if set_:                  parts.append(set_)
    if row.get("player"):     parts.append(row["player"])
    if row.get("card_number") and not row.get("card_number").startswith("#"):
        parts.append(f"#{row['card_number']}")
    elif row.get("card_number"):
        parts.append(row["card_number"])
    if row.get("parallel"):   parts.append(row["parallel"])
    if row.get("grader") and row.get("grade"):
        parts.append(f"{row['grader']} {row['grade']}")
    sport = (row.get("sport") or "").strip().title()
    if sport and sport not in {p.lower().title() for p in parts}:
        parts.append(sport)
    title = " ".join(parts)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:80]


def _as_float(v) -> float | None:
    try:
        f = float(v)
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _scp_best_price(scp: dict | None) -> tuple[float, str] | None:
    if not scp:
        return None
    for key in ("psa10_price", "psa9_price", "psa8_price",
                "graded_price", "ungraded_price", "loose_price"):
        v = _as_float(scp.get(key))
        if v:
            return (v, key)
    return None


def _suggest_price(row: dict, scp: dict | None) -> dict:
    """Return {price, basis, low, high}. Prefer CollX market_value when present
    (it's the live signal from Jason's CollX Pro subscription); fall back to
    SCP guide price; then 2x acquired; then default."""
    # 1. CollX market value (preferred — live signal)
    collx_mv = _as_float(row.get("collx_market_value"))
    if collx_mv:
        price = round(collx_mv * 0.92, 2)
        return {"price": price, "basis": "CollX market",
                "low": round(price * 0.85, 2), "high": round(price * 1.15, 2)}
    # 2. SCP cache hit
    scp_best = _scp_best_price(scp)
    if scp_best:
        scp_v, scp_key = scp_best
        price = round(scp_v * 0.92, 2)
        return {"price": price, "basis": f"SCP {scp_key}",
                "low": round(price * 0.85, 2), "high": round(price * 1.15, 2)}
    # 3. Acquired-price 2x fallback
    ap = _as_float(row.get("acquired_price"))
    if ap:
        return {"price": round(ap * 2, 2), "basis": "2x acquired",
                "low": round(ap * 1.5, 2), "high": round(ap * 3, 2)}
    # 4. Default $4.99
    return {"price": 4.99, "basis": "default", "low": 3.99, "high": 6.99}


def _extract_manufacturer(set_str: str) -> str:
    """Pull the manufacturer name out of a CollX set string like
    '2025 Panini Phoenix - Pyramids Prizm' -> 'Panini'."""
    s = (set_str or "").strip()
    for needle in ("Panini", "Topps", "Bowman", "Upper Deck", "Donruss",
                   "Score", "Leaf", "Wizards of the Coast", "Pokemon"):
        if needle.lower() in s.lower():
            return needle
    return ""


def _features_from_row(row: dict) -> list[str]:
    """eBay Features specific — accepts a comma-separated list. Detect from
    the parallel/flags and the set/title text."""
    feats = []
    parallel = (row.get("parallel") or "").upper()
    name     = (row.get("name") or "").lower()
    if "RC" in parallel or "(rc)" in name or "rookie" in name:
        feats.append("Rookie")
    if "AU" in parallel or " auto" in name or "autograph" in name:
        feats.append("Autograph")
    if "MEM" in parallel or "patch" in name or "memorabilia" in name or "jersey" in name:
        feats.append("Memorabilia")
    if "SN" in parallel or "/" in (row.get("parallel") or "") or "numbered" in name:
        feats.append("Serial Numbered")
    if "refractor" in name or "prizm" in name or "shimmer" in name or "holo" in name or "shine" in name:
        feats.append("Parallel/Variation")
    return feats


def _print_run_from_parallel(parallel: str) -> str:
    """CollX flags like 'RC, SN85' or 'SN10' encode the print run as the
    trailing number after 'SN'. Return the bare number for the Print Run
    specific. Empty if not numbered."""
    import re as _re
    m = _re.search(r'SN\s*(\d+)', (parallel or "").upper())
    return m.group(1) if m else ""


# Common-team lookup for sport leagues. Extend as needed.
NFL_TEAMS = {
    "raiders", "vikings", "chiefs", "bills", "ravens", "cowboys", "eagles",
    "giants", "jets", "patriots", "dolphins", "bengals", "browns", "steelers",
    "texans", "colts", "jaguars", "titans", "broncos", "chargers", "lions",
    "packers", "bears", "buccaneers", "falcons", "panthers", "saints",
    "cardinals", "rams", "49ers", "seahawks", "commanders",
}


def _team_from_text(*texts: str) -> str:
    """Guess team from any of the provided strings. Picks the first match."""
    hay = " ".join(t for t in texts if t).lower()
    for team in NFL_TEAMS:
        if team in hay:
            return team.capitalize()
    return ""


def _league_for(sport: str) -> str:
    """Map sport to its primary league name eBay uses in specifics."""
    s = (sport or "").lower()
    return {"football":"NFL", "basketball":"NBA", "baseball":"MLB",
            "hockey":"NHL", "soccer":"MLS"}.get(s, "")


def _suggest_specifics(row: dict, category: str) -> dict[str, str]:
    """Item Specifics eBay wants. eBay's Trading Card Singles category 261328
    mandates 12+ fields for full Cassini placement. Top-sellers review on
    2026-05-30 flagged that we were emitting only 7 — missing Manufacturer,
    League, Team, Features, Print Run despite the data being available."""
    out: dict[str, str] = {}
    if row.get("year"):           out["Year"] = row["year"]
    if row.get("set"):            out["Set"] = row["set"]
    if row.get("player"):
        if category in ("Pokemon",):
            out["Character"] = row["player"]
        else:
            out["Player/Athlete"] = row["player"]
            out["Athlete"] = row["player"]
    if row.get("card_number"):    out["Card Number"] = str(row["card_number"]).lstrip("#")
    if row.get("parallel"):       out["Parallel/Variety"] = row["parallel"]
    if row.get("grader") and row.get("grade"):
        out["Graded"] = "Yes"
        out["Professional Grader"] = row["grader"]
        out["Grade"] = row["grade"]
    else:
        out["Graded"] = "No"
        # Note: the "Card Condition" sub-grade (Near mint or better / Excellent
        # / Very good / Poor) lives in <ConditionDescriptors>, NOT ItemSpecifics
        # — push_to_ebay.py emits it as descriptor 40001 with value 400010 by
        # default. See CARD_CONDITION_DESCRIPTOR_VALUE in push_to_ebay.py.
    sport = (row.get("sport") or "").title()
    if sport and category != "Pokemon":
        out["Sport"] = sport
    # --- Cassini-completeness fields (added 2026-05-30 per top-seller review)
    mfr = _extract_manufacturer(row.get("set", ""))
    if mfr:
        out["Manufacturer"] = mfr
    league = _league_for(row.get("sport", ""))
    if league:
        out["League"] = league
    team = _team_from_text(row.get("set", ""), row.get("name", ""))
    if team:
        out["Team"] = team
    feats = _features_from_row(row)
    if feats:
        out["Features"] = ", ".join(feats)
    print_run = _print_run_from_parallel(row.get("parallel", ""))
    if print_run:
        out["Print Run"] = print_run
    # Language defaults — eBay wants this for international visibility
    if category == "Pokemon" and "japan" in (row.get("name","") + row.get("set","")).lower():
        out["Language"] = "Japanese"
    else:
        out["Language"] = "English"
    return out


# --------------------------------------------------------------------------- #
# Plan + render                                                                #
# --------------------------------------------------------------------------- #

def build_plan() -> dict:
    rows = load_inventory()
    scp = _load_scp_cache()
    enriched: list[dict] = []
    for r in rows:
        cat_name, cat_id = _category(r)
        scp_match = _scp_match(r, scp)
        price_rec = _suggest_price(r, scp_match)
        title     = _suggest_title(r) or r.get("name", "")
        specifics = _suggest_specifics(r, cat_name)
        scp_best = _scp_best_price(scp_match)
        enriched.append({
            "raw":              r,
            "title":            title,
            "ebay_category":    cat_name,
            "category_id":      cat_id,
            "store_category":   cat_name,  # matches our 8-bucket store sidebar
            "price":            price_rec["price"],
            "price_basis":      price_rec["basis"],
            "price_low":        price_rec["low"],
            "price_high":       price_rec["high"],
            "collx_market":     _as_float(r.get("collx_market_value")),
            "collx_asking":     _as_float(r.get("collx_asking_price")),
            "scp_value":        scp_best[0] if scp_best else None,
            "scp_basis":        scp_best[1] if scp_best else None,
            "specifics":        specifics,
            "scp_match":        bool(scp_match),
            "image_url":        r.get("image_url", ""),
        })
    return {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count":         len(enriched),
        "ready":         sum(1 for e in enriched if e["image_url"]),
        "needs_photo":   sum(1 for e in enriched if not e["image_url"]),
        "items":         enriched,
    }


def save_plan(plan: dict) -> Path:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def _sources_line(e: dict) -> str:
    parts: list[str] = []
    if e.get("collx_market") is not None:
        parts.append(f"<span>CollX <b>${e['collx_market']:.2f}</b></span>")
    if e.get("scp_value") is not None:
        parts.append(f"<span>SCP <b>${e['scp_value']:.2f}</b></span>")
    if e.get("collx_asking") is not None:
        parts.append(f"<span>Asking <b>${e['collx_asking']:.2f}</b></span>")
    return " &middot; ".join(parts) if parts else "<span class=\"inv-pb\">no live comps</span>"


def ensure_nav_entry() -> None:
    entry = ("inventory.html", "Inventory", False, "Sell")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "price_review.html":
            items.insert(idx, entry); break
    else:
        items.append(entry)
    promote._NAV_ITEMS = items
    promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.parse_args()
    ensure_nav_entry()
    plan = build_plan()
    save_plan(plan)
    print(f"  Inventory: {plan['count']} cards loaded  ({plan['ready']} ready, {plan['needs_photo']} need photos)")
    print(f"  Plan:   {PLAN_PATH}")


if __name__ == "__main__":
    main()
