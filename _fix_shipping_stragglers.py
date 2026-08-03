"""One-off: fix the 3 listings shipping_audit_agent.py caught still using the
wrong shipping service/cost (the original 79-listing fix on 2026-08-02 missed
these). ReviseItem to the house default -- US_eBayStandardEnvelope @ $1.32."""
import json
import requests
import ebay_client
import post_from_scan as pfs

ITEM_IDS = ["307094509406", "307096980129", "307101178018"]

cfg = json.loads(open("configuration.json").read())
tok = ebay_client.get_write_token(cfg)

results = []
for item_id in ITEM_IDS:
    xml = (
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
        f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
        f'<Item><ItemID>{item_id}</ItemID>'
        f'<ShippingDetails><ShippingType>Flat</ShippingType><ShippingServiceOptions>'
        f'<ShippingServicePriority>1</ShippingServicePriority>'
        f'<ShippingService>{pfs.SHIPPING_SERVICE}</ShippingService>'
        f'<ShippingServiceCost>{pfs.SHIPPING_SERVICE_COST}</ShippingServiceCost>'
        f'</ShippingServiceOptions></ShippingDetails>'
        f'</Item></ReviseItemRequest>'
    )
    h = ebay_client.trading_headers("ReviseItem", cfg, tok)
    r = requests.post(ebay_client.TRADING_URL, headers=h, data=xml.encode(), timeout=30)
    ack = ebay_client.find_tag(r.text, "Ack") or "?"
    err = ebay_client.find_tag(r.text, "LongMessage") or ""
    print(f"{item_id}  {ack}  {err}")
    results.append({"item_id": item_id, "ack": ack, "err": err})

from pathlib import Path
Path("output/_shipping_stragglers_fix_result.json").write_text(json.dumps(results, indent=1))
ok = sum(1 for r in results if r["ack"] in ("Success", "Warning"))
print(f"\n=== {ok}/{len(ITEM_IDS)} fixed ===")
