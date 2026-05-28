"""
jack_pokemon_agent.py — Pokemon buyer's guide for Jason's son Jack.

Goal: surface raw (ungraded) Pokemon cards on eBay that fit Jack's tastes —
iconic Pokemon, modern chase pulls (Crown Zenith, 151, Paldean Fates,
Twilight Masquerade, Surging Sparks, Journey Together, Prismatic Evolutions),
WOTC vintage, full-art / illustration / secret rares, and Japanese holos —
then label each one DEAL / FAIR / OVERPRICED / TRAP versus the typical raw
price so Jason knows whether to pull the trigger.

Hard rules (do not relax):
  - Raw only. Any title containing PSA / BGS / CGC / SGC / "graded" / "slab"
    is dropped.
  - $5 minimum. No commons, no energies, no lots, no damaged copies.
  - Iconic Pokemon (Charizard, Pikachu, Mewtwo, Lugia, Mew, starter evos)
    or modern chase set or first-print Japanese / Pokemon Center.
  - Full-art / alt-art / illustration / secret rare OR Japanese holo gets the
    Jack ★ badge.

Sources, in order of preference:
  1. Fresh eBay Browse API queries (curated below). Needs configuration.json
     client credentials. If the token call or any individual search fails the
     agent keeps going and falls back to whatever it has.
  2. Existing pokemon_*_plan.json files in output/ (charizard, pikachu,
     mewtwo, mew, eevee) — re-filtered through the same gate.
  3. pokemon_news_plan.json chase finds.
  4. under_10_plan.json — only Pokemon buckets, only items >= $5.

Output:
  output/jack_pokemon_plan.json
  docs/jack_pokemon.html
"""

from __future__ import annotations

import html
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT = Path(__file__).parent
OUT_PLAN  = REPO_ROOT / "output" / "jack_pokemon_plan.json"
OUT_HTML  = REPO_ROOT / "docs"   / "jack_pokemon.html"
BROWSE    = "https://api.ebay.com/buy/browse/v1/item_summary/search"

MIN_PRICE = 5.0
MAX_PRICE = 1500.0           # ceiling; raw chase tops out long before
PER_CATEGORY_CAP = 36        # don't bury Jason; keep each section browsable

# Verdict thresholds vs. typical raw price
DEAL_THRESHOLD       = 0.20  # 20% or more below typical raw
OVERPRICED_THRESHOLD = 0.20  # 20% or more above typical raw

# ---------------------------------------------------------------------------- #
# Curated query set — what Jack would actually want                            #
# ---------------------------------------------------------------------------- #
# Categories double as on-page filter chips.

CATEGORIES: list[dict] = [
    {
        "key":   "modern_chase",
        "label": "Modern Chase Sets",
        "blurb": "Current English sets Jack chases — Crown Zenith, 151, "
                 "Paldean Fates, Twilight Masquerade, Surging Sparks, "
                 "Journey Together, Prismatic Evolutions.",
        "queries": [
            "pokemon crown zenith charizard alt art",
            "pokemon crown zenith galarian gallery",
            "pokemon 151 charizard ex",
            "pokemon 151 mewtwo ex",
            "pokemon 151 alakazam ex",
            "pokemon paldean fates shiny",
            "pokemon paldean fates charizard",
            "pokemon twilight masquerade illustration rare",
            "pokemon surging sparks pikachu ex",
            "pokemon journey together illustration rare",
            "pokemon prismatic evolutions",
            "pokemon prismatic evolutions umbreon",
            "pokemon prismatic evolutions sylveon",
        ],
    },
    {
        "key":   "full_art",
        "label": "Full-Art / Alt-Art / Illustration Rare",
        "blurb": "Special illustration rares, alt arts, secret rares — "
                 "the artsy chase pulls Jack actually puts in his binder.",
        "queries": [
            "pokemon special illustration rare",
            "pokemon alt art charizard ex",
            "pokemon alt art pikachu",
            "pokemon alt art mewtwo",
            "pokemon illustration rare ex",
            "pokemon secret rare full art",
            "pokemon gold star",
        ],
    },
    {
        "key":   "japanese",
        "label": "Japanese Holos & Promos",
        "blurb": "First-print Japanese holos, SARs, promos — often unique art "
                 "and cheaper than the English equivalent.",
        "queries": [
            "pokemon japanese sar special art rare",
            "pokemon japanese promo holo",
            "pokemon japanese charizard holo",
            "pokemon japanese pikachu holo",
            "pokemon japanese mew holo",
            "pokemon japanese terastal festival",
            "pokemon japanese 151 master ball",
            "pokemon japanese paradise dragona",
        ],
    },
    {
        "key":   "wotc_vintage",
        "label": "WOTC Vintage (1999–2003)",
        "blurb": "Wizards of the Coast era — Base, Jungle, Fossil, Team "
                 "Rocket, Neo, Expedition, Aquapolis, Skyridge. Raw NM only.",
        "queries": [
            "pokemon base set holo near mint",
            "pokemon jungle holo near mint",
            "pokemon fossil holo near mint",
            "pokemon team rocket holo near mint",
            "pokemon neo genesis holo near mint",
            "pokemon neo destiny shining near mint",
            "pokemon expedition holo near mint",
            "pokemon skyridge holo near mint",
            "pokemon aquapolis holo near mint",
        ],
    },
    {
        "key":   "iconic",
        "label": "Iconic Pokemon",
        "blurb": "Charizard, Pikachu, Mewtwo, Lugia, Mew, starter evolutions "
                 "— the ones that make Jack actually care.",
        "queries": [
            "pokemon charizard holo ex",
            "pokemon pikachu illustration rare",
            "pokemon mewtwo ex full art",
            "pokemon lugia v full art",
            "pokemon mew ex full art",
            "pokemon blastoise ex",
            "pokemon venusaur ex",
            "pokemon umbreon vmax alt art",
            "pokemon eevee illustration rare",
            "pokemon greninja star",
        ],
    },
    {
        "key":   "pokemon_center",
        "label": "Pokemon Center Exclusives",
        "blurb": "Pokemon Center stamped promos and special drops.",
        "queries": [
            "pokemon center exclusive promo holo",
            "pokemon center stamp promo",
            "pokemon center 25th anniversary promo",
        ],
    },
]

