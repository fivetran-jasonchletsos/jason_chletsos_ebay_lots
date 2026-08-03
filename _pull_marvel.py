"""One-off: JC decided to keep the physical Marvel cards rather than sell them.
None of the 47 active Marvel listings have sold (confirmed against
sold_history.json) -- end them all and flip linkage/snapshot state, reusing
end_listing.py's helpers so every downstream dashboard stays consistent."""
import json
import requests
import snapshot_store
from pathlib import Path
from ebay_client import CONFIG, TRADING_URL, get_write_token, trading_headers, find_tag
from end_listing import build_end_xml, _mark_ended_in_linkage

d = json.loads(open("output/listings_snapshot.json").read())
listings = d.get("listings", d) if isinstance(d, dict) else d
marvel = [l for l in listings if "marvel" in l.get("title", "").lower()]
print(f"Ending {len(marvel)} active Marvel listings (reason=NotAvailable)...")

cfg = json.loads(CONFIG.read_text())
token = get_write_token(cfg)

results = []
for l in marvel:
    item_id = l["item_id"]
    body = build_end_xml(token, item_id, "NotAvailable")
    r = requests.post(TRADING_URL, headers=trading_headers("EndFixedPriceItem", cfg, token),
                       data=body.encode("utf-8"), timeout=30)
    ack = find_tag(r.text, "Ack") or "?"
    ok = ack in ("Success", "Warning")
    if ok:
        try:
            _mark_ended_in_linkage(item_id, "NotAvailable")
        except Exception as exc:
            print(f"  {item_id} linkage_db update FAILED: {exc}")
        try:
            snapshot_store.remove_listing(str(item_id))
        except Exception as exc:
            print(f"  {item_id} snapshot update FAILED: {exc}")
    print(f"  {item_id}  {l['title'][:55]:55s}  {ack}")
    results.append({"item_id": item_id, "title": l["title"], "ack": ack})

ok_n = sum(1 for r in results if r["ack"] in ("Success", "Warning"))
print(f"\n=== ended {ok_n}/{len(marvel)} ===")
Path("output/_marvel_pull_result.json").write_text(json.dumps(results, indent=1))
