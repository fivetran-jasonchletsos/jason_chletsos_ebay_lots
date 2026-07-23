"""Baseball batch 2 sort/valuation — Scans 476-486 (98 cards, 2025 Topps Chrome +
Panini Prizm, mostly rookies/prospects + a run of Panini Prizm legends). Splits into
INDIVIDUALS (worth listing as singles) vs LOTS (bundle by team, 5 cards or fewer).
Raw/ungraded July 2026 eBay-comp estimates. HOLD — not for posting, per JC's request
to sort only this round.
Writes docs/baseball_batch2_sort.pdf (+ ~/Downloads) and output/_baseball_batch2_sort.json.
"""
import json, re, shutil, math
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

QTY_RE = re.compile(r"x(\d+)\s*cop(?:y|ies)", re.IGNORECASE)
def qty_of(variant):
    m = QTY_RE.search(variant)
    return int(m.group(1)) if m else 1

GRAY_DK = colors.HexColor("#222222")
GRAY_MD = colors.HexColor("#555555")
GRAY_LT = colors.HexColor("#e8e8e8")
BLACK = colors.black
WHITE = colors.white

# (name, variant/note, low, typ, high, note)
INDIVIDUALS = [
 ("Marcelo Mayer","Panini Prizm RC · Red Sox top prospect",4,6,10,""),
 ("Jackson Jobe","Topps Chrome RC · Tigers top pitching prospect",4,6,9,""),
 ("Chase Dollander","Topps Chrome RC · Rockies top pitching prospect",3,5,7,""),
 ("Cam Smith","Topps Chrome RC · Astros, fast MLB debut",3,4,6,""),
 ("Dylan Crews","Topps Chrome RC · Nationals, former #2 overall pick",3,4,6,""),
 ("Cade Horton","Topps Chrome RC (copy 1 of 3) · Cubs rotation piece",3,4,6,""),
 ("Chandler Simpson","Topps Chrome RC (copy 1 of 2) · Rays speedster",2,3,5,""),
 ("Hyeseong Kim","Topps Chrome RC (copy 1 of 2) · Dodgers international debut",2,3,5,""),
 ("Kevin Alcantara","Topps Chrome RC (copy 1 of 2) · Cubs",2,3,4,""),
 ("Brooks Lee","Topps Chrome RC · Twins",2,3,4,""),
 ("Eury Perez","Panini Prizm · Marlins electric arm",2,3,5,""),
 ("Mike Trout / Shohei Ohtani","Topps Chrome 'Fortune 15' insert · Angels",3,4,6,""),
 ("Vladimir Guerrero Jr.","Topps Chrome All-Star Game parallel · Blue Jays",3,4,6,""),
 ("Giancarlo Stanton","Topps Holiday insert · Yankees",2,3,5,""),
 ("Mason Miller","Topps Chrome (Future Star trophy) · Padres, elite closer",2,3,5,""),
 ("Jeremy Pena","Topps Chrome · Astros starting SS",2,3,4,""),
 ("Aroldis Chapman","Topps Chrome (copy 1 of 2) · Red Sox",1,2,3,""),
 ("Nomar Garciaparra","Panini Prizm · Red Sox legend",2,3,4,""),
 ("Omar Vizquel","Panini Prizm · Cleveland legend",1,2,3,""),
 ("Jim Edmonds","Panini Prizm · Cardinals legend",1,2,3,""),
 ("Tim Salmon","Panini Prizm · Angels legend",1,2,3,""),
 ("Paul Molitor","Panini Prizm · Brewers legend",1,2,3,""),
 ("Dustin May","Topps Chrome RC (copy 1 of 2) · Red Sox",2,3,4,""),
 ("David Bednar","Topps Chrome (copy 1 of 2) · Yankees",1,2,3,""),
 ("Bryan Woo","Topps Chrome (copy 1 of 2) · Mariners rotation",1,2,3,""),
]

