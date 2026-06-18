"""Pull list PDF — big names, one page."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_CENTER

OUT = "docs/pull_list_3_june2026.pdf"

doc = SimpleDocTemplate(OUT, pagesize=letter,
    leftMargin=0.75*inch, rightMargin=0.75*inch,
    topMargin=0.5*inch, bottomMargin=0.4*inch)

BLACK = colors.black
MGRAY = colors.HexColor("#555555")
LGRAY = colors.HexColor("#bbbbbb")

TITLE  = ParagraphStyle("T",  fontSize=13, leading=16, textColor=BLACK, spaceAfter=2, fontName="Helvetica-Bold", alignment=TA_CENTER)
SUB    = ParagraphStyle("S",  fontSize=8,  leading=10, textColor=MGRAY, spaceAfter=6, fontName="Helvetica", alignment=TA_CENTER)
NAME   = ParagraphStyle("NM", fontSize=18, leading=21, textColor=BLACK, fontName="Helvetica-Bold", spaceAfter=1)
DETAIL = ParagraphStyle("D",  fontSize=8.5, leading=10, textColor=MGRAY, fontName="Helvetica", spaceAfter=4)
FOOT   = ParagraphStyle("F",  fontSize=7,  leading=9,  textColor=MGRAY, fontName="Helvetica", alignment=TA_CENTER)

def rule(): return HRFlowable(width="100%", thickness=0.35, color=LGRAY, spaceBefore=3, spaceAfter=3)

PLAYERS = [
    (1,  "Tyreek Hill",        "Miami Dolphins · WR"),
    (2,  "Justin Jefferson",   "Minnesota Vikings · WR"),
    (3,  "Puka Nacua",         "Los Angeles Rams · WR"),
    (4,  "Derrick Henry",      "Baltimore Ravens · RB"),
    (5,  "Drake Maye",         "New England Patriots · QB"),
    (6,  "Joe Burrow",         "Cincinnati Bengals · QB"),
    (7,  "Ja'Marr Chase",      "Cincinnati Bengals · WR"),
    (8,  "CeeDee Lamb",        "Dallas Cowboys · WR"),
    (9,  "Brian Thomas Jr.",   "Jacksonville Jaguars · WR"),
    (10, "George Kittle",      "San Francisco 49ers · TE"),
]

story = [
    Paragraph("JC² Cards — Pull List 3", TITLE),
    Paragraph("June 2026", SUB),
    rule(),
]

for rank, name, detail in PLAYERS:
    story.append(Paragraph(f"{rank}.  {name}", NAME))
    story.append(Paragraph(detail, DETAIL))
    if rank < 10:
        story.append(rule())

story += [
    Spacer(1, 6),
    rule(),
    Paragraph("JC² Cards · June 2026 · Exclude: Jaxson Dart · NY Giants · Eagles (Jack's)", FOOT),
]

doc.build(story)
print(f"PDF: {OUT}")
