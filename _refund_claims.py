"""_refund_claims.py — classify each issued refund into 'file a claim' vs
'no action (fee auto-credited)'.

Pulls refunds from Fulfillment orders, then enriches with the reason from the
Post-Order Return + Inquiry (item-not-received) APIs and the order's cancel
status + shipping service. eBay Standard Envelope covers trading cards up to
$20 for loss/damage — those are the claimable ones.
"""
import json, sys
from pathlib import Path
import requests
from ebay_client import get_write_token
from returns_agent import _post_order_get

FULFILL = "https://api.ebay.com/sell/fulfillment/v1/order"

def _orders_with_refunds(token):
    headers = {"Authorization": f"Bearer {token}",
               "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
               "Content-Type": "application/json"}
    out, offset, total = [], 0, None
    while True:
        r = requests.get(FULFILL, headers=headers,
                         params={"limit": 200, "offset": offset}, timeout=40)
        if not r.ok:
            print(f"  orders fetch failed {r.status_code}: {r.text[:200]}"); break
        d = r.json(); total = d.get("total", total)
        orders = d.get("orders", []) or []
        for o in orders:
            refs = ((o.get("paymentSummary") or {}).get("refunds") or [])
            if not refs:
                continue
            amt = sum(float((x.get("amount") or {}).get("value", 0) or 0) for x in refs)
            ship = ""
            for fsi in (o.get("fulfillmentStartInstructions") or []):
                ship = (((fsi.get("shippingStep") or {}).get("shippingServiceCode")) or ship)
            cancel = o.get("cancelStatus") or {}
            creq = cancel.get("cancelRequests") or []
            out.append({
                "order_id": o.get("orderId", ""),
                "date": (refs[0].get("refundDate") or o.get("creationDate", ""))[:10],
                "buyer": (o.get("buyer") or {}).get("username", ""),
                "amount": round(amt, 2),
                "item": "; ".join(li.get("title", "")[:44] for li in (o.get("lineItems") or [])),
                "ship": ship,
                "cancel_state": cancel.get("cancelState", ""),
                "cancel_reason": (creq[0].get("cancelReason") if creq else ""),
                "reason": "", "source": "",
            })
        if not orders or (offset + 200) >= (total or 0):
            break
        offset += 200
    return out, total

def _reasons_by_buyer(token):
    """Return {buyer_lower: (reason, kind)} from Return + Inquiry searches."""
    reasons = {}
    st, body = _post_order_get("/return/search", token, {"limit": 100})
    if body:
        for m in (body.get("members") or []):
            b = (m.get("buyerLoginName") or "").lower()
            rsn = ((m.get("creationInfo") or {}).get("reason")
                   or m.get("returnType") or "RETURN")
            if b:
                reasons[b] = (rsn, "return")
    st2, body2 = _post_order_get("/inquiry/search", token, {"limit": 100})
    if body2:
        for m in (body2.get("members") or []):
            b = (m.get("buyerLoginName") or "").lower()
            if b and b not in reasons:
                reasons[b] = ("ITEM_NOT_RECEIVED", "inquiry")
    return reasons

def _classify(r):
    rsn = (r.get("reason") or "").upper()
    if rsn in ("ITEM_NOT_RECEIVED", "ARRIVED_DAMAGED") or r.get("source") == "inquiry":
        return "CLAIM", ("Lost/damaged in transit — request eBay Standard Envelope "
                          "reimbursement (cards covered to $20)"
                          if "eBayStandardEnvelope" in (r.get("ship") or "")
                          else "Lost/damaged in transit — file carrier/eBay claim")
    if r.get("cancel_state") in ("CANCELED", "CANCELLED") or r.get("cancel_reason"):
        return "NO_ACTION", "Cancellation — final value fee auto-credited"
    if rsn in ("NOT_AS_DESCRIBED", "DEFECTIVE_ITEM"):
        return "REVIEW", ("Not-as-described: FVF auto-credited. Claim ONLY if it was "
                          "actually damaged in transit (then eSE reimbursement)")
    return "REVIEW", "Direct refund — confirm reason; if never delivered, eSE loss claim"

def main():
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    refunds, total = _orders_with_refunds(token)
    reasons = _reasons_by_buyer(token)
    for r in refunds:
        rr = reasons.get((r["buyer"] or "").lower())
        if rr:
            r["reason"], r["source"] = rr[0], rr[1]
    for r in refunds:
        r["verdict"], r["note"] = _classify(r)

    buckets = {"CLAIM": [], "REVIEW": [], "NO_ACTION": []}
    for r in refunds:
        buckets[r["verdict"]].append(r)

    print(f"\n=== {len(refunds)} refunds across {total} orders "
          f"(${sum(r['amount'] for r in refunds):.2f} total) ===")
    for tag, title in (("CLAIM", ">>> FILE CLAIMS FOR"),
                       ("REVIEW", ">>> REVIEW (maybe claimable)"),
                       ("NO_ACTION", ">>> NO ACTION (fee auto-credited)")):
        rows = sorted(buckets[tag], key=lambda x: x["date"])
        print(f"\n{title}  —  {len(rows)} refund(s), ${sum(r['amount'] for r in rows):.2f}")
        for r in rows:
            print(f"  {r['date']}  ${r['amount']:6.2f}  {r['buyer']:16s} "
                  f"[{r['reason'] or r['cancel_reason'] or 'unknown'}] {r['item'][:40]}")
            print(f"        ↳ {r['note']}  (ship: {r['ship'] or 'n/a'})")
    Path("output/_refund_claims.json").write_text(json.dumps(refunds, indent=2))
    print("\n  Detail: output/_refund_claims.json")

if __name__ == "__main__":
    sys.exit(main())