LOTS = {
 "Los Angeles Angels": [
  ("Garrett McDaniels","Topps Chrome RC (x2 copies)",1,2,3,""),
  ("Jorge Soler","Topps Chrome (x2 copies)",1,2,3,""),
  ("Caden Dana","Topps Chrome RC",1,2,3,""),
  ("Matthew Lugo","Topps Chrome RC",1,2,3,""),
  ("Ky Bush","Panini Prizm RC",1,2,3,""),
  ("Yusei Kikuchi","Topps Chrome",1,2,3,""),
 ],
 "Houston Astros": [
  ("Logan VanWey","Topps Chrome RC",1,2,3,""),
  ("Isaac Paredes","Topps Chrome",1,2,3,""),
  ("Colton Gordon","Topps Chrome RC (x2 copies)",1,2,3,""),
 ],
 "Minnesota Twins": [
  ("Alan Roden","Topps Chrome RC",1,2,3,""),
  ("Zebby Matthews","Topps Chrome RC",1,2,3,""),
  ("Luke Keaschall","Topps Chrome RC",1,2,3,""),
  ("Ryan Fitzgerald","Topps Chrome RC",1,2,3,""),
 ],
 "Detroit Tigers": [
  ("Chase Lee","Topps Chrome RC (x2 copies)",1,2,3,""),
  ("Spencer Torkelson","Topps Chrome",1,2,4,""),
  ("Chris Paddack","Topps Chrome (x2 copies)",1,2,3,""),
 ],
 "Boston Red Sox": [
  ("Aroldis Chapman","Topps Chrome (2nd copy)",1,2,3,""),
  ("Dustin May","Topps Chrome RC (2nd copy)",1,2,3,""),
  ("Ceddanne Rafaela","Topps Chrome",1,2,3,""),
 ],
 "Toronto Blue Jays": [
  ("Seranthony Dominguez","Topps Chrome (x2 copies)",1,2,3,""),
  ("Addison Barger","Panini Prizm",1,2,3,""),
 ],
 "Pittsburgh Pirates": [
  ("Tsung-Che Cheng","Topps Chrome RC (x2 copies)",1,2,3,""),
  ("Braxton Ashcraft","Topps Chrome RC",1,2,3,""),
  ("Ronny Simon","Topps Chrome RC",1,2,3,""),
 ],
 "Chicago Cubs": [
  ("Cade Horton","Topps Chrome RC (x2 copies, copies 2 &amp; 3 of 3)",1,2,3,""),
  ("Kevin Alcantara","Topps Chrome RC (2nd copy)",1,2,3,""),
  ("Moises Ballesteros","Topps Chrome RC",1,2,3,""),
 ],
 "San Diego Padres": [
  ("Will Wagner","Topps Chrome RC",1,2,3,""),
  ("Jason Adam","Topps Chrome",1,2,3,""),
  ("JP Sears","Topps Chrome (x2 copies)",1,2,3,""),
  ("Ramon Laureano","Topps Chrome",1,2,3,""),
 ],
 "Texas Rangers": [
  ("Kumar Rocker","Topps Chrome RC",1,2,3,""),
  ("Blaine Crim","Topps Chrome RC",1,2,3,""),
  ("Alejandro Osuna","Topps Chrome RC",1,2,3,""),
 ],
 "Atlanta Braves": [
  ("Spencer Schwellenbach","Topps Chrome RC",1,2,3,""),
  ("Nathan Wiles","Topps Chrome RC",1,2,3,""),
  ("Drake Baldwin","Topps Chrome RC",1,2,3,""),
 ],
 "New York Yankees": [
  ("Ryan McMahon","Topps Chrome",1,2,3,""),
  ("Amed Rosario","Topps Chrome",1,2,3,""),
  ("David Bednar","Topps Chrome (2nd copy)",1,2,3,""),
  ("J.C. Escarra","Topps Chrome RC",1,2,3,""),
 ],
 "Tampa Bay Rays": [
  ("Chandler Simpson","Topps Chrome RC (2nd copy)",1,2,3,""),
  ("Jake Mangum","Topps Chrome RC (x2 copies)",1,2,3,""),
 ],
 "Kansas City Royals": [
  ("Mike Yastrzemski","Topps Chrome (x2 copies)",1,2,3,""),
  ("Rich Hill","Topps Chrome",1,2,3,""),
  ("Noah Cameron","Topps Chrome RC",1,2,3,""),
 ],
 "Cincinnati Reds": [
  ("Tyler Stephenson","Topps Chrome",1,2,3,""),
  ("Jose Trevino","Topps Chrome",1,2,3,""),
 ],
 "Multi-team mixed lot 1": [
  ("Cade Gibson","Topps Chrome RC · Marlins",1,2,3,""),
  ("Cole Henry","Topps Chrome RC · Nationals",1,2,3,""),
  ("Zac Veen","Topps Chrome RC · Rockies",1,2,3,""),
  ("Logan Evans","Topps Chrome · Mariners",1,2,3,""),
  ("Bryan Woo","Topps Chrome (2nd copy) · Mariners",1,2,3,""),
 ],
 "Multi-team mixed lot 2": [
  ("Logan Henderson","Topps Chrome RC · Brewers",1,2,3,""),
  ("Matt Svanson","Topps Chrome RC · Cardinals",1,2,3,""),
  ("Tyler Locklear","Topps Chrome RC · Diamondbacks",1,2,3,""),
  ("Hyeseong Kim","Topps Chrome RC (2nd copy) · Dodgers",1,2,3,""),
  ("Maverick Handley","Topps Chrome RC · Orioles",1,2,3,""),
 ],
 "Multi-team mixed lot 3": [
  ("Jud Fabian","Panini Prizm · Orioles",1,2,3,""),
  ("Jett Williams","Panini Prizm · Mets",1,2,3,""),
  ("Doug Nikhazy","Topps Chrome RC · Guardians",1,2,3,""),
  ("Jhoan Duran","Topps Chrome · Phillies",1,2,3,""),
 ],
}

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2,textColor=BLACK)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=GRAY_MD,spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=BLACK,spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=GRAY_MD,spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12,textColor=BLACK)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

