"""Pull sheet for the 5 three-card lots — COLOR thumbnail + set + price +
checkbox per card, grouped by lot, so JC can visually find each exact card.

JC asked for color thumbnails (overrides the usual print-grayscale default)."""
import json, re
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

REPO = Path(__file__).parent
THUMBS = REPO / "output/lot_thumbs"
lots = json.loads((REPO / "output/_lot_plan.json").read_text())
OUT = REPO / "output/lot_pull_sheet.pdf"
PAGE_W, PAGE_H = letter
ML = 0.6 * inch
INK = HexColor("#000000"); MID = HexColor("#555555"); LINE = HexColor("#999999")
ROW = 0.46 * inch          # tightened so all 5 lots fit one page
THUMB_H = 0.40 * inch
BOTTOM = 0.35 * inch

c = canvas.Canvas(str(OUT), pagesize=letter)


def header():
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 17)
    c.drawString(ML, PAGE_H - 0.5*inch, "Lot Pull Sheet — 5 Lots / 15 Cards")
    c.setFillColor(MID); c.setFont("Helvetica", 9.5)
    c.drawString(ML, PAGE_H - 0.68*inch, "JC2 Cards · pull these, then CC posts the lots + delists the singles")


def short_set(title):
    t = re.sub(r"\b(Football|Insert)\b", "", title)
    return re.sub(r"\s+", " ", t).strip()[:46]


header()
y = PAGE_H - 0.92*inch

for l in lots:
    if y < BOTTOM + 1.1*inch:          # not enough room for a lot header + a row
        c.showPage(); header(); y = PAGE_H - 0.92*inch
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12.5)
    c.drawString(ML, y, f"LOT {l['rank']}: {l['theme']}  —  ${l['lot_price']:.2f}")
    y -= 5
    c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(ML, y, PAGE_W-ML, y)
    y -= ROW - 0.06*inch   # small header-to-row gap (not a full row)
    for card in l["cards"]:
        # checkbox
        c.setStrokeColor(INK); c.setLineWidth(1.1)
        c.rect(ML, y + 0.16*inch, 0.2*inch, 0.2*inch)
        # color thumbnail
        timg = THUMBS / f"{card['item_id']}.jpg"
        tx = ML + 0.36*inch
        if timg.is_file():
            try:
                img = ImageReader(str(timg))
                iw, ih = img.getSize()
                w = THUMB_H * (iw / ih)
                c.drawImage(img, tx, y + 0.02*inch, width=w, height=THUMB_H,
                            preserveAspectRatio=True, mask='auto')
            except Exception:
                w = 0.4*inch
        else:
            w = 0.4*inch
        # set name + price/id to the right of the thumb
        text_x = tx + 0.78*inch
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 13)
        c.drawString(text_x, y + 0.30*inch, short_set(card["title"]))
        c.setFillColor(MID); c.setFont("Helvetica", 10)
        c.drawString(text_x, y + 0.12*inch, f"${card['price']}  ·  item {card['item_id']}")
        y -= ROW
    y -= 0.04*inch

c.showPage(); c.save()
print(f"wrote {OUT}")
