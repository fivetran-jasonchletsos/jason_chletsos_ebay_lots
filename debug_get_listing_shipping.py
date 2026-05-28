"""Pull ShippingDetails from one of Jason's live listings so we can mirror its
exact shape in push_to_ebay.py. Reads the first item from listings_snapshot.json
and calls Trading API GetItem.
"""
import base64, json, sys
from pathlib import Path
import requests

REPO = Path(__file__).parent
cfg = json.loads((REPO / "configuration.json").read_text())
items = json.loads((REPO / "output" / "listings_snapshot.json").read_text())
items = items.get("listings") or items.get("items") or items
item_id = items[0]["item_id"]

basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
r = requests.post(
    "https://api.ebay.com/identity/v1/oauth2/token",
    headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
    data={"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"],
          "scope": "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly"},
    timeout=30,
)
r.raise_for_status()
token = r.json()["access_token"]

body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
  <IncludeItemSpecifics>true</IncludeItemSpecifics>
</GetItemRequest>"""

headers = {
    "X-EBAY-API-SITEID": "0",
    "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
    "X-EBAY-API-CALL-NAME": "GetItem",
    "X-EBAY-API-APP-NAME": cfg["client_id"],
    "X-EBAY-API-DEV-NAME": cfg.get("dev_id", ""),
    "X-EBAY-API-CERT-NAME": cfg["client_secret"],
    "X-EBAY-API-IAF-TOKEN": token,
    "Content-Type": "text/xml",
}
resp = requests.post("https://api.ebay.com/ws/api.dll", headers=headers, data=body.encode(), timeout=30)

import re
print(f"ItemID: {item_id}")
print(f"HTTP: {resp.status_code}")
# Extract ShippingDetails block + ListingType + PaymentMethods
for tag in ["PrimaryCategory", "ConditionID", "ConditionDisplayName", "ShippingDetails", "PaymentMethods", "ReturnPolicy", "SellerProfiles", "ListingType", "DispatchTimeMax", "BusinessSellerDetails", "ShipToLocations", "PostalCode"]:
    m = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", resp.text)
    if m:
        print(f"\n=== {tag} ===")
        print(m.group(0)[:1800])
