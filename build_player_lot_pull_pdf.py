"""build_player_lot_pull_pdf.py — one-page-per-player VISUAL pull sheet for the
Josh Allen / Mahomes / Cam Ward / Jeanty lot consolidation. Each page shows the
5 cards to pull as thumbnails (downloaded from each live listing's eBay photo)
with a check box, item id and price, plus the keep-solo cards to leave listed.
Writes output/player_lot_pull.pdf and copies to ~/Downloads.
"""
import json
from pathlib import Path
import shutil

import requests
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak, Flowable, Image)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

THUMBS = Path("output/_lot_thumbs")
THUMBS.mkdir(parents=True, exist_ok=True)

LOTS = [
    {
        "player": "JOSH ALLEN",
        "sub": "Buffalo Bills  ·  5-card lot  ·  list at $12.99",
        "cards": [
            ("Select Red/Yellow Shock #12", "307021784343", "2.99"),
            ("Select Die-Cut #34", "306993554472", "2.33"),
            ("Select Numbers Insert #17", "306993495460", "2.33"),
            ("Select Turbocharged Insert", "306993495546", "2.33"),
            ("Panini Mosaic Base #17", "306993495361", "2.33"),
        ],
        "solo": "Topps Chrome /150 ($14.99) · Prizm Fractal ($8.99) · Paramount Pairings ($6.99)",
    },
    {
        "player": "PATRICK MAHOMES",
        "sub": "Kansas City Chiefs  ·  5-card lot  ·  list at $16.99",
        "cards": [
            ("2025 Prizm Prizm Break", "307029578211", "3.99"),
            ("Select Numbers Game #15", "307021770408", "4.99"),
            ("2024 Phoenix Thunderbirds", "307021765688", "4.99"),
            ("2025 Mosaic Base", "307021785258", "2.99"),
            ("2023 Contenders #51", "306992916873", "2.99"),
        ],
        "solo": "Select Premier Level Red/Blue Shock ($10.13) · Select Numbers ($8.99) · Select Tie-Dye Prizm ($6.99)",
    },
    {
        "player": "CAM WARD  (Rookie)",
        "sub": "Tennessee Titans  ·  5-card lot, all RC  ·  list at $18.99",
        "cards": [
            ("Prizm Fireworks RC", "307029578174", "3.99"),
            ("Prizm Fractal Green RC", "307029578293", "4.99"),
            ("Prizm Emergent Green RC", "307029578357", "4.99"),
            ("Select Numbers Game #1 RC", "307021759801", "4.99"),
            ("Select Certified RC", "307021780639", "4.99"),
        ],
        "solo": "Select Field Level #426 ($6.99-7.00, two of them) · Phoenix #194 ($6.23)",
    },
    {
        "player": "ASHTON JEANTY  (Rookie)",
        "sub": "Las Vegas Raiders  ·  5-card lot, all RC  ·  list at $12.99",
        "cards": [
            ("Select Turbocharged RC", "306993605582", "2.33"),
            ("Select RC base", "306993602623", "2.33"),
            ("Donruss Rated Rookie #305", "306998478666", "1.99"),
            ("Optic Hidden Potential #5", "307021794277", "1.99"),
            ("Mosaic Rookies Silver RC", "307021799481", "1.99"),
        ],
        "solo": "Both Revolution RCs ($14.99 ea) · Green Prizm Concourse ($14.99) · Class Action ($11.00) · "
                "Green Shock Prizm ($9.99) · Select Future ($8.99) · Torchbearer ($7.79) · Donruss Retro ($7.99)",
    },
]


def pic_map():
    d = json.load(open("output/listings_snapshot.json"))
    L = d.get("listings", d) if isinstance(d, dict) else d
    return {str(x.get("item_id")): x.get("pic") for x in L}


def fetch_thumb(item_id, url):
    dest = THUMBS / f"{item_id}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        if r.ok and r.content:
            dest.write_bytes(r.content)
            return dest
    except Exception:
        return None
    return None


styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=28, leading=32,
                    textColor=colors.HexColor("#0b2545"), spaceAfter=2)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=13, leading=16,
                     textColor=colors.HexColor("#444"), spaceAfter=18)
cap = ParagraphStyle("cap", parent=styles["Normal"], fontSize=8.5, leading=10.5,
                     alignment=1, textColor=colors.HexColor("#111"))
meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=7.5, leading=9,
                      alignment=1, textColor=colors.HexColor("#777"))
solo_lbl = ParagraphStyle("solo_lbl", parent=styles["Normal"], fontSize=11,
                          leading=15, textColor=colors.HexColor("#7a1f1f"))
foot = ParagraphStyle("foot", parent=styles["Normal"], fontSize=9.5, leading=13,
                      textColor=colors.HexColor("#666"))


class CheckBox(Flowable):
    def __init__(self, size=13):
        super().__init__()
        self.width = self.height = size

    def draw(self):
        self.canv.setLineWidth(1.2)
        self.canv.setStrokeColor(colors.HexColor("#0b2545"))
        self.canv.roundRect(0, 0, self.width, self.height, 2, stroke=1, fill=0)


def card_cell(name, iid, price, thumb):
    col = []
    if thumb:
        img = Image(str(thumb))
        img.drawWidth = 1.18 * inch
        img.drawHeight = 1.18 * inch * (img.imageHeight / img.imageWidth)
        if img.drawHeight > 1.65 * inch:
            img.drawHeight = 1.65 * inch
            img.drawWidth = 1.65 * inch * (img.imageWidth / img.imageHeight)
        img.hAlign = "CENTER"
        col.append(img)
    else:
        col.append(Paragraph("(no image)", meta))
    col += [Spacer(1, 3), CheckBox(), Spacer(1, 2),
            Paragraph(name, cap), Paragraph(f"{iid}<br/>${price}", meta)]
    return col


def page(lot, pics):
    el = [Paragraph(lot["player"], h1), Paragraph(lot["sub"], sub)]
    cells = []
    for name, iid, price in lot["cards"]:
        thumb = fetch_thumb(iid, pics.get(iid))
        cells.append(card_cell(name, iid, price, thumb))
    t = Table([cells], colWidths=[1.4 * inch] * 5)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    el += [t, Spacer(1, 0.5 * inch),
           Paragraph("KEEP LISTED SOLO — do not pull:", solo_lbl),
           Paragraph(lot["solo"], foot)]
    return el


def main():
    pics = pic_map()
    out = Path("output/player_lot_pull.pdf")
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                            title="Player Lot Pull Sheet")
    flow = []
    for i, lot in enumerate(LOTS):
        flow += page(lot, pics)
        if i < len(LOTS) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    dl = Path.home() / "Downloads" / "player_lot_pull.pdf"
    shutil.copy(out, dl)
    print(f"Wrote {out}")
    print(f"Copied to {dl}")


if __name__ == "__main__":
    main()
