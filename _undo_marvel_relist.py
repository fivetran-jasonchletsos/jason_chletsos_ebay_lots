"""One-off: relist_agent.py --apply relisted all 47 Marvel cards that were
deliberately pulled tonight (JC is keeping the physical cards, not selling
them) -- relist_agent had no way to know these were intentionally-ended,
not unsold-should-relist. Ending the 47 newly-created listings immediately."""
import json
import requests
import snapshot_store
from ebay_client import CONFIG, TRADING_URL, get_write_token, trading_headers, find_tag
from end_listing import build_end_xml, _mark_ended_in_linkage

d = json.loads(open("output/_marvel_pull_result.json").read())
marvel_old_ids = {r["item_id"] for r in d}

plan = json.loads(open("output/relist_plan.json").read())
new_ids = []
for p in plan["plans"]:
    if p["item_id"] in marvel_old_ids and p.get("relist_result", {}).get("new_item_id"):
        new_ids.append(p["relist_result"]["new_item_id"])

print(f"Ending {len(new_ids)} newly-relisted Marvel items...")

cfg = json.loads(CONFIG.read_text())
token = get_write_token(cfg)

results = []
for item_id in new_ids:
    body = build_end_xml(token, item_id, "NotAvailable")
    r = requests.post(TRADING_URL, headers=trading_headers("EndFixedPriceItem", cfg, token),
                       data=body.encode("utf-8"), timeout=30)
    ack = find_tag(r.text, "Ack") or "?"
    ok = ack in ("Success", "Warning")
    if ok:
        try:
            _mark_ended_in_linkage(item_id, "NotAvailable")
        except Exception:
            pass
        try:
            snapshot_store.remove_listing(str(item_id))
        except Exception:
            pass
    print(f"  {item_id}  {ack}")
    results.append({"item_id": item_id, "ack": ack})

ok_n = sum(1 for r in results if r["ack"] in ("Success", "Warning"))
print(f"\n=== re-ended {ok_n}/{len(new_ids)} ===")
json.dump(results, open("output/_undo_marvel_relist_result.json", "w"), indent=1)
