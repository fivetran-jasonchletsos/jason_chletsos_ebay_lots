from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "pull_list_2026_06_09.pdf")

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    topMargin=0.5*inch,
    bottomMargin=0.5*inch,
    leftMargin=0.55*inch,
    rightMargin=0.55*inch,
)

styles = getSampleStyleSheet()
header_style = ParagraphStyle("header", fontSize=13, fontName="Helvetica-Bold", spaceAfter=2)
sub_style = ParagraphStyle("sub", fontSize=8, fontName="Helvetica", textColor=colors.gray, spaceAfter=6)
section_style = ParagraphStyle("section", fontSize=10, fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)
row_style = ParagraphStyle("row", fontSize=8.5, fontName="Helvetica", leading=11)
note_style = ParagraphStyle("note", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.gray)

story = []

# Title
story.append(Paragraph("eBay Pull List — June 9, 2026", header_style))
story.append(Paragraph("CollX unlisted cards cross-referenced against live eBay snapshot (261 active, 915 unlisted)", sub_style))
story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))

# ---- SECTION 1: INDIVIDUAL LISTINGS ----
story.append(Paragraph("SINGLES — List Individually", section_style))

singles = [
    ["#", "Card", "Set", "Serial", "CollX $", "List $"],
    ["1", "Aidan Hutchinson #271", "2025 Panini Select Pink Prizm", "SN/6", "$38.00", "$45–50"],
    ["2", "John Lynch #131", "2025 Panini Phoenix Green Prizm", "SN/25", "$19.99", "$22"],
    ["3", "Stefon Diggs #94", "2024 Panini Select Silver Prizm", "—", "$19.00", "$19.99"],
    ["4", "Cole Kmet #174", "2025 Panini Select Pink Prizm", "SN/8", "$12.50", "$14.99"],
    ["5a", "Travis Kelce #13 (copy 1)", "2024 Panini Select Turbocharged Prizm", "—", "$8.59", "$9.99"],
    ["5b", "Travis Kelce #13 (copy 2)", "2024 Panini Select Turbocharged Prizm", "—", "$8.59", "$9.99"],
]

col_widths = [0.3*inch, 1.8*inch, 2.3*inch, 0.55*inch, 0.6*inch, 0.65*inch]
t = Table(singles, colWidths=col_widths, repeatRows=1)
t.setStyle(TableStyle([
    ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
    ("FONTSIZE", (0,0), (-1,-1), 8),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f0f0")]),
    ("GRID", (0,0), (-1,-1), 0.25, colors.HexColor("#cccccc")),
    ("TOPPADDING", (0,0), (-1,-1), 3),
    ("BOTTOMPADDING", (0,0), (-1,-1), 3),
    ("LEFTPADDING", (0,0), (-1,-1), 4),
    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
]))
story.append(t)
story.append(Spacer(1, 0.15*inch))

# ---- SECTION 2: LOTS ----
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=6))
story.append(Paragraph("LOTS — Pull & Bundle", section_style))

lots = [
    {
        "num": 1,
        "title": "2024 Panini Select Red & Yellow Prizm Shock — 20-card lot",
        "price": "$14.99",
        "draw": "J.J. McCarthy RC on top",
        "pool": "109 cards in inventory — pull 20, prioritize McCarthy RC, then best names",
    },
    {
        "num": 2,
        "title": "2023 Panini Contenders — 15-card lot",
        "price": "$12.99",
        "draw": "2x Josh Allen, 2x Jalen Hurts as draw cards",
        "pool": "71 cards in inventory — pull Allen + Hurts first, fill with best names",
    },
    {
        "num": 3,
        "title": "2025 Panini Prizm — 15-card lot",
        "price": "$11.99",
        "draw": "Emeka Egbuka RC as headline",
        "pool": "33 cards in inventory — pull Egbuka RC first, fill with Silver parallels",
    },
    {
        "num": 4,
        "title": "2025 Panini Phoenix — 15-card lot",
        "price": "$9.99",
        "draw": "Jaxson Dart RC",
        "pool": "26 cards in inventory — pull Dart RC, Jaxson Dart base, fill remainder",
    },
    {
        "num": 5,
        "title": "2024 Panini Select Silver Prizm Die Cut — 15-card lot",
        "price": "$9.99",
        "draw": "Josh Allen + Dak Prescott",
        "pool": "29 cards in inventory — pull Allen + Prescott first, fill with skill positions",
    },
]

for lot in lots:
    row_data = [
        [
            Paragraph(f"<b>LOT {lot['num']}  {lot['title']}</b>   List: {lot['price']}", row_style),
        ],
        [
            Paragraph(f"Draw card(s): {lot['draw']}    |    Pool: {lot['pool']}", note_style),
        ],
    ]
    lt = Table(row_data, colWidths=[7.15*inch])
    lt.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#e8e8e8")),
        ("BACKGROUND", (0,1), (-1,1), colors.white),
        ("BOX", (0,0), (-1,-1), 0.4, colors.HexColor("#aaaaaa")),
        ("TOPPADDING", (0,0), (-1,-1), 3),
        ("BOTTOMPADDING", (0,0), (-1,-1), 3),
        ("LEFTPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(lt)
    story.append(Spacer(1, 0.05*inch))

story.append(Spacer(1, 0.15*inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=4))
story.append(Paragraph("6 singles (5 cards + 1 duplicate Kelce)  +  5 lots  =  11 listings total", note_style))

doc.build(story)
print(f"PDF written to {OUTPUT}")
