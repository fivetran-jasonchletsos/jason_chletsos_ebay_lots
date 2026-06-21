"""One-page pull sheet for the 5 three-card lots. Grouped by lot, each card
shows player (big) + set + price + checkbox so JC can find the exact card."""
import json, re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

REPO = Path(__file__).parent
lots = json.loads((REPO / "output/_lot_plan.json").read_text())
OUT = REPO / "output/lot_pull_sheet.pdf"
PAGE_W, PAGE_H = letter
ML = 0.6 * inch
INK = HexColor("#000000"); MID = HexColor("#555555"); LINE = HexColor("#999999")

c = canvas.Canvas(str(OUT), pagesize=letter)
c.setFillColor(INK); c.setFont("Helvetica-Bold", 17)
c.drawString(ML, PAGE_H - 0.55*inch, "Lot Pull Sheet — 5 Lots / 15 Cards")
c.setFillColor(MID); c.setFont("Helvetica", 9.5)
c.drawString(ML, PAGE_H - 0.74*inch, "JC2 Cards · pull these, then CC posts the lots + delists the singles")

y = PAGE_H - 1.05*inch
def short_set(title):
    # strip leading year+brand-ish into a compact set label
    t = re.sub(r"\b(Football|RC|Insert)\b", "", title)
    return re.sub(r"\s+", " ", t).strip()[:52]

for l in lots:
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 13)
    c.drawString(ML, y, f"LOT {l['rank']}: {l['theme']}  —  ${l['lot_price']:.2f}")
    y -= 4
    c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(ML, y, PAGE_W-ML, y)
    y -= 22
    for card in l["cards"]:
        # checkbox
        c.setStrokeColor(INK); c.setLineWidth(1.1)
        c.rect(ML, y-5, 0.20*inch, 0.20*inch)
        # player big
        title = card["title"]
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 15)
        c.drawString(ML + 0.34*inch, y, short_set(title))
        # price right
        c.setFillColor(MID); c.setFont("Helvetica", 10)
        c.drawRightString(PAGE_W-ML, y, f"${card['price']}  ·  {card['item_id']}")
        y -= 26
    y -= 12

c.showPage(); c.save()
print(f"wrote {OUT}")