def table_for(cards):
    data=[["", "Card", "Variant", "Qty", "Low ea", "Typ ea", "High ea"]]
    for n,v,lo,ty,hi,nt in cards:
        q = qty_of(v)
        vv = v + (f" &middot; <i>{nt}</i>" if nt else "")
        data.append(["☐", Paragraph(f"<b>{n}</b>",cardp), Paragraph(f"<font size=8.5>{vv}</font>",cardp),
                     str(q), money(lo), money(ty), money(hi)])
    sub_ty = round(sum(c[3]*qty_of(c[1]) for c in cards),2)
    data.append(["","",Paragraph("<b>subtotal typical</b>",cardp),"","","",Paragraph(f"<b>{money(sub_ty)}</b>",cardp)])
    t=Table(data,colWidths=[0.24*inch,1.6*inch,3.0*inch,0.4*inch,0.55*inch,0.55*inch,0.6*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),GRAY_DK),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[WHITE,GRAY_LT]),
        ("ALIGN",(3,0),(-1,-1),"RIGHT"),("ALIGN",(0,0),(0,-1),"CENTER"),("FONTSIZE",(0,1),(0,-1),13),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEABOVE",(0,-1),(-1,-1),0.6,GRAY_DK),
        ("GRID",(0,0),(-1,-2),.4,GRAY_MD),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
    return t, sub_ty

n_individuals = sum(qty_of(c[1]) for c in INDIVIDUALS)
n_lots = sum(qty_of(c[1]) for cards in LOTS.values() for c in cards)
total_cards = n_individuals + n_lots

def tot(cards, idx):
    return round(sum(c[idx]*qty_of(c[1]) for c in cards),2)
grand_low = tot(INDIVIDUALS,2) + sum(tot(cards,2) for cards in LOTS.values())
grand_typ = tot(INDIVIDUALS,3) + sum(tot(cards,3) for cards in LOTS.values())
grand_high = tot(INDIVIDUALS,4) + sum(tot(cards,4) for cards in LOTS.values())

