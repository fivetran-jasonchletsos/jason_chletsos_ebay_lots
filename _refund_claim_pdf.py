"""Render the eBay Standard Envelope claim packet to a printable PDF
(+ copy to ~/Downloads). Leads with a 'what I need to do myself' checklist,
then the fixed fields, then one fill-block per order.
"""
import json, shutil
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
Image.MAX_IMAGE_PIXELS = None

sheet = json.loads(Path("output/_refund_claim_sheet.json").read_text())
ese = sorted(sheet.get("ese", []), key=lambda x: x["date"])
usps = sheet.get("usps", [])

def font(sz, bold=False):
    for p in (("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else
               "/System/Library/Fonts/Supplemental/Arial.ttf"),
              "/System/Library/Fonts/Helvetica.ttc"):
        if Path(p).exists():
            try: return ImageFont.truetype(p, sz)
            except Exception: pass
    return ImageFont.load_default()

F   = font(23); FB = font(23, True); H1 = font(34, True); H2 = font(27, True); SM = font(20)
PW, PH, M = 1275, 1650, 70
GOLD=(150,110,20); INK=(20,20,20); GREY=(90,90,90); RED=(170,40,40)

pages=[]; page=None; d=None; y=0
def new_page():
    global page,d,y
    page=Image.new("RGB",(PW,PH),"white"); d=ImageDraw.Draw(page); y=M; pages.append(page)
def space(n):
    global y; y+=n
def need(h):
    if y+h > PH-M: new_page()
def wrap(text, fnt, maxw):
    words=text.split(); lines=[]; cur=""
    for w in words:
        t=(cur+" "+w).strip()
        if d.textlength(t,font=fnt)<=maxw: cur=t
        else: lines.append(cur); cur=w
    if cur: lines.append(cur)
    return lines or [""]
def line(text, fnt=F, color=INK, indent=0, gap=8):
    global y
    for ln in wrap(text, fnt, PW-2*M-indent):
        need(fnt.size+gap); d.text((M+indent,y),ln,font=fnt,fill=color); y+=fnt.size+gap
def rule():
    global y; need(20); d.line([(M,y),(PW-M,y)],fill=(210,210,210),width=2); y+=18

new_page()
d.text((M,y),"eBay Standard Envelope — Claim Packet",font=H1,fill=GOLD); y+=H1.size+6
line("Seller: harpua2001 (Jason Chletsos)   -   9 claims, $73.78   -   file at pip-claim.com", SM, GREY)
space(14); rule()

line("THINGS I NEED TO DO MYSELF", H2, INK); space(6)
todo = [
 "Have my PayPal email ready — the reimbursement gets paid there.",
 "For EACH order: screenshot the eBay Order Details (My eBay > Sold > the order > View order details).",
 "For EACH order: screenshot the buyer's 'didn't arrive' / 'arrived damaged' message (Messages or the case).",
 "   Only #8 (Greg Hilliard) has a formal case on file. For the 8 Loss claims I need a real buyer message —",
 "   if a buyer never messaged me about it, skip that one (the form warns against fraudulent claims).",
 "Claim #7 (dean ebisuya): find the eSE tracking on the order page — the form requires a tracking number.",
 "File each claim at pip-claim.com (one submission per order) and attach the 2 screenshots.",
 "Eevee PSA 9 ($17.70): file SEPARATELY at usps.com/claims (USPS Ground Advantage, $100 insurance).",
]
for t in todo:
    if t.startswith("   "): line(t.strip(), SM, GREY, indent=54)
    else: line("[  ] "+t, F, INK, indent=6)
space(10); rule()

line("FIXED FIELDS (same on every claim)", H2, INK); space(4)
line("Your eBay ID:  harpua2001", FB)
line("Your Name:  Jason Chletsos", FB)
line("Your PayPal Email:  ______________________________  (fill in)", FB, RED)
space(8); rule()

def split_name(f):
    p=(f or "").split(); return (p[0], " ".join(p[1:]) or (p[0] if p else "")) if p else ("","")

line("PER-ORDER FILL BLOCKS", H2, INK); space(6)
for i,r in enumerate(ese,1):
    fn,ln=split_name(r.get("recipient",""))
    ctype="Damage" if r.get("kind")=="damaged" else "Loss"
    need(230)
    d.rectangle([M,y,PW-M,y+3],fill=GOLD); y+=14
    line(f"Claim {i} of 9    ${r['amount']:.2f}    ({ctype})", FB, GOLD)
    line(f"Tracking Number:  {r.get('tracking') or '(none on file — pull from order page)'}",
         FB, (RED if not r.get('tracking') else INK))
    line(f"Claim Type:  {ctype}", F)
    line(f"Recipient First Name:  {fn}", F)
    line(f"Recipient Last Name:  {ln}", F)
    line(f"ref: order {r['order_id']} · buyer {r['buyer']} · {r['item'][:46]}", SM, GREY)
    line(f"order page: ebay.com/sh/ord/details?orderid={r['order_id']}", SM, GREY)
    space(12)

if usps:
    rule(); line("SEPARATE — USPS claim (NOT the eBay form)", H2, INK); space(4)
    for r in usps:
        fn,ln=split_name(r.get("recipient",""))
        line(f"{r['item'][:52]}   ${r['amount']:.2f}", FB)
        line(f"Tracking: {r.get('tracking')}   Recipient: {fn} {ln}   Order: {r['order_id']}", SM, GREY)
        line("File at usps.com/claims — need tracking, proof of value (sale record), proof of refund.", SM, GREY)

out=Path("output/refund_claim_packet.pdf")
pages[0].save(out,"PDF",save_all=True,append_images=pages[1:],resolution=150)
try:
    dl=Path.home()/"Downloads"/"refund_claim_packet.pdf"; shutil.copy(out,dl)
    print(f"Wrote {out} ({len(pages)} pages)\nCopied to {dl}")
except Exception as e:
    print(f"Wrote {out} (Downloads copy failed: {e})")