# ---------------------------------------------------------------------------- #
# Filter gates                                                                  #
# ---------------------------------------------------------------------------- #

GRADED_TERMS = (
    "psa", "bgs", "cgc", "sgc",
    "graded", "slab", "slabbed",
    "gem mint 10", "gem mt 10",
    "psa 10", "psa10", "psa 9", "psa9",
    "bgs 9.5", "bgs9.5",
)

DAMAGE_TERMS = (
    "played", " mp ", "(mp)", "[mp]",
    "poor", "damaged",
    "heavy whitening", "heavy edgewear",
    "creased", "creasing",
    "water damage", "bent", "torn",
    "as is", "as-is",
)

JUNK_TERMS = (
    " lot ", "lot of", "bulk", "mystery box",
    "common ", "uncommon ",
    "energy card", " energies",
    " repack", "repack ",
    "proxy", "fake",
    "custom card", "custom holo", "custom pokemon",
    "near mint or better lot",
    # Accessories / non-cards that show up in title searches
    "display case", "card display",
    "card rug", "carpet",
    "card frame", "display frame",
    " sleeve", "sleeves ",
    " binder", "binder ",
    "card protector", "protector for",
    "playmat", "play mat",
    "8.5 x 14", "8.5x14", "11 x 14", "11x14",
    "metal card", "metal pokemon",
    "fan made", "fanmade",
    "art print", "poster",
    "sticker ",
    "code card", " code only", "online code",
    # Pokemon TCG Pocket (mobile game) virtual-trade listings are not
    # physical cards Jack can put in a binder.
    "tcgp ", "tcg pocket", "tcgpocket", "pocket trade",
    "quick trade", "in-game trade", "in game trade",
    "virtual card", "digital card",
)

# A small skip list of conditions returned by the Browse API that flag raw
# damage even when the title looks fine.
BAD_CONDITIONS = (
    "heavily played", "damaged", "poor", "for parts",
)

# Words that strongly imply the listing is for a graded slab even without
# explicit grade text.
GRADER_HINTS = ("psa ", "bgs ", "cgc ", "sgc ")

FULL_ART_TERMS = (
    "alt art", "alternate art",
    "illustration rare",
    "special illustration",
    "secret rare",
    "full art", "full-art", "fa ",
    "rainbow rare",
    "gold star",
    "sar ", " sar",
    "sir ", " sir",
    "ar ", " ar",  # noisy but combined with other filters
)

JAPANESE_TERMS = (
    "japanese", "japan ", "jp ", "(jp)",
    "pokemon center jp",
    "sm-p", "s-p", "sv-p",
    "promo card pack",
)

WOTC_HINTS = (
    "1999", "2000", "2001", "2002", "2003",
    "wotc", "wizards of the coast",
    "base set", "jungle", "fossil",
    "team rocket", "neo genesis", "neo discovery",
    "neo destiny", "expedition", "aquapolis", "skyridge",
)

ICONIC_HINTS = (
    "charizard", "pikachu", "mewtwo", "lugia", "mew ",
    "blastoise", "venusaur", "umbreon", "espeon",
    "sylveon", "greninja", "rayquaza", "gardevoir",
    "gengar", "snorlax", "eevee",
)

MODERN_CHASE_SETS = (
    "crown zenith", "151",
    "paldean fates",
    "twilight masquerade",
    "surging sparks",
    "journey together",
    "prismatic evolutions",
    "obsidian flames",
    "paldea evolved",
    "temporal forces",
    "stellar crown",
    "shrouded fable",
)


def is_graded(title: str, condition: str = "") -> bool:
    t = f" {title.lower()} "
    # The eBay condition string for raw is literally "Ungraded" — checking
    # for the substring "graded" matches "Ungraded" too. Use a tighter check.
    c = (condition or "").strip().lower()
    if c in ("graded", "professionally graded", "graded slab"):
        return True
    if any(g in t for g in GRADED_TERMS):
        return True
    # A bare grader hint with a number nearby is a slab listing.
    for g in GRADER_HINTS:
        if g in t:
            return True
    return False


def is_damaged(title: str, condition: str = "") -> bool:
    t = f" {title.lower()} "
    if condition.lower() in BAD_CONDITIONS:
        return True
    return any(d in t for d in DAMAGE_TERMS)


