"""
linkage_backfill.py — populate linkage.db from current state.

Reads inventory.csv (CollX-sourced) + output/listings_snapshot.json (eBay)
and inserts rows for every CollX card with the best-inferred eBay state:
- matched via fuzzy title (from build_collx_vs_ebay logic) -> status='live',
  ebay_item_id stamped, listed_price = current eBay price
- no eBay match -> status='unlisted'

eBay-only listings (no CollX origin) are NOT added to the linkage table —
they live in listings_snapshot.json. The linkage table is "for each CollX
card, what's its eBay state."

Run:
    python3 linkage_backfill.py [--reset]   # reset wipes the listings table

Idempotent: re-running on the same data won't double-write — it UPSERTs.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path

import linkage_db

REPO_ROOT = Path(__file__).parent
INV_PATH  = REPO_ROOT / "inventory.csv"
SNAP_PATH = REPO_ROOT / "output" / "listings_snapshot.json"

MATCH_THRESHOLD = 0.62


def normalize(s: str) -> str:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def best_match(needle: str, hay: list[str]) -> tuple[int, float]:
    nn = normalize(needle)
    best_idx, best_ratio = -1, 0.0
    for i, h in enumerate(hay):
        r = SequenceMatcher(None, nn, normalize(h)).ratio()
        if r > best_ratio:
            best_idx, best_ratio = i, r
    return best_idx, best_ratio


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="Wipe the listings table first.")
    args = ap.parse_args()

    if args.reset:
        with linkage_db.connect() as conn:
            conn.execute("DELETE FROM listings")
            conn.execute("DELETE FROM listing_history")
        print("Reset: listings table cleared.")

    linkage_db.init()

    inv = list(csv.DictReader(INV_PATH.open(encoding="utf-8")))
    snap = json.loads(SNAP_PATH.read_text())
    listings = snap.get("listings", []) if isinstance(snap, dict) else snap
    titles = [l.get("title", "") for l in listings]
    listing_used = [False] * len(listings)

    matched = 0
    unlisted = 0
    for r in inv:
        cid = (r.get("collx_id") or "").strip()
        if not cid:
            continue
        title = r.get("name") or " ".join([r.get("year", ""), r.get("set", ""), r.get("player", "")])
        idx, ratio = best_match(title, titles)
        player = (r.get("player") or "").lower()
        num = (r.get("card_number") or "").strip().lstrip("#")
        cand = titles[idx] if idx >= 0 else ""
        confident_boost = bool(player and player in cand.lower()) and bool(num and (f"#{num}" in cand or f" {num} " in cand))
        confident = ratio >= MATCH_THRESHOLD or confident_boost
        if idx >= 0 and confident and not listing_used[idx]:
            listing_used[idx] = True
            l = listings[idx]
            try:
                price = float(l.get("price") or 0)
            except (TypeError, ValueError):
                price = 0.0
            linkage_db.upsert_card(
                cid,
                ebay_item_id=l.get("item_id"),
                sku=l.get("sku") or None,
                status="live",
                listed_price=price,
                current_price=price,
                notes=f"backfilled (fuzzy ratio {ratio:.2f})",
            )
            matched += 1
        else:
            linkage_db.upsert_card(
                cid,
                status="unlisted",
                notes="backfill: no eBay match found",
            )
            unlisted += 1

    linkage_db.touch_seen_in_collx([r.get("collx_id", "").strip() for r in inv if r.get("collx_id")])

    s = linkage_db.summary()
    print()
    print(f"Backfill complete:")
    print(f"  CollX rows ingested:    {len(inv)}")
    print(f"  eBay listings scanned:  {len(listings)}")
    print(f"  Linked (live):          {matched}")
    print(f"  Unlisted:               {unlisted}")
    print(f"  eBay-only (skipped):    {sum(1 for u in listing_used if not u)}")
    print()
    print(f"DB summary: {s}")
    print(f"DB file:    {linkage_db.DB_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
