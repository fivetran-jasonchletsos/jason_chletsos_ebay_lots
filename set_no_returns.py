"""
set_no_returns.py — revise all active listings to ReturnsNotAccepted.

Usage:
    python3 set_no_returns.py           # dry run
    python3 set_no_returns.py --apply   # push to eBay
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import requests

import ebay_client
import paths

NS          = ebay_client.NS
TRADING_URL = ebay_client.TRADING_URL


def revise_return_policy(item_id: str, token: str, cfg: dict) -> tuple[bool, str]:
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{ebay_client.xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption>
    </ReturnPolicy>
  </Item>
</ReviseItemRequest>"""

    headers = ebay_client.trading_headers("ReviseItem", cfg, token)
    resp = requests.post(TRADING_URL, headers=headers, data=xml.encode("utf-8"), timeout=30)
    body = resp.text

    ack = ebay_client.find_tag(body, "Ack")
    errors = ebay_client.find_all(body, "ShortMessage")
    return ack in ("Success", "Warning"), "; ".join(errors) if errors else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    cfg = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)

    snapshot_path = Path("output/listings_snapshot.json")
    data = json.loads(snapshot_path.read_text())
    listings = data.get("listings", data) if isinstance(data, dict) else data
    item_ids = [str(l["item_id"]) for l in listings if l.get("item_id")]

    print(f"  Listings to update: {len(item_ids)}")
    if not args.apply:
        print("  [dry-run] would set ReturnsNotAccepted on all listings")
        print("  Re-run with --apply to push changes.")
        return

    ok = fail = 0
    for i, item_id in enumerate(item_ids, 1):
        success, err = revise_return_policy(item_id, token, cfg)
        if success:
            ok += 1
        else:
            fail += 1
            print(f"  FAIL {item_id}: {err}")
        if i % 25 == 0:
            print(f"  [{i}/{len(item_ids)}] ok={ok} fail={fail}")
            time.sleep(1)  # brief pause every 25 to stay under rate limits

    print(f"\n  Done. {ok} updated, {fail} failed.")


if __name__ == "__main__":
    main()
