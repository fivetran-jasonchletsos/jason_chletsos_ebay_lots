from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "pull_list_singles_2026_06_09b.pdf")

doc = SimpleDocTemplate(
    OUTPUT, pagesize=letter,
    topMargin=0.5*inch, bottomMargin=0.5*inch,
    leftMargin=0.55*inch, rightMargin=0.55*inch,
)

h1  = ParagraphStyle("h1", fontSize=13, fontName="Helvetica-Bold", spaceAfter=2)
sub = ParagraphStyle("sub", fontSize=8, fontName="Helvetica", textColor=colors.gray, spaceAfter=8)
nh  = ParagraphStyle("nh", fontSize=8, fontName="Helvetica-Bold", spaceAfter=3)
fn  = ParagraphStyle("fn", fontSize=7.5, fontName="Helvetica-Oblique", textColor=colors.gray)

story = []
story.append(Paragraph("Pull List — Singles  |  June 9 2026  (Batch 2)", h1))
story.append(Paragraph(
    "10 unlisted cards. Prices = multi-source consensus (CollX + SportsCardsPro). "
    "Check off each as you pull.", sub))
story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=8))

cards = [
    # (num, player, set/parallel, serial, collx, scp, list$, note)
    (1,  "Stefon Diggs",       "2024 Panini Select — Silver Prizm",               "—",      "$19.00", "$2.38",  "$4.99",
     "CollX inflated (retired WR). SCP raw $2.38 but Silver Prizm parallel adds premium."),
    (2,  "Sam Howell",         "2023 Panini Contenders — Red Zone Ticket 1st OTL", "—",      "$5.00",  "$5.00",  "$4.99",
     "Best consensus this batch — CollX and SCP identical. Clean comp."),
    (3,  "Puka Nacua",         "2024 Panini Select — Select Numbers Prizm",        "—",      "$4.75",  "$1.09",  "$3.99",
     "SCP raw low but Nacua is a live searched name. Numbers Prizm carries it."),
    (4,  "Puka Nacua",         "2025 Panini Phoenix — Lime Green Pyramids Prizm",  "SN/285", "$4.00",  "N/A*",   "$3.99",
     "*SCP matched wrong card (WNBA). CollX anchor. Serial number justifies premium."),
    (5,  "Dalton Kincaid",     "2023 Panini Contenders Draft Class — Teal",        "SN/149", "$4.00",  "N/A*",   "$3.99",
     "*SCP matched wrong card (Allen Iverson). CollX anchor. SN/149 is the sell."),
    (6,  "Brian Thomas Jr.",   "2024 Panini Select — Select Future Prizm",         "—",      "$4.00",  "$0.97",  "$2.99",
     "Rising WR2. SCP raw low but BTJ has strong collector demand in 2024 Select."),
    (7,  "Tyler Warren",       "2025 Topps Chrome",                                "RC",     "$4.00",  "$1.09",  "$2.99",
     "Chrome RC. Tight end RCs move. Warren had a strong rookie season."),
    (8,  "Michael Penix Jr.",  "2024 Panini Select — Select Future Prizm",         "—",      "$4.00",  "$0.99",  "$2.99",
     "Starting QB for Atlanta. Low raw guide but Falcons fan base buys."),
    (9,  "Josh Allen",         "2023 Panini Contenders",                           "—",      "$3.00",  "$2.25",  "$2.99",
     "Decent consensus. Allen always gets searched — name carry even at base price."),
    (10, "Jack Sawyer",        "2025 Topps Chrome",                                "RC",     "$3.00",  "$1.27",  "$2.99",
     "Pass rusher RC. Chrome RCs move fast. Good conf 0.97 on SCP match."),
]

header = ["#", "Player", "Set / Parallel", "Serial", "CollX", "SCP", "List $", "Pull"]
col_w  = [0.25*inch, 1.35*inch, 2.1*inch, 0.45*inch, 0.5*inch, 0.5*inch, 0.5*inch, 0.4*inch]

rows = [header] + [[str(c[0]), c[1], c[2], c[3], c[4], c[5], c[6], "[ ]"] for c in cards]

t = Table(rows, colWidths=col_w, repeatRows=1)
t.setStyle(TableStyle([
    ("FONTNAME",       (0,0), (-1,0),  "Helvetica-Bold"),
    ("FONTSIZE",       (0,0), (-1,-1), 8),
    ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#eeeeee")]),
    ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#bbbbbb")),
    ("TOPPADDING",     (0,0), (-1,-1), 3),
    ("BOTTOMPADDING",  (0,0), (-1,-1), 3),
    ("LEFTPADDING",    (0,0), (-1,-1), 4),
    ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
    ("ALIGN",          (4,0), (-1,-1), "RIGHT"),
    ("ALIGN",          (7,0), (-1,-1), "CENTER"),
]))
story.append(t)
story.append(Spacer(1, 0.12*inch))

story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=5))
story.append(Paragraph("Notes per card:", nh))

note_rows = [[f"{c[0]}.", c[7]] for c in cards]
nt = Table(note_rows, colWidths=[0.25*inch, 7.25*inch])
nt.setStyle(TableStyle([
    ("FONTNAME",       (0,0), (-1,-1), "Helvetica"),
    ("FONTSIZE",       (0,0), (-1,-1), 7.5),
    ("TOPPADDING",     (0,0), (-1,-1), 2),
    ("BOTTOMPADDING",  (0,0), (-1,-1), 2),
    ("LEFTPADDING",    (0,0), (-1,-1), 3),
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#f5f5f5")]),
]))
story.append(nt)

story.append(Spacer(1, 0.1*inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=4))
story.append(Paragraph(
    "10 singles  ·  Total CollX value $55.75  ·  Total list price $36.89  ·  "
    "Egbuka (Chrome RC) held — post when found", fn))

doc.build(story)
print(f"PDF written to {OUTPUT}")
