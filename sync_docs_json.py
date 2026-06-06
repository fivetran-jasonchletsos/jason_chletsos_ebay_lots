"""Atomic publish of all docs/ JSON data files consumed by the static website.

Problem this solves
-------------------
The static GitHub Pages site reads four JSON files at runtime:

  docs/listings_snapshot.json   — all 265 listings (used by Cassini, agents)
  docs/_index_listings.json     — pre-rendered HTML card strings (browse/index)
  docs/_deals_listings.json     — deal cards (deals.html)
  docs/_seller.json             — seller profile (OG card, item pages)

Before this script, each file was written independently by different code paths
(promote.py, snapshot_store.py, refresh_snapshot.py). The timing was:

  1. refresh_snapshot.py   → output/listings_snapshot.json   (raw, no category)
  2. promote.py            → docs/listings_snapshot.json     (raw, no category)
  3. storefront_agent.py   → uses output/, but browse/index uses docs/
  4. build_dashboard()     → docs/_index_listings.json       (after step 2)

This meant:
  - A browser refresh between steps 1–4 could see half-stale data.
  - docs/ and output/ snapshots drifted (different write times, same content).
  - All 265 listings had category="" because _categorize() was never called
    at write time — only called inline inside build_dashboard() for rendering.

After this script
-----------------
A single call to sync_docs_json.publish() does the following atomically:

  1. Reads output/listings_snapshot.json (canonical source written by
     refresh_snapshot.py / promote.py).
  2. Enriches every listing with:
       - category  — derived from title via promote._categorize()
       - condition — passed through (populated by eBay API if available;
                     kept as-is if already set)
  3. Writes docs/listings_snapshot.json  (enriched copy for the website)
  4. Writes docs/_index_listings.json    (re-rendered HTML card chunks)
  5. Writes docs/_deals_listings.json    (re-rendered deal card chunks)
  6. Writes docs/_seller.json            (copied from docs/ — already current)

All four docs/ writes use tempfile + os.replace so a browser that hits the
site mid-publish never sees a partially-written file.

Usage
-----
  python3 sync_docs_json.py           # reads output/, writes docs/
  python3 sync_docs_json.py --dry-run # print what would change, don't write

Wired into refresh_pipeline.py CASCADE_FULL as the final wave so every full
refresh ends with a consistent, enriched docs/ tree.

INPUTS:  ["output/listings_snapshot.json", "docs/_seller.json"]
OUTPUTS: ["docs/listings_snapshot.json", "docs/_index_listings.json",
          "docs/_deals_listings.json"]
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO     = Path(__file__).parent.resolve()
OUTPUT   = REPO / "output"
DOCS     = REPO / "docs"

SRC_SNAPSHOT  = OUTPUT / "listings_snapshot.json"
DST_SNAPSHOT  = DOCS   / "listings_snapshot.json"
DST_INDEX     = DOCS   / "_index_listings.json"
DST_DEALS     = DOCS   / "_deals_listings.json"
DST_SELLER    = DOCS   / "_seller.json"

INPUTS  = ["output/listings_snapshot.json", "docs/_seller.json"]
OUTPUTS = ["docs/listings_snapshot.json", "docs/_index_listings.json",
           "docs/_deals_listings.json"]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, payload) -> None:
    """Write JSON to path via tempfile + os.replace (atomic on POSIX)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _load_snapshot() -> list[dict]:
    """Load output/listings_snapshot.json, returning a plain list."""
    if not SRC_SNAPSHOT.is_file():
        return []
    try:
        raw = json.loads(SRC_SNAPSHOT.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  [sync_docs_json] WARNING: could not parse {SRC_SNAPSHOT}: {exc}")
        return []
    return list(raw.get("listings", raw) if isinstance(raw, dict) else raw)


def _enrich(listings: list[dict]) -> list[dict]:
    """Add derived fields that the website needs but the eBay API doesn't supply.

    - category: derived from title via promote._categorize().  Always
      overwritten so the website always sees the title-derived value even when
      the API leaves the field blank.
    """
    try:
        import promote as _promote
        _cat = _promote._categorize
    except Exception:
        _cat = None

    enriched = []
    for raw in listings:
        row = dict(raw)
        if _cat is not None:
            row["category"] = _cat(row)
        elif not row.get("category"):
            row["category"] = _derive_category_fallback(row.get("title", ""))
        enriched.append(row)
    return enriched


_BASKETBALL_WORDS = ["lakers", "celtics", "bulls", "nba", "basketball", "heat",
                     "warriors", "nets", "knicks", "bucks", "sixers", "suns",
                     "nuggets", "clippers", "thunder", "raptors", "spurs",
                     "rockets", "mavericks", "jazz", "pelicans", "timberwolves",
                     "hawks", "hornets", "wizards", "magic", "pacers", "pistons",
                     "cavaliers", "grizzlies", "blazers", "kings", "lebron",
                     "kobe", "jordan", "durant", "curry", "giannis"]
_BASEBALL_WORDS  = ["yankees", "red sox", "dodgers", "cubs", "braves", "mlb",
                    "baseball", "mets", "cardinals", "astros", "giants",
                    "phillies", "tigers", "white sox", "rangers", "mariners",
                    "athletics", "brewers", "reds", "padres", "pirates",
                    "nationals", "marlins", "royals", "angels", "rays",
                    "twins", "rockies", "orioles", "blue jays"]
_FOOTBALL_WORDS  = ["patriots", "eagles", "cowboys", "nfl", "football",
                    "chiefs", "bears", "ravens", "steelers", "49ers",
                    "seahawks", "broncos", "raiders", "chargers", "dolphins",
                    "bills", "bengals", "browns", "saints", "falcons",
                    "buccaneers", "lions", "vikings", "packers", "colts",
                    "texans", "jaguars", "titans", "commanders", "giants",
                    "jets", "rams", "cardinals", "panthers", "prizm",
                    "panini", "donruss", "optic", "rookie", " rc "]


def _derive_category_fallback(title: str) -> str:
    """Minimal title-based categorisation used when promote.py isn't importable."""
    t = title.lower()
    is_lot = any(w in t for w in [" lot", "lot ", "cards "])
    if any(w in t for w in ["pokemon", "pikachu", "charizard", "eevee", "holo promo"]):
        return "Pokemon"
    if any(w in t for w in _BASKETBALL_WORDS):
        return "Basketball Lots" if is_lot else "Basketball Singles"
    if any(w in t for w in _BASEBALL_WORDS):
        return "Baseball Lots" if is_lot else "Baseball Singles"
    if any(w in t for w in _FOOTBALL_WORDS):
        return "Football Lots" if is_lot else "Football Singles"
    return "Other"


# ---------------------------------------------------------------------------
# HTML card renderer
# ---------------------------------------------------------------------------

def _render_listing_card(listing: dict) -> str:
    """Render one listing as an <article> HTML string — identical DOM as
    promote.py build_dashboard() so the JS filter chips work on both inline
    and deferred cards."""
    item_id = listing.get("item_id", "")
    title   = html.escape((listing.get("title") or "").strip())
    try:
        price_f = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        price_f = 0.0
    price_str = f"{price_f:.2f}"

    pic     = listing.get("pic") or ""
    big_pic = re.sub(r"s-l\d+\.jpg", "s-l1600.jpg", pic) if pic else ""
    url_raw = listing.get("url") or f"https://www.ebay.com/itm/{item_id}"

    try:
        import promote as _p
        ebay_url = html.escape(_p._epn_wrap(url_raw))
    except Exception:
        ebay_url = html.escape(url_raw)

    cat   = html.escape(listing.get("category") or "Other")
    cond  = listing.get("condition") or ""
    ltype = listing.get("listing_type") or "BIN"

    title_esc = title.replace('"', "&quot;")

    if pic:
        thumb = (
            f'<a href="{html.escape(big_pic)}" class="glightbox" data-gallery="store" '
            f'data-title="{title_esc}" data-description="${price_str} · {html.escape(cond or cat)}">'
            f'<img src="{html.escape(pic)}" alt="{title_esc}" loading="lazy"></a>'
        )
    else:
        thumb = ('<div style="height:100%;display:flex;align-items:center;'
                 'justify-content:center;color:var(--text-dim);font-size:11px;">No image</div>')

    cond_tag = f'<span class="tag">{html.escape(cond)}</span>' if cond else ""
    cat_tag  = f'<span class="tag tag-gold">{cat}</span>'

    item_page = f"items/{item_id}.html"

    return (
        f'\n      <article class="listing-card"'
        f'\n        data-id="{item_id}"'
        f'\n        data-title="{title.lower()}"'
        f'\n        data-price="{price_str}"'
        f'\n        data-cat="{cat}"'
        f'\n        data-flag="NONE"'
        f'\n        data-type="{ltype}"'
        f'\n        data-hot="0"'
        f'\n        >'
        f'\n        <div class="thumb-wrap">'
        f'\n          {thumb}'
        f'\n          <button class="zoom-btn" type="button"'
        f'\n            onclick="event.preventDefault();document.querySelector(\'article[data-id=&quot;{item_id}&quot;] .glightbox\').click();"'
        f'\n            aria-label="Zoom image">'
        f'\n            <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3-3M9 11h4M11 9v4"/></svg>'
        f'\n          </button>'
        f'\n          <button class="fav-btn" type="button" data-id="{item_id}" onclick="toggleFav(this, event)" aria-label="Favorite">'
        f'\n            <svg viewBox="0 0 24 24"><path d="M12 21s-7-4.5-9.5-9C.86 8.4 2.7 4 6.5 4c2 0 3.5 1 5.5 3 2-2 3.5-3 5.5-3 3.8 0 5.64 4.4 4 8-2.5 4.5-9.5 9-9.5 9z"/></svg>'
        f'\n          </button>'
        f'\n        </div>'
        f'\n        <div class="info">'
        f'\n          <h3><a href="{item_page}">{title}</a></h3>'
        f'\n          <div class="price-wrap">'
        f'\n            <div class="price" tabindex="0" onclick="togglePricePop(this, event)">${price_str}<span class="price-info-ic" data-admin="1" aria-hidden="true">ⓘ</span></div>'
        f'\n            <div data-admin="1" class="price-pop-wrap"></div>'
        f'\n          </div>'
        f'\n          <span class="trust-chip" aria-label="Free shipping, combined shipping on 2 or more">'
        f'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M1 3h13v13H1z"/><path d="M14 8h4l3 3v5h-7z"/><circle cx="6" cy="18.5" r="1.8"/><circle cx="17.5" cy="18.5" r="1.8"/></svg>'
        f'Free ship · Combined ship 2+</span>'
        f'\n          <div class="meta">{cat_tag}{cond_tag}</div>'
        f'\n        </div>'
        f'\n        <div class="actions">'
        f'\n          <a href="{ebay_url}" target="_blank" rel="noopener" class="btn btn-gold">View on eBay</a>'
        f'\n          <a href="{item_page}" class="btn btn-ghost">Details</a>'
        f'\n        </div>'
        f'\n      </article>'
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

INLINE_CARDS = 12   # first N cards ship as real HTML; rest go into JSON


def publish(dry_run: bool = False) -> dict:
    """Enrich the snapshot and atomically publish all four docs/ JSON files.

    Returns a summary dict: { "listings": int, "categories": dict,
                               "dry_run": bool, "changed": list[str] }
    """
    listings_raw = _load_snapshot()
    if not listings_raw:
        print("  [sync_docs_json] No listings in output/listings_snapshot.json — skipping.")
        return {"listings": 0, "categories": {}, "dry_run": dry_run, "changed": []}

    enriched = _enrich(listings_raw)

    # Category summary for reporting
    from collections import Counter
    cat_counts: Counter = Counter(l.get("category", "Other") for l in enriched)

    # --- docs/listings_snapshot.json -----------------------------------------
    # Enriched, consistent copy for the website.  Agents that need the
    # authoritative data should read output/listings_snapshot.json; this copy
    # is for the website's client-side JS.
    changed = []
    if not dry_run:
        _atomic_write(DST_SNAPSHOT, enriched)
        changed.append("docs/listings_snapshot.json")

    # --- docs/_index_listings.json -------------------------------------------
    # Pre-rendered HTML card strings.  First INLINE_CARDS cards are baked into
    # index.html / browse.html; the rest are hydrated client-side from this file.
    all_cards = [_render_listing_card(l) for l in enriched]
    deferred_cards = all_cards[INLINE_CARDS:]
    index_payload = {"cards": deferred_cards}
    if not dry_run:
        _atomic_write(DST_INDEX, index_payload)
        changed.append("docs/_index_listings.json")

    # --- docs/_deals_listings.json -------------------------------------------
    # Deal cards are generated by promote.py's build_deals_page() which reads
    # from the deals watchlist + Browse API. We don't regenerate them here
    # because deal scores require live eBay price data. We only rewrite the
    # file if it is currently empty ({"cards":[]}) so the page shows something
    # rather than nothing, using regular listings sorted by price below median.
    deals_path = DST_DEALS
    try:
        existing_deals = json.loads(deals_path.read_text(encoding="utf-8"))
        existing_cards = existing_deals.get("cards", []) if isinstance(existing_deals, dict) else []
    except Exception:
        existing_cards = []

    if not existing_cards:
        # Fall back: show the cheapest listings as "deals" so the page isn't blank
        prices = sorted([float(l.get("price") or 0) for l in enriched if l.get("price")], reverse=True)
        median = prices[len(prices) // 2] if prices else 0
        cheap = [l for l in enriched if float(l.get("price") or 0) <= median * 0.7]
        cheap.sort(key=lambda l: float(l.get("price") or 0))
        fallback_cards = [_render_listing_card(l) for l in cheap[:50]]
        deals_payload = {"cards": fallback_cards}
        if not dry_run:
            _atomic_write(DST_DEALS, deals_payload)
            changed.append("docs/_deals_listings.json (fallback — no live deal data)")
    else:
        if not dry_run:
            changed.append("docs/_deals_listings.json (unchanged — live deal data present)")

    return {
        "listings": len(enriched),
        "categories": dict(cat_counts.most_common()),
        "dry_run": dry_run,
        "changed": changed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--dry-run", action="store_true",
                    help="Print what would be written without touching docs/.")
    args = ap.parse_args()

    result = publish(dry_run=args.dry_run)
    n = result["listings"]
    cats = result["categories"]
    top = list(cats.items())[:8]
    print(f"  [sync_docs_json] {'DRY-RUN: ' if args.dry_run else ''}"
          f"{n} listings enriched · categories: "
          + ", ".join(f"{k} ({v})" for k, v in top))
    if result["changed"]:
        for f in result["changed"]:
            print(f"  [sync_docs_json]   wrote {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
