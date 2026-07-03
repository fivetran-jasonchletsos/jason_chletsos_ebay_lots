"""build_big5_pull_pdf.py — pull sheet for the big-5 glut-player lots
(Lamar, Daniels, Stroud, Burrow, Caleb). One page per player, 5 card thumbnails
(from output/_lot_thumbs cached during the auto-build) with a check box + item id.
Writes output/big5_lot_pull.pdf and copies to ~/Downloads.
"""
from pathlib import Path
import shutil

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak, Image, Flowable)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

THUMBS = Path("output/_lot_thumbs")

LOTS = [
    {"player": "LAMAR JACKSON", "sub": "Baltimore Ravens  ·  list at $12.99", "cards": [
        ("306999472549", "Select Premier Level #160"),
        ("307020777166", "2024 Score"),
        ("306999472522", "Donruss Base"),
        ("306914174921", "Rookies & Stars Artistry in Motion"),
        ("307007016021", "Absolute"),
    ]},
    {"player": "JAYDEN DANIELS", "sub": "Washington Commanders  ·  list at $12.99", "cards": [
        ("306930942401", "Prizm Draft Picks #178 Silver"),
        ("307004672735", "Select Future Insert"),
        ("307004672963", "Absolute"),
        ("307021796285", "Select Certified RC"),
        ("307021796416", "Mosaic Touchdown Masters"),
    ]},
    {"player": "C.J. STROUD", "sub": "Houston Texans  ·  list at $13.99", "cards": [
        ("306998210982", "Totally Certified #33"),
        ("307001075966", "Select Turbocharged Insert"),
        ("307021800070", "Donruss Base"),
        ("307018704792", "Donruss Base (2nd)"),
        ("306998478794", "Donruss #40"),
    ]},
    {"player": "JOE BURROW", "sub": "Cincinnati Bengals  ·  list at $11.99", "cards": [
        ("306955931330", "Select Concourse #57 Silver"),
        ("307021783475", "Signature Class"),
        ("307021788323", "Prestige"),
        ("307021790088", "Select Green Flash Prizm"),
        ("306994502065", "Signature Class Sunday Showcase"),
    ]},
    {"player": "CALEB WILLIAMS", "sub": "Chicago Bears  ·  list at $12.99", "cards": [
        ("306999815763", "Rookies and Stars"),
        ("307000686030", "Select Future RC Insert"),
        ("307006958992", "Select Future Insert RC"),
        ("307021797692", "Absolute #60"),
        ("307021799725", "Mosaic #22 Silver"),
    ]},
]

styles = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=styles["Title"], fontSize=26, leading=30,
                    textColor=colors.HexColor("#0b2545"), spaceAfter=2)
sub = ParagraphStyle("sub", parent=styles["Normal"], fontSize=13, leading=16,
                     textColor=colors.HexColor("#444"), spaceAfter=16)
cap = ParagraphStyle("cap", parent=styles["Normal"], fontSize=8.5, leading=10.5,
                     alignment=1, textColor=colors.HexColor("#111"))
meta = ParagraphStyle("meta", parent=styles["Normal"], fontSize=7.5, leading=9,
                      alignment=1, textColor=colors.HexColor("#777"))
note = ParagraphStyle("note", parent=styles["Normal"], fontSize=10, leading=13,
                      textColor=colors.HexColor("#7a1f1f"))


class CheckBox(Flowable):
    def __init__(self, size=13):
        super().__init__()
        self.width = self.height = size

    def draw(self):
        self.canv.setLineWidth(1.2)
        self.canv.setStrokeColor(colors.HexColor("#0b2545"))
        self.canv.roundRect(0, 0, self.width, self.height, 2, stroke=1, fill=0)


def card_cell(iid, name):
    col = []
    p = THUMBS / f"{iid}.jpg"
    if p.exists():
        img = Image(str(p))
        img.drawWidth = 1.18 * inch
        img.drawHeight = 1.18 * inch * (img.imageHeight / img.imageWidth)
        if img.drawHeight > 1.6 * inch:
            img.drawHeight = 1.6 * inch
            img.drawWidth = 1.6 * inch * (img.imageWidth / img.imageHeight)
        img.hAlign = "CENTER"
        col.append(img)
    else:
        col.append(Paragraph("(no image)", meta))
    col += [Spacer(1, 3), CheckBox(), Spacer(1, 2),
            Paragraph(name, cap), Paragraph(iid, meta)]
    return col


def page(lot):
    el = [Paragraph(lot["player"], h1), Paragraph(lot["sub"], sub)]
    cells = [card_cell(iid, name) for iid, name in lot["cards"]]
    t = Table([cells], colWidths=[1.4 * inch] * 5)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    el += [t, Spacer(1, 0.4 * inch),
           Paragraph('When you\'ve pulled this player\'s 5, tell me "[player] is ready" and I\'ll repost the lot.', note)]
    return el


def main():
    out = Path("output/big5_lot_pull.pdf")
    doc = SimpleDocTemplate(str(out), pagesize=letter,
                            topMargin=0.7 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.55 * inch, rightMargin=0.55 * inch,
                            title="Big 5 Lot Pull Sheet")
    flow = []
    for i, lot in enumerate(LOTS):
        flow += page(lot)
        if i < len(LOTS) - 1:
            flow.append(PageBreak())
    doc.build(flow)
    dl = Path.home() / "Downloads" / "big5_lot_pull.pdf"
    shutil.copy(out, dl)
    print(f"Wrote {out}")
    print(f"Copied to {dl}")


if __name__ == "__main__":
    main()
