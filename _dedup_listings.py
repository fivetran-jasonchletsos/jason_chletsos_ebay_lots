"""_dedup_listings.py — find & remove EXACT-title duplicate active listings to
reclaim listing-limit slots. Keeps the oldest (lowest ItemID) of each dup set,
ends the rest. Dry-run by default; pass --apply to actually end.
"""
import argparse, re, sys, time
from collections import defaultdict
import ebay_client, requests, json
from pathlib import Path

def _norm(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())

def pull_active(token, cfg):
    """Return {item_id: {'title':..., 'price':..., 'start':...}} for all active."""
    out = {}
    page = 1
    while True:
        hdr = ebay_client.trading_headers("GetMyeBaySelling", cfg, token)
        xml = (f'<?xml version="1.0" encoding="utf-8"?>'
               f'<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
               f'<ActiveList><Include>true</Include>'
               f'<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>'
               f'</ActiveList></GetMyeBaySellingRequest>')
        r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=60)
        items = re.findall(r"<Item>(.*?)</Item>", r.text, re.S)
        if not items:
            break
        for it in items:
            iid = re.search(r"<ItemID>(.*?)</ItemID>", it)
            ti = re.search(r"<Title>(.*?)</Title>", it)
            pr = re.search(r"<CurrentPrice[^>]*>(.*?)</CurrentPrice>", it) or re.search(r"<StartPrice[^>]*>(.*?)</StartPrice>", it)
            st = re.search(r"<StartTime>(.*?)</StartTime>", it)
            if iid:
                out[iid.group(1)] = {"title": ti.group(1) if ti else "",
                                     "price": pr.group(1) if pr else "",
                                     "start": st.group(1) if st else ""}
        tp = re.search(r"<TotalNumberOfPages>(\d+)</TotalNumberOfPages>", r.text)
        total = int(tp.group(1)) if tp else page
        if page >= total:
            break
        page += 1
    return out

def end(item_id, token, cfg):
    hdr = ebay_client.trading_headers("EndFixedPriceItem", cfg, token)
    xml = ('<?xml version="1.0" encoding="utf-8"?>'
           '<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f'<ItemID>{item_id}</ItemID><EndingReason>OtherListingError</EndingReason>'
           '</EndFixedPriceItemRequest>')
    r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=40)
    return re.search(r"<Ack>(.*?)</Ack>", r.text).group(1) if "<Ack>" in r.text else "?"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    token = ebay_client.get_write_token(cfg)
    active = pull_active(token, cfg)
    print(f"active listings pulled: {len(active)}")

    groups = defaultdict(list)
    for iid, d in active.items():
        groups[_norm(d["title"])].append(iid)
    dups = {t: sorted(ids, key=lambda x: int(x)) for t, ids in groups.items() if len(ids) > 1 and t}

    to_end = []
    for t, ids in dups.items():
        keep, extras = ids[0], ids[1:]   # keep oldest (lowest ItemID)
        for e in extras:
            to_end.append((e, active[e]["title"]))

    print(f"\nduplicate title groups: {len(dups)}   extra listings to end: {len(to_end)}\n")
    for t, ids in sorted(dups.items(), key=lambda kv: -len(kv[1]))[:40]:
        print(f"  x{len(ids)}  keep {ids[0]}  end {','.join(ids[1:])}  | {active[ids[0]]['title'][:52]}")
    Path("output/_dedup_plan.json").write_text(json.dumps(
        {"groups": {t: ids for t, ids in dups.items()}, "to_end": [e for e, _ in to_end]}, indent=2))

    if not a.apply:
        print(f"\nDRY RUN — would end {len(to_end)} duplicate listings (freeing {len(to_end)} slots). Re-run with --apply.")
        return
    print(f"\nEnding {len(to_end)} duplicates...")
    ok = 0
    for i, (iid, title) in enumerate(to_end, 1):
        ack = end(iid, token, cfg)
        if ack in ("Success", "Warning"): ok += 1
        if i % 25 == 0: print(f"  ...{i}/{len(to_end)}")
    print(f"\n  ENDED {ok}/{len(to_end)} duplicate listings — {ok} slots freed.")

if __name__ == "__main__":
    sys.exit(main())
