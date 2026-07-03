"""build_keep_remove_pdf.py — visual keep/remove sort sheet for the 6 review
scans (review_21..review_26). KEEP = post solo (green badge + price), REMOVE =
lot/skip (gray badge). One card per cell with its thumbnail. Writes
output/keep_remove_sheet.pdf and copies to ~/Downloads.
"""
from pathlib import Path
import shutil

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak, Image, Flowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

R = "output"

# (image, name, price)  — KEEP = post solo
KEEP = [
    ("review_25/card_07.jpg", "Jeremiah Smith Prizm NIL", "$24.99"),
    ("review_25/card_04.jpg", "Eddie George NIL", "$5.99"),
    ("review_21/card_06.jpg", "Quinshon Judkins NIL", "$5.99"),
    ("review_24/card_08.jpg", "James Cook Prizm Premier Pink relic", "$5.99"),
    ("review_25/card_03.jpg", "Cris Carter NIL", "$4.99"),
    ("review_24/card_05.jpg", "Terry McLaurin Prizm Pink", "$4.99"),
    ("review_22/card_06.jpg", "Ricky Pearsall Optic Green RR", "$3.99"),
    ("review_24/card_06.jpg", "Geno Smith Prizm Pink", "$3.99"),
    ("review_24/card_02.jpg", "Chuba Hubbard Prizm Global Reach", "$3.99"),
    ("review_25/card_09.jpg", "Cardale Jones NIL", "$3.99"),
    ("review_22/card_03.jpg", "Jayden Daniels Topps Chrome RC", "$2.99"),
    ("review_21/card_01.jpg", "Bryce Young Select RC", "$2.99"),
    ("review_23/card_01.jpg", "Tetairoa McMillan SAGE", "$2.99"),
    ("review_23/card_04.jpg", "Jaxon Smith-Njigba Select Future RC", "$2.49"),
    ("review_24/card_03.jpg", "TreVeyon Henderson Prizm Fireworks RC", "$2.49"),
    ("review_22/card_08.jpg", "Tyler Warren SAGE", "$2.49"),
    ("review_23/card_07.jpg", "De'Von Achane Absolute", "$1.99"),
    ("review_23/card_02.jpg", "Maxx Crosby Optic", "$1.99"),
    ("review_23/card_03.jpg", "Omarion Hampton SAGE", "$1.99"),
    ("review_22/card_09.jpg", "Torry Holt Prizm Pink", "$1.99"),
]

# (image, name, reason)  — REMOVE = lot or skip
REMOVE = [
    ("review_22/card_01.jpg", "Cam Ward SAGE", "lot"),
    ("review_22/card_02.jpg", "Dylan Sampson SAGE", "lot"),
    ("review_22/card_04.jpg", "Tez Johnson SAGE", "lot"),
    ("review_22/card_05.jpg", "Ja'Corey Brooks SAGE", "lot"),
    ("review_22/card_07.jpg", "Devin Neal SAGE", "lot"),
    ("review_21/card_02.jpg", "Mason Taylor SAGE", "lot"),
    ("review_21/card_03.jpg", "Ted Ginn Jr NIL", "lot"),
    ("review_21/card_04.jpg", "Carson Beck SAGE", "lot"),
    ("review_21/card_05.jpg", "Raheim Sanders SAGE", "lot"),
    ("review_21/card_07.jpg", "Savion Williams SAGE", "lot"),
    ("review_21/card_08.jpg", "Carnell Tate NIL", "lot"),
    ("review_23/card_05.jpg", "Jaydon Blue SAGE", "lot"),
    ("review_23/card_06.jpg", "Tyler Warren SAGE (dup)", "lot"),
    ("review_23/card_08.jpg", "Tyler Warren SAGE (dup)", "lot"),
    ("review_23/card_09.jpg", "Rahjai Harris SAGE", "lot"),
    ("review_24/card_09.jpg", "Jordan Watkins Prizm RC", "lot"),
    ("review_25/card_01.jpg", "Tavien St. Clair NIL", "lot"),
    ("review_25/card_02.jpg", "Ava Shankle NIL (volleyball)", "lot"),
    ("review_25/card_05.jpg", "Michael Redd NIL", "lot"),
    ("review_25/card_06.jpg", "Chance Gray NIL (W hoops)", "lot"),
    ("review_25/card_08.jpg", "Michael Redd NIL (dup)", "lot"),
    ("review_26/card_03.jpg", "Omarion Hampton SAGE (dup)", "lot"),
    ("review_26/card_06.jpg", "DJ Giddens SAGE", "lot"),
    ("review_26/card_09.jpg", "Dillon Gabriel SAGE", "lot"),
    ("review_24/card_01.jpg", "Kalon Gervin SAGE Auto", "auto lot"),
    ("review_24/card_04.jpg", "John Metchie SAGE", "lot"),
    ("review_24/card_07.jpg", "Drew Estrada SAGE Auto", "auto lot"),
    ("review_26/card_01.jpg", "Drew Estrada SAGE Auto (dup)", "auto lot"),
    ("review_26/card_02.jpg", "Camren McDonald SAGE Auto", "auto lot"),
    ("review_26/card_04.jpg", "Bailey Zappe SAGE Artistry", "auto lot"),
    ("review_26/card_05.jpg", "John Metchie SAGE Auto", "auto lot"),
    ("review_26/card_07.jpg", "Greg Brooks SAGE Auto", "auto lot"),
    ("review_26/card_08.jpg", "Isaiah King SAGE Auto", "auto lot"),
]

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=22, leading=26,
                    textColor=colors.HexColor("#0b2545"), spaceAfter=2)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=11, leading=14,
                     textColor=colors.HexColor("#444"), spaceAfter=12)
