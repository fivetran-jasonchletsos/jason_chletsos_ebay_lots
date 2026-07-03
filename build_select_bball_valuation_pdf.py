"""build_select_bball_valuation_pdf.py — valuation + post/hold overview for the
2024-25 Panini Select Basketball scans (Scan 137 + 138). One page per scan, a
3x3 grid of card thumbnails with player, parallel, raw value range, suggested
list price, and a verdict badge. Writes output/select_bball_valuation.pdf and
copies to ~/Downloads.
"""
from pathlib import Path
import shutil

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak, Image, Flowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# verdict -> badge color
BADGE = {
    "POST SOLO": colors.HexColor("#1b7a3d"),
    "MAYBE SOLO": colors.HexColor("#b8860b"),
    "LOT": colors.HexColor("#6b6b6b"),
}

PAGES = [
    {
        "dir": "output/scan137_cards",
        "title": "2024-25 SELECT BASKETBALL — Parallels & Inserts",
        "cards": [
            ("card_01.jpg", "Victor Wembanyama", "Concourse Orange Flash #9", "$15-25", "19.99", "POST SOLO"),
            ("card_02.jpg", "Keyonte George", "Orange Flash", "$1-3", "2.99", "LOT"),
            ("card_03.jpg", "Jayson Tatum", "Neon Icons insert", "$2-5", "4.99", "MAYBE SOLO"),
            ("card_04.jpg", "Tristan da Silva", "Orange Flash RC", "$1-3", "2.99", "LOT"),
            ("card_05.jpg", "DeMar DeRozan", "Green parallel", "$1-3", "2.99", "LOT"),
            ("card_06.jpg", "Nikola Jokic", "Neon Icons insert", "$2-5", "4.99", "MAYBE SOLO"),
            ("card_07.jpg", "Chet Holmgren", "Orange Flash", "$1-3", "2.99", "LOT"),
            ("card_08.jpg", "Stephon Castle", "Concourse base RC", "$2-7", "4.99", "LOT"),
            ("card_09.jpg", "Ja Morant", "Select Certified insert", "$1-3", "2.99", "LOT"),
        ],
    },
    {
        "dir": "output/scan138_cards",
        "title": "2024-25 SELECT BASKETBALL — Concourse Blue (Retail)",
        "cards": [
            ("card_01.jpg", "Kawhi Leonard", "Concourse Blue", "$1-4", "3.99", "LOT"),
            ("card_02.jpg", "Draymond Green", "Concourse Blue", "$1-2", "1.99", "LOT"),
            ("card_03.jpg", "Anthony Davis", "Concourse Blue", "$1-3", "2.99", "LOT"),
            ("card_04.jpg", "Stephen Curry", "Concourse Blue", "$2-5", "4.99", "MAYBE SOLO"),
            ("card_05.jpg", "Bam Adebayo", "Concourse Blue", "$1-3", "2.49", "LOT"),
            ("card_06.jpg", "Zion Williamson", "Concourse Blue", "$1-3", "2.99", "LOT"),
            ("card_07.jpg", "Shai Gilgeous-Alexander", "Concourse Blue", "$1.50-4", "3.99", "MAYBE SOLO"),
            ("card_08.jpg", "Devin Booker", "Concourse Blue", "$1.50-3", "2.99", "LOT"),
            ("card_09.jpg", "Tyrese Haliburton", "Concourse Blue", "$1-3", "2.99", "LOT"),
        ],
    },
]

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=18, leading=22,
                    textColor=colors.HexColor("#0b2545"), spaceAfter=2, alignment=0)
summary = ParagraphStyle("summary", parent=styles["Normal"], fontSize=10.5,
                         leading=14, textColor=colors.HexColor("#333"), spaceAfter=10)
pname = ParagraphStyle("pname", parent=styles["Normal"], fontSize=9.5, leading=11,
                       alignment=1, textColor=colors.HexColor("#111"))
ppar = ParagraphStyle("ppar", parent=styles["Normal"], fontSize=7.5, leading=9,
                      alignment=1, textColor=colors.HexColor("#666"))
pval = ParagraphStyle("pval", parent=styles["Normal"], fontSize=9, leading=11,
                      alignment=1, textColor=colors.HexColor("#0b2545"))


class Badge(Flowable):
    def __init__(self, text, color, w=1.35 * inch, h=0.2 * inch):
        super().__init__()
        self.text, self.color, self.width, self.height = text, color, w, h

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.roundRect(0, 0, self.width, self.height, 4, stroke=0, fill=1)
        self.canv.setFillColor(colors.white)
        self.canv.setFont("Helvetica-Bold", 8)
        self.canv.drawCentredString(self.width / 2, self.height / 2 - 3, self.text)


def cell(d, c):
    fn, player, par, vrange, price, verdict = c
    col = []
    p = Path(d) / fn
    if p.exists():
        img = Image(str(p))
        img.drawWidth = 1.12 * inch
        img.drawHeight = 1.12 * inch * (img.imageHeight / img.imageWidth)
        if img.drawHeight > 1.45 * inch:
            img.drawHeight = 1.45 * inch
            img.drawWidth = 1.45 * inch * (img.imageWidth / img.imageHeight)
        img.hAlign = "CENTER"
        col.append(img)
    col += [Spacer(1, 3), Paragraph(f"<b>{player}</b>", pname), Paragraph(par, ppar),
            Spacer(1, 2), Paragraph(f"{vrange} &nbsp;·&nbsp; list ${price}", pval),
            Spacer(1, 3), Badge(verdict, BADGE[verdict])]
    return col


def page(P):
    el = [Paragraph(P["title"], h1)]
    cards = P["cards"]
    rows = [cards[i:i + 3] for i in range(0, 9, 3)]
    grid = [[cell(P["dir"], c) for c in row] for row in rows]
    t = Table(grid, colWidths=[2.4 * inch] * 3, rowHeights=[2.5 * inch] * 3)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    el.append(t)
    return el


def main():
    out = Path("output/select_bball_valuation.pdf")
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.55 * inch, bottomMargin=0.5 * inch,
                            leftMargin=0.45 * inch, rightMargin=0.45 * inch,
                            title="Select Basketball Valuation")
    flow = [
        Paragraph("2024-25 Panini Select Basketball — Valuation & Post Plan", h1),
        Paragraph(
            "18 raw cards, two scans. <b>Bottom line:</b> only the Victor Wembanyama Orange Flash "
            "(~$20) is a clear solo listing. Everything else is $1-5 raw — Blue Retail base, "
            "common parallels and base inserts. Best play: post Wemby solo, maybe solo the top "
            "names (Curry, SGA, Tatum &amp; Jokic Neon Icons), and bundle the rest into one or two "
            "'2024-25 Select Basketball' lots rather than 16 slow $2-3 singles. "
            "Green = post solo · Amber = borderline (solo or lot) · Gray = lot it.",
            summary),
        Spacer(1, 4),
    ]
    flow += page(PAGES[0])
    flow.append(PageBreak())
    flow += page(PAGES[1])
    doc.build(flow)
    dl = Path.home() / "Downloads" / "select_bball_valuation.pdf"
    shutil.copy(out, dl)
    print(f"Wrote {out}")
    print(f"Copied to {dl}")


if __name__ == "__main__":
    main()
