"""Build a per-order eBay Standard Envelope claim packet from the claim sheet.
Writes output/refund_claim_packet.md (+ copies to ~/Downloads) with every field
the claim form asks for, the direct order/tracking links, and exactly which
screenshots to attach (which I can't capture — they're behind the eBay login).
"""
import json, shutil
from pathlib import Path

data = json.loads(Path("output/_refund_claim_sheet.json").read_text())
ese, usps = data.get("ese", []), data.get("usps", [])

def order_link(oid):
    return f"https://www.ebay.com/sh/ord/details?orderid={oid}"

lines = []
w = lines.append
w("# eBay Standard Envelope — Reimbursement Claim Packet")
w("_Seller: harpua2001. Each buyer was already refunded in full; requesting eSE "
  "shipping-protection reimbursement (trading cards covered up to $20)._\n")

total = 0.0
for i, r in enumerate(sorted(ese, key=lambda x: x["date"]), 1):
    total += r["amount"]
    w(f"## Claim {i} — {r['buyer']}  (${r['amount']:.2f})")
    w("")
    w(f"- **Order number:** {r['order_id']}")
    w(f"- **Item:** {r['item']}")
    w(f"- **Buyer:** {r['buyer']}")
    w(f"- **Refund amount (your loss):** ${r['amount']:.2f}")
    w(f"- **Refund date:** {r['date']}")
    w(f"- **Shipping service:** eBay Standard Envelope")
    w(f"- **Tracking number:** {r.get('tracking') or '(none on file — eBay can pull from the order)'}")
    w(f"- **Issue:** {'Arrived damaged' if r.get('kind')=='damaged' else 'Lost in transit / not delivered'}")
    w(f"- **Order page:** {order_link(r['order_id'])}")
    w("")
    w("  **Screenshots to attach:**")
    w(f"  1. Open the order page above → screenshot the **tracking status** "
      f"showing the last scan / not delivered"
      + (" (or the buyer's damage photo/message)." if r.get('kind')=='damaged' else "."))
    w("  2. On the same page, screenshot the **Refund issued** line (amount + date).")
    w("")

w(f"**TOTAL eSE requested: ${total:.2f} across {len(ese)} orders**\n")

if usps:
    w("---\n# USPS claim (separate — file at usps.com/claims)\n")
    for r in usps:
        w(f"- **Order:** {r['order_id']}  ·  **Item:** {r['item']}")
        w(f"- **Tracking:** {r.get('tracking')}  (USPS Ground Advantage — $100 included insurance)")
        w(f"- **Value / refund:** ${r['amount']:.2f}  ·  **Issue:** lost in transit")
        w(f"- **File at:** https://www.usps.com/help/claims.htm  "
          f"(need: tracking, proof of value = the eBay sale record, proof of refund)")
        w("")

out = Path("output/refund_claim_packet.md")
out.write_text("\n".join(lines))
try:
    dl = Path.home() / "Downloads" / "refund_claim_packet.md"
    shutil.copy(out, dl)
    print(f"Wrote {out}\nCopied to {dl}")
except Exception as e:
    print(f"Wrote {out} (Downloads copy failed: {e})")
print(f"\n{len(ese)} eSE claims totaling ${total:.2f}"
      + (f" + {len(usps)} USPS claim" if usps else ""))
