"""End a live eBay fixed-price listing via Trading API EndFixedPriceItem.

Use this for ghost listings — items that exist on eBay but not in the
physical inventory (typically caused by a bad CollX import where a row
got auto-pushed for a card that never existed). Also flips the linkage_db
row from 'live' to 'ended' so dashboards stop showing it as active.

Usage:
  python3 end_listing.py 306965305227                # ends the listing
  python3 end_listing.py 306965305227 --reason NotAvailable
  python3 end_listing.py 306965305227 --dry-run      # show XML, don't send
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import requests

import linkage_db
from push_to_ebay import (
    CONFIG, TRADING_URL,
    get_write_token, trading_headers,
    xml_escape, find_tag,
)

NS = "urn:ebay:apis:eBLBaseComponents"

VALID_REASONS = ("NotAvailable", "Incorrect", "LostOrBroken", "OtherListingError")


def build_end_xml(token: str, item_id: str, reason: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <ItemID>{xml_escape(item_id)}</ItemID>
  <EndingReason>{reason}</EndingReason>
</EndFixedPriceItemRequest>"""


def _mark_ended_in_linkage(ebay_item_id: str, reason: str) -> int:
    """Flip the linkage row from 'live' to 'ended'. Returns rows updated."""
    with linkage_db.connect() as conn:
        cur = conn.execute(
            "UPDATE listings SET status='ended', updated_at=datetime('now') "
            "WHERE ebay_item_id = ? AND status != 'sold'",
            (ebay_item_id,),
        )
        n = cur.rowcount
        # Record the event in listing_history.
        row = conn.execute(
            "SELECT collx_id FROM listings WHERE ebay_item_id = ?",
            (ebay_item_id,),
        ).fetchone()
        collx_id = row["collx_id"] if row else None
        conn.execute(
            "INSERT INTO listing_history(collx_id, ebay_item_id, event, details) "
            "VALUES(?, ?, 'ended', ?)",
            (collx_id, ebay_item_id, f"EndFixedPriceItem reason={reason}"),
        )
        return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("item_id", help="eBay item ID to end.")
    ap.add_argument("--reason", default="NotAvailable", choices=VALID_REASONS,
                    help="Ending reason (default: NotAvailable — the card doesn't exist or can't be shipped).")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the XML that would be sent. Don't call eBay.")
    args = ap.parse_args()

    cfg = json.loads(CONFIG.read_text())
    token = get_write_token(cfg)
    body = build_end_xml(token, args.item_id, args.reason)

    if args.dry_run:
        print(body)
        return 0

    print(f"Ending eBay item {args.item_id} via Trading API EndFixedPriceItem (reason={args.reason})...")
    r = requests.post(
        TRADING_URL,
        headers=trading_headers("EndFixedPriceItem", cfg, token),
        data=body.encode("utf-8"),
        timeout=30,
    )
    ack = find_tag(r.text, "Ack") or "?"
    print(f"  HTTP {r.status_code}  Ack={ack}")
    if ack not in ("Success", "Warning"):
        msg = find_tag(r.text, "LongMessage") or find_tag(r.text, "ShortMessage") or "(no error message)"
        print(f"  ERROR: {msg}")
        return 1

    # Flip linkage_db. Failure here is NOT "non-fatal" — if eBay says ended
    # and linkage says live, every downstream dashboard (pull-aside Gate 1,
    # cassini, repricing, best_offer) will keep treating the dead listing as
    # alive indefinitely. Surface a non-zero exit so the caller knows the
    # reconcile is incomplete and a manual rerun is needed.
    linkage_ok = False
    try:
        n = _mark_ended_in_linkage(args.item_id, args.reason)
        print(f"  linkage_db: {n} row(s) marked ended")
        linkage_ok = True
    except Exception as exc:
        print(f"  linkage_db update FAILED: {exc}")
        print(f"  WARNING: eBay listing is ended but linkage_db still says live.")
        print(f"  Re-run when sqlite is unlocked:")
        print(f"      python3 -c \"import linkage_db; linkage_db.connect()."
              f"__enter__().execute(\\\"UPDATE listings SET status='ended', "
              f"updated_at=datetime('now') WHERE ebay_item_id={args.item_id}\\\")\"")

    # Also drop the listing from listings_snapshot.json so dashboards stop showing it.
    try:
        snap_path = Path(__file__).parent / "output" / "listings_snapshot.json"
        if snap_path.is_file():
            snap = json.loads(snap_path.read_text())
            listings = snap["listings"] if isinstance(snap, dict) else snap
            before = len(listings)
            listings = [l for l in listings if str(l.get("item_id")) != str(args.item_id)]
            if len(listings) < before:
                if isinstance(snap, dict):
                    snap["listings"] = listings
                    snap_path.write_text(json.dumps(snap, separators=(",", ":")))
                else:
                    snap_path.write_text(json.dumps(listings, separators=(",", ":")))
                print(f"  snapshot: removed item {args.item_id} ({before} -> {len(listings)})")
    except Exception as exc:
        print(f"  snapshot update FAILED (non-fatal): {exc}")

    print(f"Done. Item {args.item_id} is no longer live.")
    # Return non-zero if any reconcile step failed so callers (and humans)
    # know the dashboards may show stale state until manually fixed.
    return 0 if linkage_ok else 3


if __name__ == "__main__":
    sys.exit(main())
