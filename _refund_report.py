"""_refund_report.py — count/list refunds issued, from the Sell Fulfillment API.

Enumerates orders (paginated) and pulls each order's paymentSummary.refunds[].
Prints a table of every refund with date, buyer, item, amount, status + totals.
"""
import json, sys
from pathlib import Path
import requests
from ebay_client import get_write_token

BASE = "https://api.ebay.com/sell/fulfillment/v1/order"

def main():
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
        "Content-Type": "application/json",
    }
    refunds = []
    offset, limit, total_orders = 0, 200, None
    while True:
        r = requests.get(BASE, headers=headers,
                         params={"limit": limit, "offset": offset}, timeout=40)
        if not r.ok:
            print(f"orders fetch failed ({r.status_code}): {r.text[:300]}")
            break
        d = r.json()
        total_orders = d.get("total", total_orders)
        orders = d.get("orders", []) or []
        for o in orders:
            ps = o.get("paymentSummary") or {}
            for ref in (ps.get("refunds") or []):
                amt = ref.get("amount", {})
                refunds.append({
                    "order_id":   o.get("orderId", ""),
                    "date":       (ref.get("refundDate") or o.get("creationDate", ""))[:10],
                    "buyer":      (o.get("buyer") or {}).get("username", ""),
                    "status":     ref.get("refundStatus", ""),
                    "amount":     float(amt.get("value", 0) or 0),
                    "currency":   amt.get("currency", "USD"),
                    "item":       "; ".join(
                        li.get("title", "")[:40]
                        for li in (o.get("lineItems") or [])) or o.get("orderId", ""),
                    "cancel":     (o.get("cancelStatus") or {}).get("cancelState", ""),
                })
        if not orders or (offset + limit) >= (total_orders or 0):
            break
        offset += limit

    refunds.sort(key=lambda x: x["date"])
    print(f"\n=== Refunds issued (from {total_orders} orders scanned) ===\n")
    if not refunds:
        print("  No refunds found on any order.")
    else:
        total = 0.0
        for i, f in enumerate(refunds, 1):
            total += f["amount"]
            print(f"  {i:2d}. {f['date']}  ${f['amount']:7.2f}  {f['status']:12s} "
                  f"{f['buyer']:16s} {f['item'][:44]}")
        print(f"\n  COUNT: {len(refunds)} refund(s)   TOTAL REFUNDED: ${total:.2f}")
    Path("output/_refund_report.json").write_text(json.dumps(refunds, indent=2))
    print("\n  Detail: output/_refund_report.json")

if __name__ == "__main__":
    sys.exit(main())