def is_junk(title: str) -> bool:
    t = f" {title.lower()} "
    return any(j in t for j in JUNK_TERMS)


def has_any(title: str, terms) -> bool:
    t = f" {title.lower()} "
    return any(term in t for term in terms)


def is_iconic(title: str) -> bool:
    return has_any(title, ICONIC_HINTS)


def is_modern_chase(title: str) -> bool:
    return has_any(title, MODERN_CHASE_SETS)


def is_wotc(title: str) -> bool:
    return has_any(title, WOTC_HINTS)


def is_full_art(title: str) -> bool:
    return has_any(title, FULL_ART_TERMS)


def is_japanese(title: str) -> bool:
    t = title.lower()
    # Cheap precision boost — single "jp" outside a set code is too noisy.
    return any(term in t for term in JAPANESE_TERMS)


def trap_risk(title: str) -> bool:
    """Title hints at hidden condition risk even if not in DAMAGE_TERMS."""
    t = title.lower()
    return any(p in t for p in (
        "minor whitening", "light whitening",
        "edge wear", "edgewear", "swirl",
        "off-center", "off center",
        "scratch", "scuff", "scuffs",
    ))


# ---------------------------------------------------------------------------- #
# Filter pipeline (instrumented so we can report what fell out where)          #
# ---------------------------------------------------------------------------- #

def filter_pipeline(candidates: list[dict]) -> tuple[list[dict], dict]:
    """Run candidates through the gates. Returns (kept, drop_counts)."""
    counts = {
        "input": len(candidates),
        "dropped_graded": 0,
        "dropped_under_5": 0,
        "dropped_damaged": 0,
        "dropped_junk": 0,
        "dropped_not_relevant": 0,
        "kept": 0,
        "tagged_jack_star": 0,
    }
    kept: list[dict] = []
    seen_ids: set[str] = set()
    for c in candidates:
        iid = c.get("item_id") or ""
        if iid and iid in seen_ids:
            continue
        title = c.get("title") or ""
        price = float(c.get("price") or 0)
        condition = c.get("condition") or ""

        if is_graded(title, condition):
            counts["dropped_graded"] += 1
            continue
        if price < MIN_PRICE:
            counts["dropped_under_5"] += 1
            continue
        if is_damaged(title, condition):
            counts["dropped_damaged"] += 1
            continue
        if is_junk(title):
            counts["dropped_junk"] += 1
            continue
        # Must be at least one of: iconic, modern chase set, WOTC vintage,
        # full-art keyword, or Japanese holo.
        relevant = (
            is_iconic(title) or is_modern_chase(title) or is_wotc(title)
            or is_full_art(title) or is_japanese(title)
        )
        if not relevant:
            counts["dropped_not_relevant"] += 1
            continue

        c["is_full_art"] = is_full_art(title)
        c["is_japanese"] = is_japanese(title)
        c["is_wotc"]     = is_wotc(title)
        c["is_iconic"]   = is_iconic(title)
        c["is_modern_chase"] = is_modern_chase(title)
        c["jack_star"]   = c["is_full_art"] or c["is_japanese"]
        c["trap_hint"]   = trap_risk(title)

        if c["jack_star"]:
            counts["tagged_jack_star"] += 1
        kept.append(c)
        if iid:
            seen_ids.add(iid)

    counts["kept"] = len(kept)
    return kept, counts


# ---------------------------------------------------------------------------- #
# Verdict computation                                                          #
# ---------------------------------------------------------------------------- #

def classify(price: float, typical: float, trap_hint: bool) -> str:
    """DEAL / FAIR / OVERPRICED / TRAP."""
    if not typical or typical <= 0:
        return "FAIR"
    delta = (price - typical) / typical
    if delta <= -DEAL_THRESHOLD:
        return "DEAL"
    if delta >= OVERPRICED_THRESHOLD:
        return "TRAP" if trap_hint else "OVERPRICED"
    return "FAIR"


def explain(item: dict, typical: float, verdict: str) -> str:
    """One-line plain-English explanation for Jason."""
    if typical and typical > 0:
        diff = item["price"] - typical
        pct  = abs(diff) / typical * 100
        tag = item.get("category_label", "This card")
        if verdict == "DEAL":
            return (f"{tag} raw typically trades around ${typical:,.0f}. "
                    f"Asking ${item['price']:,.0f} is ${abs(diff):,.0f} "
                    f"({pct:.0f}%) under typical.")
        if verdict in ("OVERPRICED", "TRAP"):
            suffix = " and the title hints at condition risk." if verdict == "TRAP" else "."
            return (f"{tag} raw typically trades around ${typical:,.0f}. "
                    f"Asking ${item['price']:,.0f} is ${diff:,.0f} "
                    f"({pct:.0f}%) above typical{suffix}")
        return (f"{tag} raw typically trades around ${typical:,.0f}. "
                f"Asking ${item['price']:,.0f} is within the normal range.")
    return "Not enough raw comps yet. Compare against TCGplayer before pulling the trigger."


# ---------------------------------------------------------------------------- #
# Candidate fetch — fresh eBay queries with graceful fallback                  #
# ---------------------------------------------------------------------------- #