cap = ParagraphStyle("cap", parent=styles["Normal"], fontSize=8, leading=10,
                     alignment=1, textColor=colors.HexColor("#111"))
GREEN = colors.HexColor("#1b7a3d")
GRAY = colors.HexColor("#6b6b6b")


class Badge(Flowable):
    def __init__(self, text, color, w=1.3 * inch, h=0.19 * inch):
        super().__init__()
        self.text, self.color, self.width, self.height = text, color, w, h

    def draw(self):
        self.canv.setFillColor(self.color)
        self.canv.roundRect(0, 0, self.width, self.height, 4, stroke=0, fill=1)
        self.canv.setFillColor(colors.white)
        self.canv.setFont("Helvetica-Bold", 8)
        self.canv.drawCentredString(self.width / 2, self.height / 2 - 3, self.text)


def cell(img_rel, name, tag, color):
    col = []
    p = Path(R) / img_rel
    if p.exists():
        img = Image(str(p))
        img.drawWidth = 1.15 * inch
        img.drawHeight = 1.15 * inch * (img.imageHeight / img.imageWidth)
        if img.drawHeight > 1.5 * inch:
            img.drawHeight = 1.5 * inch
            img.drawWidth = 1.5 * inch * (img.imageWidth / img.imageHeight)
        img.hAlign = "CENTER"
        col.append(img)
    col += [Spacer(1, 3), Badge(tag, color), Spacer(1, 2), Paragraph(name, cap)]
    return col


def grid(items, tagfn, color):
    rows = [items[i:i + 3] for i in range(0, len(items), 3)]
    data = []
    for row in rows:
        data.append([cell(img, name, tagfn(extra), color) for img, name, extra in row]
                    + [""] * (3 - len(row)))
    t = Table(data, colWidths=[2.45 * inch] * 3)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def main():
    out = Path("output/keep_remove_sheet.pdf")
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.5 * inch, bottomMargin=0.45 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch,
                            title="Keep / Remove Sort Sheet")
    flow = [
        Paragraph(f"KEEP — Post Solo  ({len(KEEP)} cards)", h1),
        Paragraph("Pull these to list individually. Price shown is the suggested list.", sub),
        grid(KEEP, lambda price: f"KEEP  {price}", GREEN),
        PageBreak(),
        Paragraph(f"REMOVE — Lot / Skip  ({len(REMOVE)} cards)", h1),
        Paragraph("These go into lots (SAGE prospects, OSU NIL, SAGE autos) or hold — not worth solo.", sub),
        grid(REMOVE, lambda reason: f"REMOVE · {reason}", GRAY),
    ]
    doc.build(flow)
    dl = Path.home() / "Downloads" / "keep_remove_sheet.pdf"
    shutil.copy(out, dl)
    print(f"Wrote {out}  ({len(KEEP)} keep, {len(REMOVE)} remove)")
    print(f"Copied to {dl}")


if __name__ == "__main__":
    main()
