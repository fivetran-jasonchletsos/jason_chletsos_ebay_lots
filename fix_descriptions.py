"""
fix_descriptions.py -- one-time sweep: correct the volume-discount line in
live listing descriptions.

Old text (baked into every post_from_scan listing until 2026-08-15):
    "Buy 2 save 5%, buy 5 save 12%, buy 10 save 20%"
advertised tiers that never existed on eBay (the live promo, re-enabled
2026-08-15, is buy 2/3/4 -> 3/6/10%). This script GetItems every active
listing, and where the old text appears, revises ONLY the description.

Resumable: progress persists to output/description_fix_log.json keyed by
item_id, so re-runs skip finished items. Inventory-API (CollX) listings
reject Trading ReviseItem (error 21919474) -- those are logged and skipped.

Usage: python3 fix_descriptions.py [--apply] [--limit N]
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

import ebay_client
import paths

NS          = ebay_client.NS
TRADING_URL = ebay_client.TRADING_URL
SNAPSHOT    = Path("output/listings_snapshot.json")
LOG_PATH    = Path("output/description_fix_log.json")

OLD_LINE = "Buy 2 save 5%, buy 5 save 12%, buy 10 save 20%"
NEW_LINE = "Buy 2 save 3%, buy 3 save 6%, buy 4+ save 10%"

PACE_SECONDS = 0.5  # ~2 calls/sec against the Trading API


def _load_log() -> dict:
    if LOG_PATH.exists():
        try:
            return json.loads(LOG_PATH.read_text())
        except json.JSONDecodeError:
            pass
    return {}


def _save_log(log: dict) -> None:
    LOG_PATH.write_text(json.dumps(log, indent=1))


class TradingCallLimit(Exception):
    """Raised when eBay reports the daily Trading API call cap is exhausted."""


def get_description(item_id: str, token: str, cfg: dict) -> str | None:
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{NS}">
<RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
<ItemID>{item_id}</ItemID>
<DetailLevel>ReturnAll</DetailLevel>
<IncludeItemSpecifics>false</IncludeItemSpecifics>
</GetItemRequest>'''
    headers = ebay_client.trading_headers("GetItem", cfg, token)
    r = requests.post(TRADING_URL, headers=headers, data=xml.encode("utf-8"), timeout=30)
    if "Call usage limit has been reached" in r.text:
        raise TradingCallLimit(item_id)
    m = re.search(r"<Description>(.*?)</Description>", r.text, re.S)
    if not m:
        # Distinguish a real empty description from any other API failure --
        # failures must NOT be logged as done (2026-08-15: 1,260 rate-limit
        # errors were logged "no_desc" and would have been silently skipped).
        ack = re.search(r"<Ack>(.*?)</Ack>", r.text)
        if not ack or ack.group(1) not in ("Success", "Warning"):
            raise requests.RequestException(f"GetItem failed for {item_id}")
        return None
    desc = m.group(1)
    if desc.startswith("<![CDATA["):
        desc = desc[len("<![CDATA["):]
        if desc.endswith("]]>"):
            desc = desc[:-3]
    return desc


def revise_description(item_id: str, new_desc: str, token: str, cfg: dict) -> tuple[bool, str]:
    xml = f'''<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <Description><![CDATA[{new_desc}]]></Description>
  </Item>
</ReviseItemRequest>'''
    headers = ebay_client.trading_headers("ReviseItem", cfg, token)
    r = requests.post(TRADING_URL, headers=headers, data=xml.encode("utf-8"), timeout=30)
    ack = re.search(r"<Ack>(.*?)</Ack>", r.text)
    ack = ack.group(1) if ack else "Unknown"
    if ack in ("Success", "Warning"):
        return True, ack
    errs = [e for e in re.findall(r"<ShortMessage>(.*?)</ShortMessage>", r.text)
            if "business policies" not in e]
    return False, "; ".join(errs) or ack


def main() -> int:
    apply = "--apply" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    cfg   = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)

    raw = json.loads(SNAPSHOT.read_text())
    listings = raw.get("listings", raw) if isinstance(raw, dict) else raw
    log = _load_log()

    todo = [str(l["item_id"]) for l in listings
            if str(l.get("item_id")) and str(l.get("item_id")) not in log]
    # Per-run safety cap (2026-08-16 panel): yesterday an uncapped sweep ate the
    # ENTIRE daily Trading quota and blinded order reads + blocked postings for
    # 12+ hours. Never again -- leave headroom for the store's real operations.
    MAX_PER_RUN = 600
    if len(todo) > MAX_PER_RUN and not limit:
        print(f"  capping run at {MAX_PER_RUN} of {len(todo)} remaining (quota headroom)")
        todo = todo[:MAX_PER_RUN]
    if limit:
        todo = todo[:limit]
    print(f"{len(listings)} active · {len(log)} already processed · {len(todo)} to scan"
          f" · mode={'APPLY' if apply else 'dry-run'}")

    counts = {"fixed": 0, "clean": 0, "would_fix": 0, "no_desc": 0, "revise_failed": 0}
    for i, item_id in enumerate(todo, 1):
        time.sleep(PACE_SECONDS)
        try:
            desc = get_description(item_id, token, cfg)
        except TradingCallLimit:
            print(f"  [{i}/{len(todo)}] daily Trading API call limit reached — "
                  f"stopping; {len(todo) - i + 1} items remain for the next run "
                  "(limit resets midnight PT)")
            break
        except requests.RequestException as exc:
            print(f"  [{i}/{len(todo)}] {item_id} GetItem error: {exc} — will retry next run")
            continue
        if desc is None:
            log[item_id] = "no_desc"
            counts["no_desc"] += 1
        elif OLD_LINE not in desc:
            log[item_id] = "clean"
            counts["clean"] += 1
        elif not apply:
            log[item_id] = "would_fix"
            counts["would_fix"] += 1
        else:
            ok, msg = revise_description(item_id, desc.replace(OLD_LINE, NEW_LINE), token, cfg)
            if ok:
                log[item_id] = "fixed"
                counts["fixed"] += 1
            else:
                log[item_id] = f"revise_failed:{msg[:90]}"
                counts["revise_failed"] += 1
                print(f"  [{i}/{len(todo)}] {item_id} revise FAILED: {msg[:90]}")
        if i % 50 == 0:
            _save_log(log)
            print(f"  [{i}/{len(todo)}] progress — {counts}")
    _save_log(log)
    print(f"\nDone. {counts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
