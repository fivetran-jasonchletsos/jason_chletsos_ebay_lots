"""Baseball batch POSTING PLAN — Scans 391-411 (179 cards), alphabetized by player last
name to match JC's physical A-Z sort. 3 real autos pulled as individual listings; the
rest split into lots of 5 cards or fewer, in alphabetical runs so each lot pulls straight
off the sorted stack. NOT auto-posted — this is the plan for JC to review before anything
goes live on eBay.
Writes docs/baseball_posting_plan.pdf (+ ~/Downloads) and output/_baseball_posting_plan.json.
"""
import json, math, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

GRAY_DK = colors.HexColor("#222222")
GRAY_MD = colors.HexColor("#555555")
GRAY_LT = colors.HexColor("#e8e8e8")
BLACK = colors.black
WHITE = colors.white

# Individual listings — real numbered/certified autos, pulled out of the alphabetical run
# NOTE: Paul O'Neill Topps Certified Auto is a GIFT to JC's best friend — excluded from sale entirely.
# Both POSTED LIVE 2026-07-21 (see item IDs in note field).
INDIVIDUALS = [
 ("Roenis Elias II","Mariners · Topps Certified Autograph /45",8,12,18,"POSTED $14.99 — item 307077710546"),
 ("Juan Morillo","Diamondbacks · Topps Chrome auto RC #031/199",8,13,18,"POSTED $15.99 — item 307077711037"),
 ("Randy Johnson","Mariners (not Diamondbacks — corrected) · Panini Crusade Numbers Green #025/249",6,10,15,"POSTED $9.99 — item 307077912239"),
 ("Randy Johnson","Mariners · Panini Crusade Numbers Blue parallel (2nd copy, non-green)",1,3,5,"POSTED $3.99 — item 307077912619"),
]

# (last_name_sort_key, display name, variant, low, typ, high, note)
CARDS = [
]

TEAM_INSERTS = [
 ("Batting Leaders (Arraez/Ohtani/Ozuna)","Topps 75 NL Leaders",1,2,4,""),
 ("Beantown Boys","Red Sox · team insert, gold parallel",1,2,4,""),
 ("Beantown Buds","Red Sox · Topps 75 team insert",1,2,3,""),
 ("Chicago Cubs","NL team celebration card",1,2,3,""),
 ("Detroit Tigers","AL team celebration card",1,2,3,""),
 ("New York Yankees","Topps 75 All-Star Game team insert",1,2,3,""),
 ("Reds 'All Smiles'","Team insert (copy 1)",1,2,3,""),
 ("Reds 'All Smiles'","Team insert, crystal parallel (copy 2)",1,2,3,""),
 ("Tampa Bay Rays","Topps Heritage team photo card",1,2,3,""),
]

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2,textColor=BLACK)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=GRAY_MD,spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=BLACK,spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=GRAY_MD,spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12,textColor=BLACK)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

# Group by TEAM first (so lots make sense as a bundle), then alphabetize by last name
# WITHIN each team/lot so the cards are easy to pull off JC's physically-sorted A-Z stack.
NO_TEAM = "Multi-team / Legends inserts"
def team_of(variant):
    if " · " in variant:
        return variant.split(" · ", 1)[0].strip()
    return NO_TEAM

by_team = {}
for row in CARDS:
    t = team_of(row[2])
    by_team.setdefault(t, []).append(row)

LOTS_PER = 5
lots = []          # list of (team, sublot_index, total_sublots, cards)
for team in sorted(by_team.keys()):
    cards = sorted(by_team[team], key=lambda c: c[0])  # alphabetize within team
    n_sub = math.ceil(len(cards) / LOTS_PER)
    for i in range(n_sub):
        chunk = cards[i*LOTS_PER:(i+1)*LOTS_PER]
        lots.append((team, i+1, n_sub, chunk))

def lot_title(team, idx, n_sub):
    return f"{team} lot {idx} of {n_sub}" if n_sub > 1 else f"{team}"

out=Path("docs/baseball_posting_plan.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Baseball batch &mdash; POSTING PLAN",h1),
      Paragraph("ALL 47 team lots + 4 individuals now LIVE &middot; Scans 391-411 &middot; only the team-insert bundle remains",sub),
      Paragraph("<b>51 items now LIVE</b> &mdash; 4 individuals (Roenis Elias II, Juan Morillo, both Randy Johnson "
                "Panini Crusade Numbers parallels) + all 47 team lots across every team in this batch (Angels, "
                "Astros, Athletics, Blue Jays, Braves, Brewers, Cardinals, Cubs, Diamondbacks, Dodgers, Giants, "
                "Guardians, Mariners, Marlins, Multi-team/Legends, Nationals, Orioles, Padres, Phillies, Pirates, "
                "Rangers, Rays, Red Sox, Reds, Rockies, Royals, Senators, Tigers, Twins, White Sox, Yankees). "
                "<b>Only the 9-card team-insert bundle below is still unposted</b> (JC: hold on the team cards). "
                "Paul O'Neill's signed auto is excluded &mdash; that one's a gift, not for sale.",grp)]