out=Path("docs/baseball_batch2_sort.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[
 Paragraph("Baseball batch 2 &mdash; sort worksheet (HOLD, not posted)",h1),
 Paragraph(f"{total_cards} cards &middot; Scans 476-486 &middot; raw/ungraded July 2026 eBay-comp estimate",sub),
 Paragraph(f"<b>Total: {money(grand_low)} &ndash; {money(grand_high)}</b> (typical ~{money(grand_typ)})",grp),
 Paragraph(
  "<b>Sort verdict:</b> mostly 2025 Topps Chrome rookies/prospects plus a run of base Panini Prizm "
  "legends (Nomar Garciaparra, Omar Vizquel, Jim Edmonds, Tim Salmon, Paul Molitor). "
  f"<b>{len(INDIVIDUALS)} cards recommended as individual listings</b> &mdash; real chase-prospect names "
  "(Marcelo Mayer, Jackson Jobe, Chase Dollander, Cam Smith, Dylan Crews, Cade Horton, Chandler Simpson, "
  "Hyeseong Kim, Kevin Alcantara, Brooks Lee, Eury Perez), established stars/legends with search-friendly "
  "names (Trout/Ohtani insert, Vladimir Jr., Giancarlo Stanton, Mason Miller, Jeremy Pe&ntilde;a, the five "
  "Prizm legends), and the better copy of a few duplicated cards (Aroldis Chapman, Dustin May, David Bednar, "
  "Bryan Woo). Extra copies of those same cards were routed to the team lots instead of double-listing as "
  "singles. <b>Everything else bundles into team lots of 5 cards or fewer</b> &mdash; mostly org-depth "
  "prospects and journeyman veterans without individual chase demand. Three small multi-team lots mop up "
  "leftover 1-2 card teams (Marlins, Nationals, Rockies, Mariners, Brewers, Cardinals, Diamondbacks, "
  "Orioles, Mets, Guardians, Phillies) rather than posting single-team lots too thin to bundle. "
  "<b>Flag before pulling:</b> Colton Gordon, Jake Mangum, and Chandler Simpson each showed up twice "
  "<i>within the same scan photo</i> (not two different scans) &mdash; worth confirming these are really "
  "2 physical copies in hand and not a re-scanned card, same lesson as the basketball batch mix-up. "
  "Mike Yastrzemski's card prints a Royals uniform (he's a longtime Giant) &mdash; likely a Topps "
  "photo-variation quirk, not a misprint to correct.",
  note),
]

flow.append(Paragraph(f"Individual listings ({len(INDIVIDUALS)} cards)",grp))
t,_ = table_for(INDIVIDUALS)
flow.append(t)

flow.append(Paragraph(f"Team lots ({sum(1 for _ in LOTS)} lots, {n_lots} cards, 5 cards or fewer each)",grp))
for team, cards in LOTS.items():
    flow.append(Paragraph(f"{team} &mdash; {sum(qty_of(c[1]) for c in cards)} cards", ParagraphStyle("lotgrp",parent=grp,fontSize=11,spaceBefore=8,spaceAfter=2)))
    t,_ = table_for(cards)
    flow.append(t)

doc.build(flow)
dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)

Path("output/_baseball_batch2_sort.json").write_text(json.dumps(
 {"individuals":{"count":n_individuals,"cards":[c[0] for c in INDIVIDUALS]},
  "lots":{"count":n_lots,"teams":{k:sum(qty_of(c[1]) for c in v) for k,v in LOTS.items()}},
  "total_cards":total_cards,"grand_total":{"low":grand_low,"typical":grand_typ,"high":grand_high},
  "status":"HOLD - sort only, not posted, per JC's request"},indent=1))

print(f"Individuals: {n_individuals} cards  ·  Lots: {n_lots} cards across {len(LOTS)} lots  ·  Total: {total_cards}")
print(f"Grand total: {money(grand_low)}-{money(grand_high)} (typ {money(grand_typ)}) -> {out} -> {dl}")
