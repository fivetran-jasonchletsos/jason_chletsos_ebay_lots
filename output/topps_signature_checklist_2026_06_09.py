from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, HRFlowable
import os

OUTPUT = os.path.join(os.path.dirname(__file__), "topps_signature_checklist_2026_06_09.pdf")

doc = SimpleDocTemplate(
    OUTPUT, pagesize=letter,
    topMargin=0.45*inch, bottomMargin=0.45*inch,
    leftMargin=0.5*inch, rightMargin=0.5*inch,
)

h1   = ParagraphStyle("h1",  fontSize=12, fontName="Helvetica-Bold", spaceAfter=2)
sub  = ParagraphStyle("sub", fontSize=7.5, fontName="Helvetica", textColor=colors.gray, spaceAfter=6)
sh   = ParagraphStyle("sh",  fontSize=9, fontName="Helvetica-Bold", spaceBefore=8, spaceAfter=3)
fn   = ParagraphStyle("fn",  fontSize=7, fontName="Helvetica-Oblique", textColor=colors.gray)

story = []
story.append(Paragraph("2025 Topps Signature — Player Checklist", h1))
story.append(Paragraph(
    "Go through your stack and check off what you have. "
    "Prices are estimates — no online comps yet. Based on comparable rookie/vet autos in similar sets. "
    "List Tier 1 FIRST before the market floods.", sub))
story.append(HRFlowable(width="100%", thickness=1, color=colors.black, spaceAfter=6))

def tier_table(players, bg_header):
    header = ["Have it", "Player", "Team", "Pos", "Est. List $", "Notes"]
    col_w  = [0.55*inch, 1.6*inch, 1.35*inch, 0.4*inch, 0.75*inch, 2.85*inch]
    rows   = [header] + [["[ ]"] + list(p) for p in players]
    t = Table(rows, colWidths=col_w, repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME",       (0,0), (-1,0),  "Helvetica-Bold"),
        ("FONTSIZE",       (0,0), (-1,-1), 7.5),
        ("BACKGROUND",     (0,0), (-1,0),  bg_header),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f0f0f0")]),
        ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#bbbbbb")),
        ("TOPPADDING",     (0,0), (-1,-1), 3),
        ("BOTTOMPADDING",  (0,0), (-1,-1), 3),
        ("LEFTPADDING",    (0,0), (-1,-1), 4),
        ("VALIGN",         (0,0), (-1,-1), "MIDDLE"),
        ("ALIGN",          (0,0), (0,-1),  "CENTER"),
        ("ALIGN",          (4,0), (4,-1),  "RIGHT"),
    ]))
    return t

# TIER 1
story.append(Paragraph("TIER 1 — List individually, list fast", sh))
story.append(tier_table([
    ("Cam Ward",           "Miami Dolphins",      "QB", "$60–80",  "No. 1 pick. Hottest rookie auto in any 2025 set. Get it live today."),
    ("Travis Hunter",      "Jacksonville Jaguars","WR/CB","$50–80","Heisman winner, dual-position — unique story drives collector premium."),
    ("Shedeur Sanders",    "Cleveland Browns",    "QB", "$40–60",  "Name recognition + first-round QB. Dad effect keeps demand elevated."),
    ("Ashton Jeanty",      "Las Vegas Raiders",   "RB", "$30–50",  "Heisman runner-up, elite RB prospect. RB autos undervalued early."),
    ("Abdul Carter",       "NY Giants",           "EDGE","$25–40", "Top pass rusher. Giants market is large. Price on the higher end."),
], colors.HexColor("#222222")))

story.append(Spacer(1, 0.08*inch))

