"""relist_ended.py — relist the CollX listings that the CDP inventory removal
ended (EndingReason NotAvailable). Reads output/_ended_full.json, relists each
via Trading RelistFixedPriceItem in batches of 30. Flags higher-value cards for
review. Writes output/_relist_results.json. Dry-run unless --apply.
"""
from __future__ import annotations
import argparse, json, time, re
from pathlib import Path
import requests, promote, ebay_client

ALREADY = {"307006881230"}   # Stroud test-relisted manually
FLAG_OVER = 15.0
BATCH = 30

def relist(iid, cfg, token):
    hdr = ebay_client.trading_headers("RelistFixedPriceItem", cfg, token)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<RelistFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f'<RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>'
           f'<Item><ItemID>{iid}</ItemID></Item></RelistFixedPriceItemRequest>')
    r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=40)
    ack = re.search(r"<Ack>(.*?)</Ack>", r.text)
    new = re.search(r"<ItemID>(\d+)</ItemID>", r.text)
    errs = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", r.text)
    ok = ack and ack.group(1) in ("Success", "Warning") and new
    return (new.group(1) if (ok and new) else None), (ack.group(1) if ack else "?"), errs

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    token = promote.get_access_token(cfg)
    rows = [r for r in json.loads(Path("output/_ended_full.json").read_text()) if r["item_id"] not in ALREADY]
    print(f"to relist: {len(rows)}  ({'APPLY' if a.apply else 'dry-run'})  batches of {BATCH}")
    if not a.apply:
        print("dry-run — re-run with --apply"); return
    results, ok, fail, flagged = [], 0, 0, []
    for bi in range(0, len(rows), BATCH):
        batch = rows[bi:bi+BATCH]
        for r in batch:
            new, ack, errs = relist(r["item_id"], cfg, token)
            rec = {"old": r["item_id"], "new": new, "ack": ack, "price": r["price"],
                   "title": r["title"], "errs": errs[:1]}
            results.append(rec)
            if new:
                ok += 1
                if r["price"] >= FLAG_OVER:
                    flagged.append(rec)
            else:
                fail += 1
            time.sleep(0.12)
        print(f"  batch {bi//BATCH+1}/{(len(rows)+BATCH-1)//BATCH}: relisted {ok} ok, {fail} failed so far")
        json.dump(results, open("output/_relist_results.json", "w"), indent=1)
        time.sleep(0.5)
    print(f"\nDONE: {ok} relisted, {fail} failed")
    print(f"FLAGGED for review (>= ${FLAG_OVER:.0f}): {len(flagged)}")
    for f in sorted(flagged, key=lambda x:-x["price"])[:40]:
        print(f"  ${f['price']:7.2f}  new={f['new']}  {f['title'][:50]}")
    fails = [r for r in results if not r["new"]]
    if fails:
        print(f"\nFAILURES ({len(fails)}):")
        for r in fails[:20]:
            print(f"  {r['old']}  {r['ack']}  {r['errs']}  {r['title'][:44]}")

if __name__ == "__main__":
    main()
