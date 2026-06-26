"""
oversell_guard.py — stop sold cards from being live (oversell protection).

Two failure modes it catches, both seen after CollX inventory churn:
  1. OVERSELL: a SKU that has already SOLD is still ACTIVE (a sold card got
     re-listed). For unique cards (qty 1) this double-sells inventory you no
     longer have. -> END the active listing.
  2. DUP: the same SKU is live on >1 active listing (duplicate). -> keep the
     oldest (lowest ItemID), END the rest.

Dry-run by default. Pass --apply to actually end listings. Safe to run on a
schedule / in the daily routine as a backstop.

    python3 oversell_guard.py            # report only
    python3 oversell_guard.py --apply    # end the offenders
"""
from __future__ import annotations
import argparse, json, re, time
from collections import defaultdict
from pathlib import Path
import requests, promote, ebay_client

SOLD_DAYS = 30


def _pull(list_type: str, token: str, cfg: dict, days: int | None = None) -> dict:
    hdr = ebay_client.trading_headers("GetMyeBaySelling", cfg, token)
    out, page = {}, 1
    while page <= 20:
        dur = f"<DurationInDays>{days}</DurationInDays>" if days else ""
        xml = (f'<?xml version="1.0" encoding="utf-8"?>'
               f'<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
               f'<RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>'
               f'<{list_type}><Include>true</Include>{dur}'
               f'<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>'
               f'</{list_type}></GetMyeBaySellingRequest>')
        r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=90)
        items = re.findall(r"<Item>(.*?)</Item>", r.text, re.S)
        if not items:
            break
        for it in items:
            iid = re.search(r"<ItemID>(\d+)</ItemID>", it)
            sku = re.search(r"<SKU>(.*?)</SKU>", it)
            ti = re.search(r"<Title>(.*?)</Title>", it)
            if iid and sku:
                out[iid.group(1)] = {"sku": sku.group(1), "title": ti.group(1) if ti else ""}
        tp = re.search(rf"<{list_type}>.*?<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", r.text, re.S)
        if tp and page >= int(tp.group(1)):
            break
        page += 1
        time.sleep(0.2)
    return out


def _end(item_id: str, token: str, cfg: dict) -> str:
    hdr = ebay_client.trading_headers("EndFixedPriceItem", cfg, token)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f'<RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>'
           f'<ItemID>{item_id}</ItemID><EndingReason>NotAvailable</EndingReason></EndFixedPriceItemRequest>')
    r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=30)
    ack = re.search(r"<Ack>(.*?)</Ack>", r.text)
    return ack.group(1) if ack else "?"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    token = promote.get_access_token(cfg)

    active = _pull("ActiveList", token, cfg)
    sold = _pull("SoldList", token, cfg, days=SOLD_DAYS)
    print(f"active(SKU): {len(active)}  sold {SOLD_DAYS}d(SKU): {len(sold)}")

    by_sku = defaultdict(list)
    for iid, d in active.items():
        by_sku[d["sku"]].append(iid)
    sold_skus = {d["sku"] for d in sold.values() if d["sku"]}

    # Title-based sold set (SoldList SKU is unreliable + Trading relists carry no
    # SKU), so also match by normalized title against SoldList + sold_history.json.
    norm = lambda t: re.sub(r"[^a-z0-9]", "", (t or "").lower())
    sold_titles = {norm(d["title"]) for d in sold.values() if d.get("title")}
    sh = Path("sold_history.json")
    if sh.exists():
        for s in json.loads(sh.read_text()):
            if s.get("title"):
                sold_titles.add(norm(s["title"]))

    # 1) oversell: active listing whose SKU already sold OR whose title matches a sold card
    oversell = [(iid, active[iid]) for iid in active
                if active[iid]["sku"] in sold_skus
                or (len(norm(active[iid]["title"])) > 14 and norm(active[iid]["title"]) in sold_titles)]
    # 2) dup: same SKU live more than once -> end all but the oldest (min ItemID)
    dups = []
    for sku, ids in by_sku.items():
        if len(ids) > 1:
            for extra in sorted(ids, key=int)[1:]:
                dups.append((extra, active[extra]))

    to_end = {iid: info for iid, info in oversell + dups}
    print(f"\nOVERSELL (sold SKU still active): {len(oversell)}")
    for iid, d in oversell:
        print(f"  END {iid}  {d['sku']}  {d['title'][:48]}")
    print(f"\nDUPLICATE (same SKU live >1x): {len(dups)}")
    for iid, d in dups:
        print(f"  END {iid}  {d['sku']}  {d['title'][:48]}")

    json.dump([{"item_id": i, **info} for i, info in to_end.items()],
              open("output/_oversell_guard.json", "w"), indent=1)
    if not to_end:
        print("\nClean — nothing to end.")
        return
    if not args.apply:
        print(f"\nDRY RUN — {len(to_end)} would be ended. Re-run with --apply.")
        return
    ok = 0
    for iid in to_end:
        if _end(iid, token, cfg) in ("Success", "Warning"):
            ok += 1
        time.sleep(0.15)
    print(f"\nEnded {ok}/{len(to_end)} offending listings.")


if __name__ == "__main__":
    main()