# Individuals table
flow.append(Paragraph("Individual listings — LIVE as of 2026-07-21",grp))
data=[["", "Card", "Variant", "List Price"]]
for n,v,lo,ty,hi,nt in INDIVIDUALS:
    data.append(["☐", Paragraph(f"<b>{n}</b>",cardp), Paragraph(f"<font size=8.5>{v}</font>",cardp), Paragraph(f"<b>{nt}</b>",cardp)])
t=Table(data,colWidths=[0.28*inch,1.6*inch,3.6*inch,1.5*inch])
t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("BACKGROUND",(0,0),(-1,0),GRAY_DK),("TEXTCOLOR",(0,0),(-1,0),WHITE),
    ("ROWBACKGROUNDS",(0,1),(-1,-1),[WHITE,GRAY_LT]),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("GRID",(0,0),(-1,-1),.4,GRAY_MD),
    ("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
flow.append(t)

# Lots — grouped by team, alphabetized within each lot
flow.append(Paragraph(f"Team lots ({len(lots)} lots, {LOTS_PER} cards or fewer each)",grp))
lot_summaries=[]
for i, (team, idx, n_sub, lot) in enumerate(lots, 1):
    lot_typ = round(sum(c[4] for c in lot), 2)
    lot_low = round(sum(c[3] for c in lot), 2)
    lot_high = round(sum(c[5] for c in lot), 2)
    title = lot_title(team, idx, n_sub)
    lot_summaries.append({"lot":i,"team":title,"cards":[c[1] for c in lot],"suggested_price":lot_typ})
    flow.append(Paragraph(f"Lot {i}: {title} &mdash; list at {money(lot_typ)}",
                ParagraphStyle("lotgrp",parent=grp,fontSize=11,spaceBefore=8,spaceAfter=2)))
    data=[["", "Card", "Variant"]]
    for last, n, v, lo, ty, hi, nt in lot:
        vv = v + (f" &middot; <i>{nt}</i>" if nt else "")
        data.append(["☐", Paragraph(f"<b>{n}</b>",cardp), Paragraph(f"<font size=8.5>{vv}</font>",cardp)])
    t=Table(data,colWidths=[0.24*inch,1.7*inch,4.9*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),GRAY_LT),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("GRID",(0,0),(-1,-1),.3,GRAY_MD),
        ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5)]))
    flow.append(t)

# Team/multi-player inserts as their own final lot(s)
flow.append(Paragraph("Team &amp; multi-player insert cards (bundle separately)",grp))
ti_typ = round(sum(c[3] for c in TEAM_INSERTS), 2)
data=[["", "Card", "Variant"]]
for n,v,lo,ty,hi,nt in TEAM_INSERTS:
    data.append(["☐", Paragraph(f"<b>{n}</b>",cardp), Paragraph(f"<font size=8.5>{v}</font>",cardp)])
t=Table(data,colWidths=[0.24*inch,1.7*inch,4.9*inch])
t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
    ("BACKGROUND",(0,0),(-1,0),GRAY_LT),
    ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("GRID",(0,0),(-1,-1),.3,GRAY_MD),
    ("TOPPADDING",(0,0),(-1,-1),2.5),("BOTTOMPADDING",(0,0),(-1,-1),2.5)]))
flow.append(t)
flow.append(Paragraph(f"Team-insert lot &mdash; list at {money(ti_typ)}",note))

flow.append(Paragraph("Duplicates flagged inline (Brooks Lee, Cal Raleigh, Bubba Chandler, Corey Seager) — "
    "confirm each is a real second physical copy before listing both; if either turns out to be a re-scan, "
    "just drop the extra row and the lot still holds together. Two team-print quirks to eyeball: Miguel "
    "Cabrera (Giants uniform on an Allen &amp; Ginter throwback) and Rafael Devers (Giants on a Chrome insert). "
    "All prices are raw/ungraded typical-value list points from the July 2026 comp pass &mdash; nothing posted "
    "yet, this is the plan for review.", note))

doc.build(flow)
dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)

Path("output/_baseball_posting_plan.json").write_text(json.dumps(
 {"individuals":[{"name":n,"variant":v,"list_price":nt} for n,v,lo,ty,hi,nt in INDIVIDUALS],
  "lots":lot_summaries,
  "team_inserts":{"cards":[c[0] for c in TEAM_INSERTS],"suggested_price":ti_typ},
  "status":"PLAN ONLY - not posted, pending JC review"},indent=1))

print(f"{len(INDIVIDUALS)} individuals + {len(lots)} team lots ({len(CARDS)} cards) + 1 team-insert lot ({len(TEAM_INSERTS)} cards)")
print(f"wrote {out} -> {dl} + output/_baseball_posting_plan.json")
