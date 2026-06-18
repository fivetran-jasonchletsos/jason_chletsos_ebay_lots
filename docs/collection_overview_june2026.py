"""JC2 Cards — Personal Collection Overview PDF. One page, grayscale, printable."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

OUT = "/Users/jason.chletsos/Downloads/JC2_Collection_Overview_June2026.pdf"

doc = SimpleDocTemplate(OUT, pagesize=letter,
    leftMargin=0.65*inch, rightMargin=0.65*inch,
    topMargin=0.45*inch, bottomMargin=0.35*inch)

BLACK  = colors.black
DGRAY  = colors.HexColor("#222222")
MGRAY  = colors.HexColor("#555555")
LGRAY  = colors.HexColor("#aaaaaa")
XLGRAY = colors.HexColor("#dddddd")

TITLE  = ParagraphStyle("T",  fontSize=14, leading=17, textColor=BLACK, fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=1)
SUB    = ParagraphStyle("S",  fontSize=8,  leading=10, textColor=MGRAY, fontName="Helvetica",      alignment=TA_CENTER, spaceAfter=8)
PHDR   = ParagraphStyle("PH", fontSize=12, leading=14, textColor=BLACK, fontName="Helvetica-Bold", spaceAfter=1)
PTAG   = ParagraphStyle("PT", fontSize=7.5, leading=9, textColor=MGRAY, fontName="Helvetica",      spaceAfter=4)
ITEM   = ParagraphStyle("IT", fontSize=7.5, leading=10, textColor=DGRAY, fontName="Helvetica",     spaceAfter=1, leftIndent=8)
FOOT   = ParagraphStyle("FT", fontSize=6.5, leading=8.5, textColor=LGRAY, fontName="Helvetica",   alignment=TA_CENTER)
TOTLBL = ParagraphStyle("TL", fontSize=9,  leading=11, textColor=DGRAY, fontName="Helvetica-Bold", alignment=TA_CENTER, spaceBefore=6)

def rule(thin=False):
    t = 0.25 if thin else 0.5
    return HRFlowable(width="100%", thickness=t, color=LGRAY if thin else DGRAY, spaceBefore=4, spaceAfter=4)

PLAYERS = [
    {
        "name":  "Jaxson Dart",
        "pos":   "QB · NY Giants · #10 (2025 1st Rd, Pick 22)",
        "total": 62,
        "value": 360,
        "highlights": [
            "2025 Panini Prizm Flashback Auto RC /99  —  PC anchor",
            "2025 Panini Select Numbers #22 die-cut  —  3 copies",
            "2025 Panini Select Turbocharged insert",
            "2025 Topps Signature Class In Session insert",
            "2025 Panini Donruss Optic Rated Rookie (multiple parallels)",
            "2025 Topps Chrome Edge Xfractor RC",
        ],
    },
    {
        "name":  "Cam Skattebo",
        "pos":   "RB · NY Giants · #34 (2025 4th Rd, Pick 109)",
        "total": 26,
        "value": 110,
        "highlights": [
            "2025 Panini Prizm Base RC Silver  —  2 copies",
            "2025 Panini Select Concourse RC  —  multiple copies",
            "2025 Panini Donruss Optic Rated Rookie",
            "2025 Topps Signature Class Round 4 Pick 109 base",
            "2025 Panini Score Super Rookie RC",
        ],
    },
    {
        "name":  "Malik Nabers",
        "pos":   "WR · NY Giants · #1 (2024 1st Rd, Pick 6)",
        "total": 56,
        "value": 430,
        "highlights": [
            "2024 Panini Prizm Emergent #6  PSA 10 GEM MT  —  $75",
            "2024 Panini Absolute Stars & Stripes /425  (numbered)",
            "2024 Panini Select Numbers #1 die-cut  —  3 copies",
            "2024 Panini Mosaic Prizm / Multi-color parallel",
            "2024 Panini Donruss Optic Rated Rookie  —  2 copies",
        ],
    },
    {
        "name":  "Abdul Carter",
        "pos":   "LB · NY Giants · #51 (2025 1st Rd, Pick 3)",
        "total": 29,
        "value": 310,
        "highlights": [
            "2025 Topps Chrome Edge Xfractor RC  —  premium Topps",
            "2025 Panini Prizm Prizmatic insert  —  chase card",
            "2025 Topps Signature Class Class Jams insert  —  2 copies",
            "2025 Panini Select Turbocharged insert",
            "2025 Panini Select Select Certified insert",
            "2025 Panini Mosaic Notoriety insert (draft day photo)",
        ],
    },
]

TOTAL_CARDS = sum(p["total"] for p in PLAYERS)
TOTAL_VALUE = sum(p["value"] for p in PLAYERS)

story = [
    Paragraph("JC² Cards — Personal Collection Overview", TITLE),
    Paragraph("NY Giants Prospect PC · Not For Sale · June 2026", SUB),
    rule(),
]

for i, p in enumerate(PLAYERS):
    story.append(Paragraph(p["name"], PHDR))
    story.append(Paragraph(f"{p['pos']}   ·   {p['total']} cards   ·   est. ${p['value']:,}", PTAG))
    for h in p["highlights"]:
        story.append(Paragraph(f"•  {h}", ITEM))
    if i < len(PLAYERS) - 1:
        story.append(Spacer(1, 4))
        story.append(rule(thin=True))
        story.append(Spacer(1, 4))

story += [
    Spacer(1, 6),
    rule(),
    Paragraph(f"Total: {TOTAL_CARDS} cards across 4 players   ·   Est. collection value: ${TOTAL_VALUE:,}", TOTLBL),
    Spacer(1, 6),
    Paragraph("JC² Cards · Jason + Jack Chletsos · Personal collection only · Never for sale", FOOT),
]

doc.build(story)
print(f"PDF: {OUT}")
