"""Per-order fill sheet for the eBay Standard Envelope PIP claim form
(pip-claim.com). One block per order with every field pre-filled; you copy each
into the form and attach the two required screenshots.
"""
import json, shutil
from pathlib import Path

sheet = json.loads(Path("output/_refund_claim_sheet.json").read_text())
ese = sheet.get("ese", [])
usps = sheet.get("usps", [])

EBAY_ID = "harpua2001"
YOUR_NAME = "Jason Chletsos"
PAYPAL = "[YOUR PAYPAL EMAIL — confirm]"

def split_name(full):
    parts = (full or "").split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:]) or parts[0]

L = []
w = L.append
w("# eBay Standard Envelope Claim — Fill Sheet (pip-claim.com)")
w(f"\nFile ONE claim per order below. Fixed fields for every claim:")
w(f"- **Your eBay ID:** {EBAY_ID}")
w(f"- **Your Name:** {YOUR_NAME}")
w(f"- **Your PayPal Email:** {PAYPAL}")
w("\nEvery claim needs TWO uploads:")
w("  1. **eBay Order Details** screenshot — My eBay → Sold → the order → View order details.")
w("  2. **Buyer's Item-Not-Received / Arrived-Damaged message** — from Messages or the case.")
w("     (If a buyer never messaged you about it, that order likely can't be claimed here.)\n")
w("---\n")

total = 0.0
for i, r in enumerate(sorted(ese, key=lambda x: x["date"]), 1):
    total += r["amount"]
    fn, ln = split_name(r.get("recipient", ""))
    ctype = "Damage" if r.get("kind") == "damaged" else "Loss"
    w(f"## Claim {i} of {len(ese)}  —  ${r['amount']:.2f}  ({ctype})")
    w(f"- Tracking Number: **{r.get('tracking') or '(pull from order — none on file)'}**")
    w(f"- Claim Type: **{ctype}**")
    w(f"- Ship To Recipient First Name: **{fn}**")
    w(f"- Ship To Recipient Last Name: **{ln}**")
    w(f"- (ref) Order: {r['order_id']}  ·  Buyer: {r['buyer']}  ·  Item: {r['item'][:52]}")
    w(f"- (ref) Order page: https://www.ebay.com/sh/ord/details?orderid={r['order_id']}")
    w("")

w(f"**Total across {len(ese)} eSE claims: ${total:.2f}**\n")

if usps:
    w("---\n## Separate — USPS Ground Advantage (NOT this form)\n")
    for r in usps:
        fn, ln = split_name(r.get("recipient", ""))
        w(f"- {r['item'][:52]}  ·  ${r['amount']:.2f}  ·  tracking {r.get('tracking')}")
        w(f"  Recipient: {fn} {ln}  ·  Order {r['order_id']}")
        w(f"  File at usps.com/claims ($100 GA insurance) — OR try this PIP form if it accepts the tracking.")
        w("")

out = Path("output/refund_claim_forms.md")
out.write_text("\n".join(L))
try:
    dl = Path.home() / "Downloads" / "refund_claim_forms.md"
    shutil.copy(out, dl); print(f"Wrote {out}\nCopied to {dl}")
except Exception as e:
    print(f"Wrote {out} (Downloads copy failed: {e})")
print(f"\n{len(ese)} eSE claims, ${total:.2f}" + (f" + {len(usps)} USPS" if usps else ""))
