"""Scan all active listings for dead stock: oldest + zero-watcher + zero-sales,
lowest price first. Excludes lots (just marked down) and auctions. Builds a
ranked end-list. Scan-only by default; --end N ends the top N via EndFixedPriceItem."""
import argparse, json, datetime as dt
import xml.etree.ElementTree as ET
from pathlib import Path
import requests, ebay_client

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
def T(el, path):
    x = el.find(path, NS); return x.text if x is not None else None

def scan(cfg, tok):
    items = []; page = 1
    while True:
        body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <IncludeWatchCount>true</IncludeWatchCount>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
</GetMyeBaySellingRequest>"""
        h = ebay_client.trading_headers("GetMyeBaySelling", cfg, tok)
        r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
        root = ET.fromstring(r.text)
        al = root.find(".//e:ActiveList", NS)
        if al is None: break
        batch = al.findall(".//e:Item", NS)
        if not batch: break
        for it in batch:
            items.append(it)
        total_pages = T(al, "e:PaginationResult/e:TotalNumberOfPages")
        if not total_pages or page >= int(total_pages): break
        page += 1
    return items

def parse(it):
    iid = T(it, "e:ItemID"); title = T(it, "e:Title") or ""
    price = T(it, "e:SellingStatus/e:CurrentPrice") or T(it, "e:BuyItNowPrice") or "0"
    watch = int(T(it, "e:WatchCount") or 0)
    sold  = int(T(it, "e:SellingStatus/e:QuantitySold") or 0)
    ltype = T(it, "e:ListingType") or ""
    start = T(it, "e:ListingDetails/e:StartTime")
    age = None
    if start:
        try:
            s = dt.datetime.fromisoformat(start.replace("Z", "+00:00"))
            age = (dt.datetime.now(dt.timezone.utc) - s).days
        except Exception: pass
    return {"id": iid, "title": title, "price": float(price), "watch": watch,
            "sold": sold, "type": ltype, "age": age}

def is_lot(t):
    t = t.lower(); return " lot" in t or "lot of" in t or t.startswith("lot")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--end", type=int, default=0); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    tok = ebay_client.get_write_token(cfg)
    raw = scan(cfg, tok)
    rows = [parse(it) for it in raw]
    active = [r for r in rows if r["id"]]
    # dead-stock candidates: fixed-price, zero watchers, zero sales, not a lot
    cand = [r for r in active
            if r["type"] != "Auction" and r["watch"] == 0 and r["sold"] == 0 and not is_lot(r["title"])]
    # rank: oldest first, then cheapest (clear the low-value long-tail)
    cand.sort(key=lambda r: (-(r["age"] or 0), r["price"]))
    Path("output/_dead_stock.json").write_text(json.dumps(cand, indent=1))
    print(f"active scanned: {len(active)}  |  dead-stock candidates: {len(cand)}")
    ages = [r["age"] for r in cand if r["age"] is not None]
    if ages: print(f"age range: {min(ages)}-{max(ages)} days  |  candidates >60d: {sum(1 for x in ages if x>60)}  >90d: {sum(1 for x in ages if x>90)}")
    print(f"\nTop 30 dead-stock (oldest, no watchers, no sales):")
    for r in cand[:30]:
        print(f'  {str(r["age"]):>4}d  ${r["price"]:>6.2f}  w{r["watch"]}  {r["id"]}  {r["title"][:52]}')
    if a.end:
        end = cand[:a.end]
        print(f"\n=== ENDING {len(end)} listings (NotAvailable) ===")
        ok = err = 0
        for r in end:
            body = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>
  <ItemID>{r['id']}</ItemID><EndingReason>NotAvailable</EndingReason>
</EndFixedPriceItemRequest>"""
            h = ebay_client.trading_headers("EndFixedPriceItem", cfg, tok)
            resp = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
            ack = ebay_client.find_tag(resp.text, "Ack") or "?"
            if ack in ("Success", "Warning"): ok += 1
            else:
                err += 1; print(f'  FAIL {r["id"]}: {ebay_client.find_tag(resp.text,"LongMessage")}')
        print(f"ended: {ok} · failed: {err}")

if __name__ == "__main__": main()
