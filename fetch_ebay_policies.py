"""
fetch_ebay_policies.py — pull harpua2001's eBay Business Policies (shipping,
return, payment) so push_to_ebay.py can reference them by ID instead of sending
inline ShippingDetails / ReturnPolicy blocks. Store accounts have Business
Policies enabled by default; AddFixedPriceItem rejects inline shipping blocks
when the account is opted-in, with error 37 "Input data is invalid."

Run once, prints the policies, and caches them to ebay_policies.json for
push_to_ebay.py to read.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).parent
CFG_PATH  = REPO_ROOT / "configuration.json"
OUT_PATH  = REPO_ROOT / "ebay_policies.json"

OAUTH_URL = "https://api.ebay.com/identity/v1/oauth2/token"
ACCT_BASE = "https://api.ebay.com/sell/account/v1"
MARKETPLACE = "EBAY_US"

SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.account",
])


def get_token(cfg: dict) -> str:
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post(OAUTH_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"], "scope": SCOPES},
        timeout=30)
    if not r.ok:
        raise SystemExit(f"OAuth failed ({r.status_code}): {r.text[:400]}")
    return r.json()["access_token"]


def fetch(token: str, path: str) -> dict:
    r = requests.get(f"{ACCT_BASE}/{path}?marketplace_id={MARKETPLACE}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=30)
    if r.status_code == 200:
        return r.json()
    return {"_error": r.status_code, "_body": r.text[:600]}


def show(label: str, key: str, data: dict) -> list[dict]:
    print()
    print(f"=== {label} ===")
    if data.get("_error"):
        print(f"  HTTP {data['_error']}: {data['_body']}")
        return []
    rows = data.get(key, [])
    if not rows:
        print("  (none — account may not have Business Policies opted-in for this category)")
        return []
    for p in rows:
        pid = p.get(f"{key.rstrip('s')}Id") or p.get("paymentPolicyId") or p.get("returnPolicyId") or p.get("fulfillmentPolicyId")
        print(f"  {p.get('name','(no name)')}")
        print(f"    id:   {pid}")
        if p.get("description"):
            print(f"    desc: {p['description']}")
        if p.get("marketplaceId"):
            print(f"    marketplace: {p['marketplaceId']}")
    return rows


def main() -> int:
    cfg = json.loads(CFG_PATH.read_text())
    print("Fetching OAuth token…")
    token = get_token(cfg)
    print("Fetching policies from /sell/account/v1…")

    fulfill = fetch(token, "fulfillment_policy")
    ret     = fetch(token, "return_policy")
    pay     = fetch(token, "payment_policy")

    fp = show("Fulfillment (shipping) policies", "fulfillmentPolicies", fulfill)
    rp = show("Return policies",                 "returnPolicies",     ret)
    pp = show("Payment policies",                "paymentPolicies",    pay)

    cache = {
        "marketplace":    MARKETPLACE,
        "fulfillment":    fp,
        "return":         rp,
        "payment":        pp,
    }
    OUT_PATH.write_text(json.dumps(cache, indent=2))
    print()
    print(f"Cached -> {OUT_PATH}")
    print()
    print("If all three categories returned policies, Business Policies are enabled on")
    print("the account and push_to_ebay.py must reference them via <SellerProfiles>.")
    print("If any returned 'none', the account is on inline-shipping mode and the")
    print("error 37 has a different cause — investigate further.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
