from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "pull_list_singles_2026_06_09.pdf")

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    topMargin=0.5*inch,
    bottomMargin=0.5*inch,
    leftMargin=0.55*inch,
    rightMargin=0.55*inch,
)

h1 = ParagraphStyle("h1", fontSize=13, fontName="Helvetica-Bold", spaceAfter=2)
sub = ParagraphStyle("sub", fontSize=8, fontName="Helvetica", textColor=colors.gray, spaceAfter=8)
note = ParagraphStyle("note", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.gray)

story = []
story.append(Paragraph("Pull List — Singles  |  June 9 2026", h1))
story.append(Paragraph(
    "10 unlisted cards. Prices = multi-source consensus (CollX + SportsCardsPro). "
    "Check off each as you pull.", sub))
story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))

cards = [
    # (num, player, year_set, serial, collx, scp, list_price, notes)
    (1,  "Woody Marks",          "2025 Panini Select — Pink Prizm", "SN/8",    "$11.75", "$22.51", "$18.99",
     "SCP is HIGHER than CollX here — strong consensus. Numbered /8."),
    (2,  "Aidan Hutchinson",     "2025 Panini Select — Pink Prizm", "SN/6",    "$38.00", "$10.00", "$14.99",
     "CollX inflated. SCP $10 raw. Scarcity premium for /6 bumps it up."),
    (3,  "John Lynch",           "2025 Panini Phoenix — Green Prizm", "SN/25", "$19.99", "$4.00*", "$10.99",
     "*SCP conf 0.60 — may be a bad match. Numbered /25 drives the ask."),
    (4,  "Cole Kmet",            "2025 Panini Select — Pink Prizm", "SN/8",    "$12.50", "$1.50",  "$7.99",
     "SCP says $1.50 raw (TE, low demand) but /8 scarcity justifies premium."),
    (5,  "Travis Kelce",         "2024 Panini Select — Turbocharged Prizm", "—", "$8.59", "$1.21",  "$5.99",
     "Kelce search traffic overrides raw guide. Strong name carry."),
    (6,  "Brock Bowers",         "2024 Panini Select — Select Future Prizm", "—", "$5.50", "N/A",   "$5.99",
     "SCP matched wrong card (Gold Prizm). Use CollX as anchor. Bowers is a name."),
    (7,  "Jaxson Dart",          "2025 Panini Phoenix — Thunderbirds", "—",    "$4.49",  "$3.88",  "$4.99",
     "Best consensus of the group — CollX and SCP within $0.61 of each other."),
    (8,  "Patrick Mahomes II",   "2023 Panini Contenders", "—",                "$4.99",  "$1.34",  "$3.99",
     "Always searched. Low raw guide but name carries bidding."),
    (9,  "Aaron Rodgers",        "2024 Panini Select — Select Numbers Prizm", "—", "$8.50", "$1.01", "$3.99",
     "CollX $8.50 is way high vs SCP. Listing conservatively at $3.99."),
    (10, "Emeka Egbuka",         "2025 Topps Chrome", "RC",                   "$8.00",  "$1.23",  "$3.99",
     "Chrome RC. Low raw guide but RC premium and Egbuka is rising."),
]

# Header row
header = ["#", "Player", "Set / Parallel", "Serial", "CollX", "SCP", "List $", "Pull"]
col_w  = [0.25*inch, 1.3*inch, 2.05*inch, 0.45*inch, 0.5*inch, 0.5*inch, 0.55*inch, 0.4*inch]

rows = [header]
for c in cards:
    rows.append([str(c[0]), c[1], c[2], c[3], c[4], c[5], c[6], "[ ]"])

t = Table(rows, colWidths=col_w, repeatRows=1)
t.setStyle(TableStyle([
    ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
    ("FONTSIZE",    (0, 0), (-1, -1), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eeeeee")]),
    ("GRID",        (0, 0), (-1, -1), 0.25, colors.HexColor("#bbbbbb")),
    ("TOPPADDING",  (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0,0), (-1, -1), 3),
    ("LEFTPADDING", (0, 0), (-1, -1), 4),
    ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
    ("ALIGN",       (4, 0), (-1, -1), "RIGHT"),
    ("ALIGN",       (7, 0), (-1, -1), "CENTER"),
]))
story.append(t)
story.append(Spacer(1, 0.12*inch))

# Notes section
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=5))
story.append(Paragraph("Notes per card:", ParagraphStyle("nh", fontSize=8, fontName="Helvetica-Bold", spaceAfter=3)))

note_rows = [[f"{c[0]}.", c[7]] for c in cards]
nt = Table(note_rows, colWidths=[0.25*inch, 7.25*inch])
nt.setStyle(TableStyle([
    ("FONTNAME",    (0, 0), (-1, -1), "Helvetica"),
    ("FONTSIZE",    (0, 0), (-1, -1), 7.5),
    ("TOPPADDING",  (0, 0), (-1, -1), 2),
    ("BOTTOMPADDING",(0,0), (-1, -1), 2),
    ("LEFTPADDING", (0, 0), (-1, -1), 3),
    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f5f5f5")]),
]))
story.append(nt)

story.append(Spacer(1, 0.1*inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=4))
story.append(Paragraph(
    "10 singles  ·  Total CollX value $119.36  ·  Total list price $87.89",
    note))

doc.build(story)
print(f"PDF written to {OUTPUT}")
