"""Final claim sheet: apply JC's call (all lost in transit except Luther Burden /
dusjoh1986), fetch tracking for each claimable order, group by claim type.
"""
import json, sys
from pathlib import Path
import requests
from ebay_client import get_write_token

FULFILL = "https://api.ebay.com/sell/fulfillment/v1/order"
NOT_LOST = {"dusjoh1986"}   # Luther Burden — not-as-described, not a transit claim

def tracking_for(order_id, headers):
    try:
        r = requests.get(f"{FULFILL}/{order_id}/shipping_fulfillment",
                         headers=headers, timeout=30)
        if not r.ok:
            return ""
        fs = r.json().get("fulfillments", []) or []
        return "; ".join(f.get("shipmentTrackingNumber", "") for f in fs if f.get("shipmentTrackingNumber"))
    except Exception:
        return ""

def main():
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    headers = {"Authorization": f"Bearer {token}",
               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US", "Content-Type": "application/json"}
    refunds = json.loads(Path("output/_refund_claims.json").read_text())

    ese, usps, skip = [], [], []
    for r in refunds:
        v = r["verdict"]; buyer = (r["buyer"] or "")
        # claimable = already-CLAIM (damaged) OR review-and-lost (not the Burden NAS)
        claimable = (v == "CLAIM") or (v == "REVIEW" and buyer not in NOT_LOST)
        if not claimable:
            skip.append(r); continue
        r["tracking"] = tracking_for(r["order_id"], headers)
        r["kind"] = "damaged" if (r.get("reason","").upper()=="ARRIVED_DAMAGED") else "lost"
        if "eBayStandardEnvelope" in (r.get("ship") or ""):
            ese.append(r)
        else:
            usps.append(r)

    def line(r):
        return (f"  {r['date']}  ${r['amount']:6.2f}  {r['kind']:7s} {r['buyer']:18s}\n"
                f"        order {r['order_id']}   tracking {r.get('tracking') or 'n/a'}\n"
                f"        {r['item'][:60]}")

    et = sum(r["amount"] for r in ese); ut = sum(r["amount"] for r in usps)
    print("\n================  CLAIM SHEET  ================\n")
    print(f"A) eBay Standard Envelope reimbursements — {len(ese)} claims, ${et:.2f}")
    print("   (cards covered up to $20 each; all yours are under that)\n")
    for r in sorted(ese, key=lambda x: x["date"]):
        print(line(r))
    print(f"\nB) USPS claims (shipped USPS, not eSE) — {len(usps)} claim(s), ${ut:.2f}")
    print("   (recoverable only if the label carried insurance / Ground Advantage $100 default)\n")
    for r in sorted(usps, key=lambda x: x["date"]):
        print(line(r))
    print(f"\nNOT CLAIMED: {len(skip)} (Burden not-as-described + 3 cancellations — fees auto-credited)")
    print(f"\nTOTAL CLAIMABLE: {len(ese)+len(usps)} refunds, ${et+ut:.2f}")

    Path("output/_refund_claim_sheet.json").write_text(
        json.dumps({"ese": ese, "usps": usps, "skipped": [s['buyer'] for s in skip]}, indent=2))
    print("Saved: output/_refund_claim_sheet.json")

if __name__ == "__main__":
    sys.exit(main())