# TIER 2
story.append(Paragraph("TIER 2 — List individually within 24–48 hrs", sh))
story.append(tier_table([
    ("Mason Graham",       "Cleveland Browns",    "DT", "$15–25",  "Top DT in the class. Niche but Browns collectors are active."),
    ("Tetairoa McMillan",  "Carolina Panthers",   "WR", "$15–22",  "Top WR2 of the class. Early target for Panthers fans."),
    ("Colston Loveland",   "Chicago Bears",       "TE", "$12–20",  "Top TE. Bears fans hungry after rebuild. Good sell."),
    ("Will Johnson",       "Pittsburgh Steelers", "CB", "$10–18",  "Top CB. Steelers secondary collector base."),
    ("Emeka Egbuka",       "Tampa Bay Buccaneers","WR", "$10–18",  "Already have his Chrome RC listed — auto is a step up."),
    ("Darius Robinson",    "Kansas City Chiefs",  "EDGE","$10–16", "Chiefs player = immediate audience. Pass rusher upside."),
    ("Luther Burden III",  "Chicago Bears",       "WR", "$8–15",   "Slot WR with high floor. Bears stack with Loveland."),
    ("Kyle Williams",      "Washington Commanders","WR","$8–14",   "Fast riser. Commanders WR1 candidate going into camp."),
    ("Omarion Hampton",    "Los Angeles Rams",    "RB", "$8–14",   "Top RB2. Rams brand helps. Early RB autos move quick."),
    ("Harold Fannin Jr.",  "Cleveland Browns",    "TE", "$8–12",   "Broke the college TE record. Underrated — good early price."),
], colors.HexColor("#555555")))

story.append(Spacer(1, 0.08*inch))

# TIER 3 — VETERANS
story.append(Paragraph("TIER 3 — Veterans (if on-card auto, list individually; sticker, lot it)", sh))
story.append(tier_table([
    ("Patrick Mahomes",    "Kansas City Chiefs",  "QB", "$80–150", "Always the top seller. List immediately regardless of parallel."),
    ("Josh Allen",         "Buffalo Bills",       "QB", "$60–100", "You already have 2 Contenders — Allen auto is a major upgrade."),
    ("Lamar Jackson",      "Baltimore Ravens",    "QB", "$50–80",  "MVP demand is consistent year-round."),
    ("Joe Burrow",         "Cincinnati Bengals",  "QB", "$35–60",  "Strong collector base, Bengals fans buy."),
    ("Justin Jefferson",   "Minnesota Vikings",   "WR", "$25–45",  "Best WR in the league. Always searched."),
    ("CeeDee Lamb",        "Dallas Cowboys",      "WR", "$25–40",  "Cowboys brand × WR1 = strong demand."),
    ("Brock Purdy",        "San Francisco 49ers", "QB", "$20–35",  "Underdog story = deep collector loyalty."),
    ("Drake Maye",         "New England Patriots","QB", "$20–35",  "You already sold a Maye card. Auto is significantly more."),
    ("Jayden Daniels",     "Washington Commanders","QB","$20–35",  "OROY. Washington market is buying."),
    ("Bo Nix",             "Denver Broncos",      "QB", "$12–22",  "You have Prizm of him listed already. Auto bumps it up."),
], colors.HexColor("#888888")))

story.append(Spacer(1, 0.08*inch))

# LOT PILE
story.append(Paragraph("LOT PILE — Everything else (bundle by team or position tonight)", sh))
lot_rows = [
    ["[ ]", "Any non-star rookie", "— lot with 5–10 similar rookies", "$9.99–14.99 per lot"],
    ["[ ]", "Any non-star veteran", "— lot by team (Bills lot, Chiefs lot, etc.)", "$7.99–12.99 per lot"],
    ["[ ]", "Linemen / Kickers / Punters", "— bulk lot, price low, move volume", "$4.99–7.99 per lot"],
]
lt = Table(lot_rows, colWidths=[0.55*inch, 1.8*inch, 3.4*inch, 1.75*inch])
lt.setStyle(TableStyle([
    ("FONTSIZE",       (0,0), (-1,-1), 7.5),
    ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#f0f0f0"), colors.white]),
    ("GRID",           (0,0), (-1,-1), 0.25, colors.HexColor("#bbbbbb")),
    ("TOPPADDING",     (0,0), (-1,-1), 3),
    ("BOTTOMPADDING",  (0,0), (-1,-1), 3),
    ("LEFTPADDING",    (0,0), (-1,-1), 4),
    ("ALIGN",          (0,0), (0,-1),  "CENTER"),
]))
story.append(lt)

story.append(Spacer(1, 0.1*inch))
story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#999999"), spaceAfter=4))
story.append(Paragraph(
    "Strategy: Tier 1 gets listed TODAY before market comps appear. "
    "Tier 2 within 48 hrs. Tier 3 veterans anytime — name demand is evergreen. "
    "Lot everything else tonight. First-mover advantage on new sets is real.",
    fn))

doc.build(story)
print(f"PDF written to {OUTPUT}")
