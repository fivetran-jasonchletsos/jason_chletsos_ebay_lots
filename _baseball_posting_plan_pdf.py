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
 ("Abbott","Andrew Abbott","Reds · Topps 75 checkerboard parallel",1,2,3,""),
 ("Alonso","Pete Alonso","Orioles · graffiti insert",1,2,4,""),
 ("Altuve","Jose Altuve","Astros · Topps Heritage",1,3,5,""),
 ("Alvarez","Yordan Alvarez","Astros · graffiti insert",1,3,5,""),
 ("Aparicio","Luis Aparicio","White Sox · Panini Crusade, legend",1,2,4,""),
 ("Arenado","Nolan Arenado","Diamondbacks · graffiti insert",1,2,4,""),
 ("Arozarena","Randy Arozarena","Mariners · Topps 75 silver crystal parallel",1,2,4,""),
 ("Aybar","Erick Aybar","Allen & Ginter 2012 throwback design",1,2,3,""),
 ("Basallo","Samuel Basallo","Orioles · baseballs insert RC",2,5,10,""),
 ("Bell","David Bell","Mariners · Topps Heritage RC (printed signature)",1,2,3,""),
 ("Beltre","Adrian Beltre","Rangers · Topps 'Glove Work' insert, legend",2,4,6,""),
 ("Betts","Mookie Betts","Dodgers · Glove Work insert",2,4,6,""),
 ("Betts","Mookie Betts","Dodgers · Titans of the Game insert (2nd design)",2,4,6,""),
 ("Bogaerts","Xander Bogaerts","Padres · gold parallel #0201/2025",2,3,5,""),
 ("Burger","Jake Burger","Rangers · Topps 75 crystal parallel",1,2,3,""),
 ("Burns","Chase Burns","Guardians · baseballs insert RC",2,4,6,""),
 ("Buxton","Byron Buxton","Twins · star insert",1,3,5,""),
 ("Cabrera","Miguel Cabrera","Allen & Ginter throwback, legend — Giants uniform is a print quirk, eyeball first",2,4,7,""),
 ("Caissie","Owen Caissie","Cubs · Panini Crusade Certified Prospects",1,3,6,""),
 ("Caissie","Owen Caissie","Marlins · graffiti insert RC (2nd design)",2,4,7,""),
 ("Caminero","Junior Caminero","Rays · star insert",1,3,5,""),
 ("Carroll","Corbin Carroll","Diamondbacks · graffiti insert",1,3,5,""),
 ("Carroll","Corbin Carroll","Diamondbacks · Fortune 15 insert",1,3,5,""),
 ("Carroll","Corbin Carroll","Diamondbacks · Topps Heritage '35th Anniversary'",1,3,5,""),
 ("Chandler","Bubba Chandler","Pirates · baseballs insert RC (copy 1)",2,4,7,"confirm 2 real copies, not a re-scan"),
 ("Chandler","Bubba Chandler","Pirates · baseballs insert RC (copy 2)",2,4,7,"confirm 2 real copies, not a re-scan"),
 ("Chourio","Jackson Chourio","Brewers · baseballs insert",1,3,5,""),
 ("Chourio","Jackson Chourio","Brewers · graffiti insert (2nd design)",1,3,5,""),
 ("Clemente","Roberto Clemente","Pirates · Topps Heritage NL All-Stars, legend",2,5,8,""),
 ("Corona","Kenedy Corona","Astros · Topps 75 checkerboard 'FL' parallel RC",1,2,3,""),
 ("Crochet","Garrett Crochet","Red Sox · Topps Heritage pink sparkle parallel",1,3,5,""),
 ("Crow-Armstrong","Pete Crow-Armstrong","Cubs · Fortune 15 insert",1,3,5,""),
 ("Cruz","Oneil Cruz","Pirates · Power Players insert",1,3,5,""),
 ("Castillo","Luis Castillo","Mariners · Topps Holiday-style insert",1,2,3,""),
 ("Dana","Caden Dana","Angels · Topps Heritage RC",1,2,3,""),
 ("deGrom","Jacob deGrom","Rangers · Topps Heritage",1,3,5,""),
 ("De La Cruz","Elly De La Cruz","Reds · RC",1,3,5,""),
 ("De La Cruz","Elly De La Cruz","Reds · Topps Heritage",1,3,5,""),
 ("DeLauter","Chase DeLauter","Guardians · Future Stars graffiti RC",1,2,3,""),
 ("Devers","Rafael Devers","Red Sox · Topps 75 Grapefruit League",1,2,4,""),
 ("Devers","Rafael Devers","Giants · Chrome 'Night Terrors' insert — eyeball team print first",1,3,5,""),
 ("Diaz","Yainer Diaz","Astros · Topps 75 crystal parallel",1,2,4,""),
 ("Duran","Jarren Duran","Red Sox · Future Stars graffiti insert",1,2,4,""),
 ("Duran","Jarren Duran","Red Sox · graffiti insert (2nd design)",1,2,4,""),
 ("Eldridge","Bryce Eldridge","Giants · baseballs insert RC",2,4,7,""),
 ("Estevez/Suarez","Carlos Estevez / Robert Suarez","Leading Firemen combo insert",1,2,3,""),
 ("Freeland","Alex Freeland","Dodgers · graffiti insert RC",1,2,3,""),
 ("Freeman","Freddie Freeman","Dodgers · graffiti insert",1,3,5,""),
 ("Fricano","Marion Fricano","Athletics · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Gilbert","Drew Gilbert","Giants · Topps 75 RC",1,2,3,""),
 ("Goldschmidt","Paul Goldschmidt","Yankees · star insert",1,2,4,""),
 ("Gonzales","Nick Gonzales","Pirates · Topps 75 checkerboard parallel",1,2,3,""),
 ("Greene","Riley Greene","Tigers · 2025 Record Breaker insert",1,2,4,""),
 ("Guerrero","Vladimir Guerrero Jr.","Blue Jays · sparkle parallel",1,3,5,""),
 ("Guerrero","Vladimir Guerrero Jr.","Topps 75 All-Star NL",1,3,5,""),
 ("Guerrero","Vladimir Guerrero Jr.","Blue Jays · Titans of the Game insert",1,3,5,""),
 ("Guerrero","Vladimir Guerrero Jr.","Blue Jays · graffiti insert",1,3,5,""),
 ("Harris","Hayden Harris","Braves · Topps 75 crystal parallel RC",1,2,4,""),
 ("Helsley","Ryan Helsley","Orioles · Topps 75 crystal parallel",1,2,3,""),
 ("Hernaiz","Darell Hernaiz","Athletics · Topps Heritage sparkle parallel RC",1,2,4,""),
 ("Hess","Ben Hess","White Sox · Panini Crusade",1,2,4,""),
 ("Hicks","Liam Hicks","Marlins · Topps 75 crystal parallel RC",1,2,3,""),
 ("Hoglund","Gunnar Hoglund","Athletics · Topps Chrome geometric parallel RC",1,2,4,""),
 ("House","Brady House","Nationals · graffiti insert RC",1,2,4,""),
 ("Janek","Hunter Janek","Astros · Panini Crusade #230/299",2,4,7,""),
 ("Jackson","Reggie Jackson","Athletics · Topps 75 All-Star AL, legend",2,4,6,""),
 ("Jolly","Dave Jolly","Braves · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Jones","Chipper Jones","Braves · Panini Crusade, legend",2,4,6,""),
 ("Jones","Jahmai Jones","Tigers · Topps 75 crystal parallel",1,2,3,""),
 ("Judge","Aaron Judge","Yankees · Topps 75 Grapefruit League",1,3,5,""),
 ("Judge","Aaron Judge","Yankees · Panini Crusade 'Call to Arms' insert",2,4,7,""),
 ("Judge","Aaron Judge","Yankees · Topps Chrome '62 Home Runs' insert",2,4,7,""),
 ("Judge","Aaron Judge","Yankees · Topps '144 RBI' insert",2,4,7,""),
 ("Kikuchi","Yusei Kikuchi","Angels · Topps Heritage",1,2,3,""),
 ("Koufax","Sandy Koufax","Dodgers · '382 Strikeouts' insert, legend",2,5,9,""),
 ("Kwan","Steven Kwan","Guardians · Glove Work insert",1,3,5,""),
 ("Labine","Clem Labine","Dodgers · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Langford","Wyatt Langford","Rangers · graffiti insert",1,2,4,""),
 ("Lewis","Royce Lewis","Twins · star insert",1,2,4,""),
 ("Lee","Brooks Lee","Twins · star insert RC (copy 1)",1,2,4,"confirm 2 real copies vs copy 2 below"),
 ("Lee","Brooks Lee","Twins · star insert RC (copy 2)",1,2,4,"confirm 2 real copies vs copy 1 above"),
 ("Lee","Brooks Lee","Twins · Topps 75 Future Stars RC (different design)",1,2,4,""),
 ("Lee","Jung Hoo Lee","Giants · RC",1,2,3,""),
 ("Logan","Johnny Logan","Braves · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Lowder","Rhett Lowder","Reds · RC",1,2,3,""),
 ("Lowder","Rhett Lowder","Reds · Panini Crusade Certified Stars RC",1,3,5,""),
 ("Lowder","Rhett Lowder","Reds · Topps 75 Future Stars",1,2,4,""),
 ("Lowder","Rhett Lowder","Reds · Topps Chrome jersey-graphic RC",1,3,5,""),
 ("Lowder","Rhett Lowder","Reds · Panini Crusade 'Call to Arms' insert",1,3,5,""),
 ("Machado","Manny Machado","Padres · Power Players insert",1,3,5,""),
 ("Made","Jesus Made","Brewers · Panini Crusade",1,3,6,""),
 ("Matthews","Brice Matthews","Astros · graffiti insert RC",1,2,4,""),
 ("Mayer","Marcelo Mayer","Red Sox · Fortune 15 RC",1,3,6,""),
 ("McGwire","Mark McGwire","Athletics · Upper Deck 'Capture the Flag' vintage insert",2,5,9,""),
 ("Melton","Troy Melton","Tigers · Topps 75 camo parallel RC",1,2,4,""),
 ("Merrill","Jackson Merrill","Padres · baseballs insert RC",2,4,7,""),
 ("Merrill","Jackson Merrill","Padres · graffiti insert (2nd design)",1,3,5,""),
 ("Misiorowski","Jacob Misiorowski","Brewers · Panini Crusade",1,3,6,""),
 ("Montgomery","Braden Montgomery","White Sox · Panini Crusade Certified Prospects",1,3,5,""),
 ("Moore","Christian Moore","Angels · graffiti insert RC",1,2,4,""),
 ("Muncy","Max Muncy","Athletics · Topps 75 Future Stars RC",1,2,3,""),
 ("Murakami","Munetaka Murakami","White Sox · baseballs insert RC",2,5,10,""),
 ("Murakami","Munetaka Murakami","White Sox · graffiti insert RC (2nd design)",2,4,7,""),
 ("Neto","Zach Neto","Angels · Topps 75 crystal parallel",1,2,4,""),
 ("Ohtani","Shohei Ohtani","Dodgers · Bowman Veterans",1,3,6,""),
 ("Okamoto","Kazuma Okamoto","Blue Jays · Topps 75 crystal parallel RC",1,2,4,""),
 ("Olson","Karl Olson","Red Sox · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Olson","Matt Olson","Braves · Power Players insert",1,2,4,""),
 ("Ortiz","Joey Ortiz","Brewers · pink/purple crystal parallel",1,2,3,""),
 ("Pascual","Camilo Pascual","Senators · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Pujols","Albert Pujols","Angels · Topps Heritage AL All-Stars, legend",1,3,5,""),
 ("Purkey","Bob Purkey","Pirates · Topps 75 vintage tribute, legend",1,3,5,""),
 ("Quero","Edgar Quero","White Sox · Future Stars RC",1,2,3,""),
 ("Raleigh","Cal Raleigh","Mariners · graffiti insert",1,3,5,""),
 ("Raleigh","Cal Raleigh","Mariners · Topps Heritage AL All-Stars (copy 1)",1,3,5,"confirm 2 real copies vs copy 2"),
 ("Raleigh","Cal Raleigh","Mariners · Topps Heritage AL All-Stars (copy 2)",1,3,5,"confirm 2 real copies vs copy 1"),
 ("Ramirez","Jose Ramirez","Guardians · Topps Chrome 'Fortune 15' insert",1,2,4,""),
 ("Rodon","Carlos Rodon","Yankees · Topps Chrome geometric parallel",1,2,4,""),
 ("Rodriguez","Ivan Rodriguez","Rangers · Glove Work insert, legend",2,4,6,""),
 ("Rutschman","Adley Rutschman","Orioles · Topps 75",1,3,5,""),
 ("Ryan","Nolan Ryan","Topps Heritage All-Star NL, legend",2,5,9,""),
 ("Sale","Chris Sale","Braves · Topps 75 crystal parallel",1,3,5,""),
 ("Sandberg","Ryne Sandberg","Cubs · Topps 75, legend",1,3,5,""),
 ("Schlittler","Cam Schlittler","Yankees · baseballs insert RC",2,4,7,""),
 ("Schlittler","Cam Schlittler","Yankees · graffiti insert RC (2nd design)",2,4,6,""),
 ("Schwarber","Kyle Schwarber","Phillies · graffiti insert",1,2,4,""),
 ("Sele","Aaron Sele","Mariners · Topps Heritage RC (printed signature)",1,2,3,""),
 ("Seager","Corey Seager","Rangers · star insert (copy 1)",1,2,3,"confirm 2 real copies vs copy 2"),
 ("Seager","Corey Seager","Rangers · star insert (copy 2)",1,2,3,"confirm 2 real copies vs copy 1"),
 ("Skenes","Paul Skenes","Pirates · Panini Crusade base insert",3,5,8,""),
 ("Skubal","Tarik Skubal","Tigers · baseballs insert RC",1,3,5,""),
 ("Skubal","Tarik Skubal","Tigers · star insert (2nd design)",1,3,5,""),
 ("Smyth","Steve Smyth","Cubs · Topps Heritage RC (printed signature)",1,2,3,""),
 ("Sommers","Drew Sommers","Tigers · Topps 75 crystal parallel RC",1,2,3,""),
 ("Sproat","Brandon Sproat","Brewers · Topps 75 purple parallel RC",1,3,6,""),
 ("Stanton","Giancarlo Stanton","Yankees · sparkle parallel",1,2,3,""),
 ("Stewart","Sal Stewart","Reds · Topps 75 gold sunburst RC",1,3,6,""),
 ("Sugano","Tomoyuki Sugano","Orioles · Panini Crusade RC",1,3,5,""),
 ("Suzuki","Ichiro Suzuki","Mariners · Topps Heritage 'Turn Back the Clock', legend",2,4,7,""),
 ("Suzuki","Seiya Suzuki","Cubs · baseballs insert",1,2,3,""),
 ("Suzuki","Seiya Suzuki","Cubs · Topps 75 checkerboard parallel (2nd design)",1,2,3,""),
 ("Swanson","Dansby Swanson","Cubs · sparkle parallel",1,2,3,""),
 ("Tatis","Fernando Tatis Jr.","Padres · graffiti insert",1,3,5,""),
 ("Tatis","Fernando Tatis Jr.","Padres · baseballs insert",1,3,5,""),
 ("Tatis","Fernando Tatis Jr.","Padres · Topps Chrome 1990-inspired design",1,3,5,""),
 ("Taylor","Brayden Taylor","Rays · Panini Crusade",1,2,4,""),
 ("Teel","Kyle Teel","White Sox · graffiti insert RC",2,4,7,""),
 ("Thomas","Frank Thomas","White Sox · Panini Crusade, legend",2,4,6,""),
 ("Tolle","Payton Tolle","Red Sox · graffiti insert RC",1,2,4,""),
 ("Torkelson","Spencer Torkelson","Tigers · Topps 75 sunburst gold parallel",1,2,4,""),
 ("Tucker","Kyle Tucker","Dodgers · Topps 75 crystal parallel",1,3,6,""),
 ("Turner","Trea Turner","Phillies · star insert",1,3,5,""),
 ("Veen","Zac Veen","Rockies · Topps 75 chrome parallel",1,2,3,""),
 ("Wade","Ben Wade","Dodgers · Topps 75 vintage tribute, legend",1,2,4,""),
 ("Wagner","Honus Wagner","Pirates · Topps 75 vintage tribute, legend",2,5,9,""),
 ("Ward","Taylor Ward","Angels · Topps 75 gold sunburst parallel — prints Orioles/BAL, known quirk",1,2,4,""),
 ("Winn","Masyn Winn","Cardinals · Panini Crusade",1,3,5,""),
 ("Witt","Bobby Witt Jr.","Royals · Gameday Drip insert",1,3,6,""),
 ("Witt","Bobby Witt Jr.","Royals · Topps Chrome 'Terrors' insert",1,3,5,""),
 ("Wood","James Wood","Nationals · star insert RC",2,4,6,""),
 ("Wood","James Wood","Nationals · Titans of the Game insert",2,4,6,""),
 ("Yastrzemski","Carl Yastrzemski","Red Sox · Glove Work insert, legend",2,4,7,""),
 ("Yesavage","Trey Yesavage","Blue Jays · baseballs insert RC",2,4,7,""),
 ("Young","Cole Young","Mariners · baseballs insert RC",1,3,5,""),
 ("Young","Cole Young","Mariners · graffiti insert RC (2nd design)",1,3,5,""),
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
      Paragraph(f"174 cards remaining in lots &middot; Scans 391-411 &middot; lots grouped by team, alphabetized within each lot to match your physical A-Z sort",sub),
      Paragraph("<b>4 individuals now LIVE</b> (Roenis Elias II, Juan Morillo, and both Randy Johnson "
                f"Panini Crusade Numbers parallels) + {len(lots)} team lots of 5 cards or fewer remain to post. "
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
