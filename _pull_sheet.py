"""Pull sheet for the 9 leftover cards that still need listing (scans 250/251).
Shows the card images grouped as 4 singles + 1 five-card lot, so JC can gather
the physical cards before we post. Output -> output/pull_sheet.pdf, ~/Downloads,
and docs/."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

CROP = Path("output/split_cards")
OUT = Path("output/pull_sheet.pdf")
styles = getSampleStyleSheet()
H = ParagraphStyle("H", parent=styles["Heading1"], fontSize=18, spaceAfter=3, textColor=HexColor("#111111"))
SUB = ParagraphStyle("SUB", parent=styles["Normal"], fontSize=10, textColor=HexColor("#666666"), spaceAfter=14)
H2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=8, textColor=HexColor("#1a3d6d"))
CAP = ParagraphStyle("CAP", parent=styles["Normal"], fontSize=8.5, leading=10.5, alignment=1)
PRICE = ParagraphStyle("PRICE", parent=styles["Normal"], fontSize=9.5, leading=11, alignment=1, textColor=HexColor("#137333"))

def crop(scan, idx): return str(CROP / f"Scan {scan}" / f"Scan {scan}_{idx:02d}.jpg")

# (scan, idx, player, parallel, suggested price)
SINGLES = [
    (250, 3, "Arch Manning",  "Prizm Draft Instant Impact", "$12.99"),
    (250, 2, "Cole Kmet",     "Optic (Blue Stars)",         "$2.99"),
    (250, 4, "Tez Johnson",   "Optic Rated Rookie RC",      "$3.99"),
    (250, 8, "Jalen Milroe",  "Prizm Draft Fearless RC",    "$4.99"),
]
LOT = [
    (251, 3, "Ryan Wingo",    "Red Cracked Ice"),
    (251, 5, "Riley Leonard", "New Recruits Green"),
    (251, 6, "Zy Alexander",  "Purple Wave"),
    (251, 7, "Xavier Watts",  "Green"),
    (251, 8, "T.J. Sanders",  "Red Cracked Ice"),
]
LOT_PRICE = "$9.99"

IW, IH = 1.15*inch, 1.58*inch
def cell(scan, idx, name, par, price=None):
    parts = [RLImage(crop(scan, idx), width=IW, height=IH),
             Paragraph(f"<b>{name}</b><br/>{par}", CAP)]
    if price: parts.append(Paragraph(price, PRICE))
    return parts

story = []
story.append(Paragraph("Pull sheet — 9 leftover cards to list", H))
story.append(Paragraph("harpua2001 &bull; 2026-07-05 &bull; gather these, then tell me to post. Nothing is live yet.", SUB))

# Singles
story.append(Paragraph("SINGLES (4)", H2))
row_imgs, row_caps, row_prices = [], [], []
for s in SINGLES:
    c = cell(*s)
    row_imgs.append(c[0]); row_caps.append(c[1]); row_prices.append(c[2])
t1 = Table([row_imgs, row_caps, row_prices], colWidths=[1.6*inch]*4)
t1.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
story.append(t1)

# Lot
story.append(Spacer(1, 10))
story.append(Paragraph(f"5-CARD LOT — “Prizm Draft Rookies” &nbsp; (suggested {LOT_PRICE})", H2))
row_imgs, row_caps = [], []
for l in LOT:
    c = cell(*l)
    row_imgs.append(c[0]); row_caps.append(c[1])
t2 = Table([row_imgs, row_caps], colWidths=[1.28*inch]*5)
t2.setStyle(TableStyle([("ALIGN",(0,0),(-1,-1),"CENTER"),("VALIGN",(0,0),(-1,-1),"TOP"),
                        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3),
                        ("BOX",(0,0),(-1,-1),1,HexColor("#137333")),("BACKGROUND",(0,0),(-1,-1),HexColor("#f2faf4"))]))
story.append(t2)

story.append(Spacer(1, 16))
note = ParagraphStyle("N", parent=styles["Normal"], fontSize=9.5, leading=13, textColor=HexColor("#444"))
story.append(Paragraph("These were missed earlier because I mistakenly treated the Prizm Draft rookies, the "
  "Cole Kmet Optic, and the Arch Manning as bad auto-ID. They're real. Once you've pulled them, say the word "
  "and I'll post the 4 singles + the lot (prices adjustable).", note))

doc = SimpleDocTemplate(str(OUT), pagesize=letter, topMargin=0.6*inch, bottomMargin=0.5*inch,
                        leftMargin=0.6*inch, rightMargin=0.6*inch)
doc.build(story)
for dest in (Path.home()/"Downloads"/"pull_sheet.pdf", Path("docs/pull_sheet.pdf")):
    shutil.copy(OUT, dest)
print("wrote", OUT, "+ ~/Downloads + docs/")
