"""Morning-routine step: pull (end) any active listing over 60 days old, first
archiving its full data to output/pulled_repository.json so it can be relisted
when there's listing-slot room. Excludes lots (JC manages those) and watched
items. Dry-run default; --apply to archive + end.

Standing rule (JC 2026-07-08): 60+ day posts get pulled every morning run."""
import argparse, json, datetime as dt
from pathlib import Path
import requests, ebay_client
from _dead_stock import scan, parse, is_lot

DEFAULT_AGE = 60
REPO = Path("output/pulled_repository.json")
DNR = Path("output/do_not_relist.json")  # relist_agent skips these item_ids

def load_repo():
    if REPO.exists():
        try: return json.load(open(REPO))
        except Exception: return []
    return []

def end_listing(iid, cfg, tok):
    body = (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
            f'<ItemID>{iid}</ItemID><EndingReason>NotAvailable</EndingReason>'
            f'</EndFixedPriceItemRequest>')
    h = ebay_client.trading_headers("EndFixedPriceItem", cfg, tok)
    r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
    ack = ebay_client.find_tag(r.text, "Ack") or "?"
    return ack in ("Success", "Warning"), (ebay_client.find_tag(r.text, "LongMessage") or "")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true")
    ap.add_argument("--days", type=int, default=DEFAULT_AGE, help="pull listings older than N days (routine uses 60)")
    a = ap.parse_args(); AGE_LIMIT = a.days
    cfg = json.loads(Path("configuration.json").read_text()); tok = ebay_client.get_write_token(cfg)
    watched = set(json.load(open("output/_watched_ids.json"))) if Path("output/_watched_ids.json").exists() else set()
    snap = json.load(open("output/listings_snapshot.json"))
    L = snap.get("listings", snap) if isinstance(snap, dict) else snap
    meta = {str(x.get("item_id")): x for x in L}

    rows = [parse(it) for it in scan(cfg, tok)]
    old = [r for r in rows if r["id"] and (r["age"] or 0) > AGE_LIMIT
           and r["sold"] == 0 and not is_lot(r["title"]) and r["id"] not in watched]
    old.sort(key=lambda r: -(r["age"] or 0))
    print(f"active over {AGE_LIMIT}d (zero-sale, non-lot, unwatched): {len(old)}")
    for r in old: print(f'  {r["age"]:>3}d  ${r["price"]:>6.2f}  {r["id"]}  {r["title"][:54]}')
    if not a.apply:
        print("\nDRY-RUN. Re-run with --apply to archive + end."); return

    repo = load_repo(); have = {e["item_id"] for e in repo}
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    ok = err = 0; fails = []
    for r in old:
        m = meta.get(r["id"], {})
        good, msg = end_listing(r["id"], cfg, tok)
        if good:
            ok += 1
            if r["id"] not in have:
                repo.append({"item_id": r["id"], "title": r["title"], "price": r["price"],
                             "sku": m.get("sku"), "category": m.get("category"),
                             "pic": m.get("pic"), "url": m.get("url"),
                             "listing_type": m.get("listing_type"),
                             "age_at_pull": r["age"], "pulled": stamp, "reason": "over-60-days"})
        else:
            err += 1; fails.append((r["id"], msg))
    REPO.write_text(json.dumps(repo, indent=1))
    # Add pulled ids to do_not_relist so relist_agent doesn't resurrect them
    # (they'd otherwise reappear in UnsoldList and undo the slot-freeing).
    dnr = set(str(x) for x in (json.load(open(DNR)) if DNR.exists() else []))
    dnr.update(str(e["item_id"]) for e in repo)
    DNR.write_text(json.dumps(sorted(dnr), indent=1))
    print(f"\n=== PULLED: {ok} ended + archived · {err} failed · repository now {len(repo)} · do-not-relist {len(dnr)} ===")
    for f in fails: print(f'  FAIL {f[0]}: {f[1]}')

if __name__ == "__main__": main()