def _search(token: str, q: str, own: str) -> list[dict]:
    # eBay Browse API supports `-term` negative keywords inside q. We tack on
    # the grader brands + accessory words right in the query so we get more
    # raw-card density per call and waste less of the 60-row budget.
    augmented = (q
        + " -psa -bgs -cgc -sgc -graded -slab -slabbed"
        + " -lot -bulk -repack -proxy -fake"
        + " -binder -sleeve -playmat -display -frame -rug -carpet"
    )
    params = {
        "q": augmented,
        "limit": "60",
        "filter": (
            f"buyingOptions:{{FIXED_PRICE|AUCTION}},"
            f"itemLocationCountry:US,"
            f"price:[{MIN_PRICE}..{MAX_PRICE}],"
            f"priceCurrency:USD"
        ),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        r = requests.get(BROWSE, params=params, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"    Browse failed for '{q}': {exc}")
        return []
    items = r.json().get("itemSummaries", []) or []
    out: list[dict] = []
    for it in items:
        seller = ((it.get("seller") or {}).get("username") or "").lower()
        if own and seller == own.lower():
            continue
        try:
            price = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        iid = (it.get("itemId") or "").split("|")[-1]
        out.append({
            "item_id":   iid,
            "title":     it.get("title") or "",
            "price":     price,
            "url":       promote._epn_wrap(it.get("itemWebUrl") or ""),
            "image":     ((it.get("image") or {}).get("imageUrl")) or "",
            "buying":    it.get("buyingOptions", []) or [],
            "seller":    seller,
            "condition": it.get("condition") or "",
            "query":     q,
        })
    return out


def fetch_fresh(token: str, own: str) -> dict[str, list[dict]]:
    """Hit eBay for every query in every category. Returns per-category lists."""
    by_cat: dict[str, list[dict]] = {}
    for cat in CATEGORIES:
        print(f"  Category: {cat['label']}")
        pool: list[dict] = []
        seen: set[str] = set()
        for q in cat["queries"]:
            for it in _search(token, q, own):
                if it["item_id"] in seen:
                    continue
                seen.add(it["item_id"])
                it["category_key"]   = cat["key"]
                it["category_label"] = cat["label"]
                pool.append(it)
        print(f"    raw candidates: {len(pool)}")
        by_cat[cat["key"]] = pool
    return by_cat


# ---------------------------------------------------------------------------- #
# Fallback: pull from disk plans when fresh queries fail                       #
# ---------------------------------------------------------------------------- #

def _categorize(item: dict) -> str:
    title = item.get("title") or ""
    if is_modern_chase(title):
        return "modern_chase"
    if is_japanese(title):
        return "japanese"
    if is_full_art(title):
        return "full_art"
    if is_wotc(title):
        return "wotc_vintage"
    if is_iconic(title):
        return "iconic"
    return "iconic"  # default landing slot


def fetch_from_disk() -> dict[str, list[dict]]:
    by_cat: dict[str, list[dict]] = {c["key"]: [] for c in CATEGORIES}
    out_dir = REPO_ROOT / "output"

    # 1. Existing pokemon character plans
    for slug in ("charizard", "pikachu", "mewtwo", "mew", "eevee"):
        p = out_dir / f"pokemon_{slug}_plan.json"
        if not p.exists():
            continue
        try:
            plan = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for b in plan.get("buckets", []):
            for it in b.get("items", []):
                cat = _categorize(it)
                copy = dict(it)
                copy["category_key"]   = cat
                copy["category_label"] = next(
                    (c["label"] for c in CATEGORIES if c["key"] == cat),
                    "Iconic Pokemon",
                )
                by_cat[cat].append(copy)

    # 2. Pokemon news chase finds
    news_p = out_dir / "pokemon_news_plan.json"
    if news_p.exists():
        try:
            np_ = json.loads(news_p.read_text())
            for s in np_.get("sets", []):
                for it in s.get("items", []):
                    cat = _categorize(it) if it.get("title") else "modern_chase"
                    copy = dict(it)
                    copy["category_key"]   = "modern_chase"
                    copy["category_label"] = "Modern Chase Sets"
                    by_cat["modern_chase"].append(copy)
                for chase in s.get("chase_finds", []):
                    for it in chase.get("items", []):
                        copy = dict(it)
                        copy["category_key"]   = "modern_chase"
                        copy["category_label"] = "Modern Chase Sets"
                        by_cat["modern_chase"].append(copy)
        except (OSError, json.JSONDecodeError):
            pass

    # 3. Under $10 plan, Pokemon buckets only
    u10_p = out_dir / "under_10_plan.json"
    if u10_p.exists():
        try:
            u10 = json.loads(u10_p.read_text())
            for b in u10.get("buckets", []):
                lbl = (b.get("label") or "").lower()
                if "pokemon" not in lbl and "pikachu" not in lbl and "charizard" not in lbl:
                    continue
                for it in b.get("items", []):
                    if float(it.get("price") or 0) < MIN_PRICE:
                        continue
                    cat = _categorize(it)
                    copy = dict(it)
                    copy["category_key"]   = cat
                    copy["category_label"] = next(
                        (c["label"] for c in CATEGORIES if c["key"] == cat),
                        "Iconic Pokemon",
                    )
                    by_cat[cat].append(copy)
        except (OSError, json.JSONDecodeError):
            pass

    return by_cat


# ---------------------------------------------------------------------------- #
# Typical-price computation                                                    #
# ---------------------------------------------------------------------------- #

def typical_price(items: list[dict]) -> float | None:
    """Median price across the (already raw-only, $5+) items in a category.
    This becomes the raw comp for the verdict — if Jack's $200 Charizard sits
    in a category whose raw median is $120, Jason gets an OVERPRICED chip."""
    prices = [float(i["price"]) for i in items if i.get("price")]
    if len(prices) < 3:
        return None
    return float(statistics.median(prices))


def enrich_with_pokemontcg(item: dict, cache: dict, api_key: str) -> None:
    """Optionally pull TCGplayer market price from PokemonTCG.io. Best-effort
    — silent failure preserves the agent's tolerance for missing data."""
    try:
        info = promote.fetch_pokemontcg(item.get("title", ""), cache, api_key)
    except Exception:
        return
    if not info:
        return
    item["tcgplayer_median"] = info.get("median")
    item["tcgplayer_url"]    = info.get("url")
    item["tcgplayer_match"]  = info.get("matched_title")


# ---------------------------------------------------------------------------- #
# HTML render                                                                  #
# ---------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    cats = plan["categories"]
    total = sum(len(c["items"]) for c in cats)
    star_count = sum(1 for c in cats for it in c["items"] if it.get("jack_star"))
    deal_count = sum(1 for c in cats for it in c["items"] if it.get("verdict") == "DEAL")

    # Filter chip options
    cat_options = "".join(
        f'<option value="{_esc(c["key"])}">{_esc(c["label"])} ({len(c["items"])})</option>'
        for c in cats if c["items"]
    )

    # Build per-category sections
    sections = []
    for c in cats:
        if not c["items"]:
            sections.append(f"""
            <section class="jp-cat" data-cat="{_esc(c['key'])}">
              <header class="jp-cat-head">
                <h3>{_esc(c['label'])}</h3>
                <p class="jp-blurb">{_esc(c['blurb'])}</p>
                <span class="jp-stats">No raw listings cleared the gate.</span>
              </header>
            </section>""")
            continue

        typical = c.get("typical_price")
        typ_line = (f"raw median (this scan) ${typical:,.2f} across {len(c['items'])} listings"
                    if typical else f"{len(c['items'])} raw listings (not enough comps for median)")

        cards = []
        for it in c["items"]:
            verdict = it.get("verdict", "FAIR")
            verdict_cls = {
                "DEAL":       "jp-chip jp-chip-deal",
                "FAIR":       "jp-chip jp-chip-fair",
                "OVERPRICED": "jp-chip jp-chip-over",
                "TRAP":       "jp-chip jp-chip-trap",
            }.get(verdict, "jp-chip jp-chip-fair")
            star_html = '<span class="jp-star" title="Fits Jack — full-art or Japanese">Jack &#9733;</span>' if it.get("jack_star") else ""
            typ_for_card = it.get("typical_used") or typical or 0
            disc_pct = 0.0
            if typ_for_card and typ_for_card > 0:
                disc_pct = round((1 - it["price"] / typ_for_card) * 100, 1)
            tags = []
            if it.get("is_japanese"):  tags.append("Japanese")
            if it.get("is_full_art"):  tags.append("Full-art / SIR / SAR")
            if it.get("is_wotc"):      tags.append("WOTC vintage")
            if it.get("is_modern_chase"): tags.append("Modern chase set")
            tags_html = " &middot; ".join(_esc(t) for t in tags) if tags else "&nbsp;"
            tcg_line = ""
            if it.get("tcgplayer_median"):
                tcg_url = it.get("tcgplayer_url") or ""
                tcg_line = (f'<div class="jp-tcg"><a href="{_esc(tcg_url)}" target="_blank" rel="noopener">'
                            f'TCGplayer market ${it["tcgplayer_median"]:,.2f}</a></div>') if tcg_url else (
                            f'<div class="jp-tcg">TCGplayer market ${it["tcgplayer_median"]:,.2f}</div>')

            cards.append(f"""
            <article class="jp-card" data-cat="{_esc(c['key'])}"
                     data-price="{it['price']:.2f}"
                     data-discount="{disc_pct:.1f}"
                     data-verdict="{_esc(verdict)}"
                     data-star="{'1' if it.get('jack_star') else '0'}"
                     data-search="{_esc((it.get('title') or '').lower())}">
              <a class="jp-img-link" href="{_esc(it.get('url',''))}" target="_blank" rel="noopener">
                <div class="jp-img" style="background-image:url('{_esc(it.get('image',''))}');"></div>
              </a>
              <div class="jp-body">
                <div class="jp-row jp-row-top">
                  <span class="{verdict_cls}">{_esc(verdict)}</span>
                  {star_html}
                </div>
                <a class="jp-title" href="{_esc(it.get('url',''))}" target="_blank" rel="noopener">{_esc((it.get('title') or '')[:120])}</a>
                <div class="jp-prices">
                  <span class="jp-ask">Asking <strong>${it['price']:,.2f}</strong></span>
                  <span class="jp-typ">Typical raw ${typ_for_card:,.2f}</span>
                </div>
                {tcg_line}
                <p class="jp-why">{_esc(it.get('explanation',''))}</p>
                <div class="jp-tags">{tags_html}</div>
              </div>
            </article>""")
        sections.append(f"""
        <section class="jp-cat" data-cat="{_esc(c['key'])}">
          <header class="jp-cat-head">
            <h3>{_esc(c['label'])} <span class="jp-count">{len(c['items'])}</span></h3>
            <p class="jp-blurb">{_esc(c['blurb'])}</p>
            <span class="jp-stats">{_esc(typ_line)}</span>
          </header>
          <div class="jp-grid">{''.join(cards)}</div>
        </section>""")

    source_line = plan.get("source_label") or "Unknown source"
    generated   = plan.get("generated_at", "")

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">Pokemon buyer's guide for Jack &middot; raw cards only</div>
        <h1 class="section-title">Jack's <span class="accent">Pokemon</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Live eBay listings filtered to raw (ungraded) Pokemon cards that fit
        Jack's collecting tastes. Each card is checked against the typical raw
        price for its category so you can tell at a glance whether it is a
        deal, fair, or overpriced.
      </div>
    </div>

    <section class="jp-howto">
      <h2>How to read this page</h2>
      <p>
        Every listing shows what is being asked versus what the card typically
        sells for raw. If the ask is meaningfully below the typical raw price,
        it is a <strong>DEAL</strong>. Within plus-or-minus 20 percent it is
        <strong>FAIR</strong>. Twenty percent or more above is
        <strong>OVERPRICED</strong> &mdash; or <strong>TRAP</strong> if the title
        hints at condition risk. Cards marked <em>Jack &#9733;</em> fit his sweet
        spot: full-art / illustration rare or Japanese, and always raw.
      </p>
      <ul class="jp-rules">
        <li>Hard filter: no PSA, BGS, CGC, SGC, or slabs. Raw only.</li>
        <li>Five-dollar minimum. No lots, commons, energies, or damaged copies.</li>
        <li>Typical raw price is the median across raw comps in this scan.</li>
        <li>TCGplayer market is pulled from PokemonTCG.io when there is a match.</li>
      </ul>
    </section>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{total}</div><div class="lbl">Raw listings kept</div></div>
      <div class="stat-card"><div class="num">{deal_count}</div><div class="lbl">DEAL chips</div></div>
      <div class="stat-card"><div class="num">{star_count}</div><div class="lbl">Jack &#9733; matches</div></div>
      <div class="stat-card"><div class="num">{len([c for c in cats if c['items']])}</div><div class="lbl">Categories with picks</div></div>
    </div>

    <div class="jp-filters">
      <input type="search" id="jp-q" class="search-input"
             placeholder="Search title, set, parallel..." autocomplete="off"
             style="flex:1 1 240px; min-width:0;">
      <select id="jp-cat">
        <option value="all">All categories</option>
        {cat_options}
      </select>
      <select id="jp-verdict">
        <option value="all">Any verdict</option>
        <option value="DEAL">DEAL</option>
        <option value="FAIR">FAIR</option>
        <option value="OVERPRICED">OVERPRICED</option>
        <option value="TRAP">TRAP</option>
      </select>
      <select id="jp-max">
        <option value="0">Any price</option>
        <option value="25">Under $25</option>
        <option value="50">Under $50</option>
        <option value="100">Under $100</option>
        <option value="250">Under $250</option>
        <option value="500">Under $500</option>
      </select>
      <select id="jp-sort">
        <option value="discount">Best discount %</option>
        <option value="price-asc">Lowest price</option>
        <option value="price-desc">Highest price</option>
      </select>
      <label class="jp-only-star">
        <input type="checkbox" id="jp-star"> Jack &#9733; only
      </label>
    </div>

    {''.join(sections)}

    <div class="jp-foot">
      Source: {_esc(source_line)} &middot; refreshed {_esc(generated)}
    </div>
    """

    extra_css = """
<style>
  .jp-howto { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 18px 20px; margin: 18px 0 24px; }
  .jp-howto h2 { margin: 0 0 8px; font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; font-size: 26px; color: var(--text); }
  .jp-howto p  { margin: 0 0 10px; color: var(--text-muted); line-height: 1.55; }
  .jp-rules { margin: 8px 0 0; padding-left: 18px; color: var(--text-muted); font-size: 13px; line-height: 1.6; }

  .jp-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin: 18px 0; padding: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); }
  .jp-filters select, .jp-filters .search-input { background: var(--surface-2); border: 1px solid var(--border-mid); color: var(--text); padding: 8px 10px; border-radius: var(--r-sm); font-size: 13px; }
  .jp-only-star { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 13px; }

  .jp-cat { margin: 32px 0; }
  .jp-cat-head { margin-bottom: 14px; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
  .jp-cat-head h3 { margin: 0 0 4px; font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; font-size: 26px; }
  .jp-count { color: var(--text-muted); font-weight: 400; font-size: 14px; margin-left: 6px; }
  .jp-blurb { color: var(--text-muted); font-size: 13px; margin: 4px 0 4px; }
  .jp-stats { color: var(--text-muted); font-size: 12px; }

  .jp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 14px; }

  .jp-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; display: flex; flex-direction: column; transition: transform .15s, border-color .15s, box-shadow .15s; }
  .jp-card:hover { transform: translateY(-2px); border-color: var(--accent, var(--gold)); box-shadow: 0 8px 20px rgba(0,0,0,.18); }
  .jp-img-link { display: block; }
  .jp-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }
  .jp-body { padding: 12px 14px 14px; display: flex; flex-direction: column; gap: 6px; }
  .jp-row-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }

  .jp-chip { display: inline-block; padding: 3px 8px; border-radius: 999px; font-size: 11px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; border: 1px solid transparent; }
  .jp-chip-deal { background: rgba(127,199,122,.18); color: var(--success, #7fc77a); border-color: rgba(127,199,122,.4); }
  .jp-chip-fair { background: rgba(120,120,120,.18); color: var(--text-muted); border-color: rgba(120,120,120,.32); }
  .jp-chip-over { background: rgba(220,130,90,.18); color: #d6925e; border-color: rgba(220,130,90,.4); }
  .jp-chip-trap { background: rgba(220,80,80,.18); color: #e57373; border-color: rgba(220,80,80,.4); }

  .jp-star { font-size: 11px; padding: 3px 8px; border-radius: 999px; background: rgba(212,175,55,.16); color: var(--gold, #d4af37); border: 1px solid rgba(212,175,55,.4); letter-spacing: .04em; font-weight: 600; }

  .jp-title { display: block; color: var(--text); font-size: 13px; line-height: 1.4; text-decoration: none; margin-top: 4px; min-height: 36px; }
  .jp-title:hover { color: var(--gold, #d4af37); }

  .jp-prices { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline; font-size: 12px; color: var(--text-muted); }
  .jp-ask strong { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-size: 20px; color: var(--text); margin-left: 2px; }
  .jp-typ { color: var(--text-dim, var(--text-muted)); }

  .jp-tcg { font-size: 11px; color: var(--text-muted); }
  .jp-tcg a { color: var(--text-muted); text-decoration: underline; }
  .jp-tcg a:hover { color: var(--gold, #d4af37); }

  .jp-why { font-size: 12px; line-height: 1.45; color: var(--text-muted); margin: 4px 0 0; }
  .jp-tags { font-size: 11px; color: var(--text-dim, var(--text-muted)); margin-top: 4px; letter-spacing: .02em; }

  .jp-foot { margin: 28px 0 8px; color: var(--text-muted); font-size: 12px; text-align: center; }

  @media (max-width: 640px) {
    .jp-grid { grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
  }
</style>
<script>
  (function() {
    var q       = document.getElementById('jp-q');
    var cat     = document.getElementById('jp-cat');
    var verdict = document.getElementById('jp-verdict');
    var maxP    = document.getElementById('jp-max');
    var sort    = document.getElementById('jp-sort');
    var starOnly= document.getElementById('jp-star');
    if (!q) return;
    var grids = Array.from(document.querySelectorAll('.jp-grid'));

    function apply() {
      var term = (q.value || '').toLowerCase().trim();
      var c = cat.value, v = verdict.value;
      var mp = parseFloat(maxP.value) || 0;
      var so = sort.value;
      var only = starOnly.checked;

      grids.forEach(function(g) {
        var cards = Array.from(g.children);
        cards.forEach(function(card) {
          var ok = true;
          if (term && card.dataset.search.indexOf(term) === -1) ok = false;
          if (c !== 'all' && card.dataset.cat !== c) ok = false;
          if (v !== 'all' && card.dataset.verdict !== v) ok = false;
          if (mp && parseFloat(card.dataset.price) > mp) ok = false;
          if (only && card.dataset.star !== '1') ok = false;
          card.style.display = ok ? '' : 'none';
        });
        var visible = cards.filter(function(c) { return c.style.display !== 'none'; });
        visible.sort(function(a, b) {
          if (so === 'price-asc')  return parseFloat(a.dataset.price)    - parseFloat(b.dataset.price);
          if (so === 'price-desc') return parseFloat(b.dataset.price)    - parseFloat(a.dataset.price);
          return parseFloat(b.dataset.discount) - parseFloat(a.dataset.discount);
        });
        visible.forEach(function(c) { g.appendChild(c); });
      });

      Array.from(document.querySelectorAll('.jp-cat')).forEach(function(section) {
        var visible = section.querySelectorAll('.jp-card:not([style*="display: none"])');
        if (c !== 'all') {
          section.style.display = (section.dataset.cat === c) ? '' : 'none';
        } else {
          section.style.display = visible.length === 0 ? 'none' : '';
        }
      });
    }
    [q, cat, verdict, maxP, sort, starOnly].forEach(function(el) {
      el.addEventListener('input', apply);
      el.addEventListener('change', apply);
    });
    apply();
  })();
</script>
"""

    html_doc = promote.html_shell(
        "Jack's Pokemon · Buyer's guide for raw Pokemon cards · Harpua2001",
        body,
        extra_head=extra_css,
        active_page="jack_pokemon.html",
    )
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    return OUT_HTML


# ---------------------------------------------------------------------------- #
# Orchestration                                                                #
# ---------------------------------------------------------------------------- #

def build_plan() -> dict:
    cfg: dict = {}
    own = "harpua2001"
    token = ""
    try:
        cfg = json.loads(promote.CONFIG_FILE.read_text())
        own = cfg.get("seller_username") or own
    except (OSError, json.JSONDecodeError):
        pass

    source_label = ""
    by_cat: dict[str, list[dict]] = {c["key"]: [] for c in CATEGORIES}

    if cfg.get("client_id") and cfg.get("client_secret"):
        try:
            token = promote.get_app_token(cfg)
        except Exception as exc:
            print(f"  Token fetch failed: {exc}")
            token = ""

    if token:
        print("Using fresh eBay Browse API queries.")
        fresh = fetch_fresh(token, own)
        total_raw = sum(len(v) for v in fresh.values())
        if total_raw > 0:
            by_cat = fresh
            source_label = "Live eBay Browse API"
        else:
            print("  Fresh queries returned nothing — falling back to disk.")
    if not source_label:
        print("Falling back to on-disk Pokemon plan data.")
        by_cat = fetch_from_disk()
        total_raw = sum(len(v) for v in by_cat.values())
        source_label = "On-disk fallback (pokemon_*_plan.json + pokemon_news_plan.json + under_10_plan.json)"

    # Aggregate counts across the whole pipeline
    pipeline_totals = {
        "input": 0,
        "dropped_graded": 0,
        "dropped_under_5": 0,
        "dropped_damaged": 0,
        "dropped_junk": 0,
        "dropped_not_relevant": 0,
        "kept": 0,
        "tagged_jack_star": 0,
    }

    categories_out: list[dict] = []
    pricing_cache = promote._pricing_cache_load() if hasattr(promote, "_pricing_cache_load") else {}
    ptcg_key = cfg.get("pokemontcg_api_key") or ""

    for cat in CATEGORIES:
        raw = by_cat.get(cat["key"], [])
        kept, counts = filter_pipeline(raw)
        for k in pipeline_totals:
            pipeline_totals[k] += counts.get(k, 0)

        # Compute the in-category raw median (used as fallback typical price)
        typ = typical_price(kept)

        # Enrich a sample with PokemonTCG.io — best-effort, cap on calls to be
        # gentle on the free tier.
        for it in kept[:18]:
            enrich_with_pokemontcg(it, pricing_cache, ptcg_key)

        # Per-item verdict
        for it in kept:
            # Prefer TCGplayer market when it is in a defensible corridor
            # relative to the asking price (within 0.2x–5x). PokemonTCG.io
            # matches on name alone, so a $79 Base Charizard can get paired
            # with the $3 Evolutions reprint — that's a wrong comp, not a
            # genuine signal. Outside the corridor we fall back to the
            # in-category raw median.
            t_tcg = it.get("tcgplayer_median")
            typical_used = None
            if t_tcg and t_tcg > 0 and it["price"] > 0:
                ratio = t_tcg / it["price"]
                if 0.2 <= ratio <= 5.0:
                    typical_used = t_tcg
            if typical_used is None:
                typical_used = typ
            it["typical_used"] = typical_used
            it["verdict"]      = classify(it["price"], typical_used or 0.0,
                                          it.get("trap_hint", False))
            it["explanation"]  = explain(it, typical_used or 0.0, it["verdict"])

        # Sort: DEAL first by best discount, then FAIR by price, then others
        def _rank(it: dict) -> tuple:
            order = {"DEAL": 0, "FAIR": 1, "OVERPRICED": 2, "TRAP": 3}.get(it["verdict"], 1)
            typ_for = it.get("typical_used") or typ or 0
            disc = (1 - it["price"] / typ_for) if typ_for else 0
            return (order, -disc, it["price"])
        kept.sort(key=_rank)

        categories_out.append({
            "key":            cat["key"],
            "label":          cat["label"],
            "blurb":          cat["blurb"],
            "typical_price":  typ,
            "items":          kept[:PER_CATEGORY_CAP],
            "drop_counts":    counts,
        })

    try:
        if hasattr(promote, "_pricing_cache_save"):
            promote._pricing_cache_save(pricing_cache)
    except Exception:
        pass

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_label": source_label,
        "min_price":    MIN_PRICE,
        "categories":   categories_out,
        "pipeline":     pipeline_totals,
    }


def save_plan(plan: dict) -> Path:
    OUT_PLAN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAN.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    return OUT_PLAN


def main() -> None:
    print("Jack's Pokemon buyer's guide — building...")
    plan = build_plan()
    save_plan(plan)
    out = render_report(plan)
    p = plan["pipeline"]
    print("")
    print(f"  Source:                 {plan['source_label']}")
    print(f"  Candidates in:          {p['input']}")
    print(f"  Dropped — graded:       {p['dropped_graded']}")
    print(f"  Dropped — under $5:     {p['dropped_under_5']}")
    print(f"  Dropped — damaged:      {p['dropped_damaged']}")
    print(f"  Dropped — junk/lots:    {p['dropped_junk']}")
    print(f"  Dropped — off-topic:    {p['dropped_not_relevant']}")
    print(f"  Kept:                   {p['kept']}")
    print(f"  Tagged Jack-star:       {p['tagged_jack_star']}")
    print("")
    for c in plan["categories"]:
        typ = c.get("typical_price")
        typ_s = f"${typ:,.2f}" if typ else "—"
        print(f"  {c['label']:<40}  {len(c['items']):>3}  typical raw {typ_s}")
    print("")
    print(f"  Plan:   {OUT_PLAN}")
    print(f"  Report: {out}")
    print("")
    print('  Nav line to add to promote.py _NAV_ITEMS:')
    print('    ("jack_pokemon.html", "Jack\'s Pokemon", False, "More"),')


if __name__ == "__main__":
    main()
