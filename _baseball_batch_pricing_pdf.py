"""Baseball batch sort/valuation — Scans 391-409 (171 cards, 2026 Topps flagship/Heritage/
Chrome + Panini Crusade). Raw/ungraded July 2026 eBay-comp estimates. Black-and-white print.
HOLD — not for posting. More scans to come; re-run/extend this script as they arrive.
Writes docs/baseball_batch_pricing.pdf (+ ~/Downloads) and output/_baseball_batch_pricing.json.
"""
import json, shutil
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

# (name, variant, low, typ, high, note)
GROUPS = {
 "Scan 397 — Topps 75 chrome/crystal parallels": [
  ("Giancarlo Stanton","Yankees · sparkle parallel",1,2,3,""),
  ("Joey Ortiz","Brewers · pink/purple crystal parallel",1,2,3,""),
  ("Zach Neto","Angels · Topps 75 crystal parallel",1,2,4,""),
  ("Randy Arozarena","Mariners · Topps 75 silver crystal parallel",1,2,4,""),
  ("Reggie Jackson","Athletics · Topps 75 All-Star AL, legend",2,4,6,"legend nostalgia premium"),
  ("Jake Burger","Rangers · Topps 75 crystal parallel",1,2,3,""),
  ("Yainer Diaz","Astros · Topps 75 crystal parallel",1,2,4,""),
  ("Drew Gilbert","Giants · Topps 75 RC",1,2,3,""),
  ("Adley Rutschman","Orioles · Topps 75",1,3,5,""),
 ],
 "Scan 393 — Topps 'orbiting baseballs' RC insert + Future Stars": [
  ("Seiya Suzuki","Cubs · baseballs insert",1,2,3,""),
  ("Trey Yesavage","Blue Jays · baseballs insert RC",2,4,7,""),
  ("Edgar Quero","White Sox · Future Stars RC",1,2,3,""),
  ("Cam Schlittler","Yankees · baseballs insert RC",2,4,7,""),
  ("Munetaka Murakami","White Sox · baseballs insert RC",2,5,10,""),
  ("Jarren Duran","Red Sox · Future Stars graffiti insert",1,2,4,""),
  ("Chase Burns","Guardians · baseballs insert RC",2,4,6,""),
  ("Tarik Skubal","Tigers · baseballs insert RC (Topps 75 sub)",1,3,5,""),
  ("Chase DeLauter","Guardians · Future Stars graffiti RC",1,2,3,""),
 ],
 "Scan 392 — Topps graffiti/paint insert": [
  ("Wyatt Langford","Rangers · graffiti insert",1,2,4,""),
  ("Kyle Schwarber","Phillies · graffiti insert",1,2,4,""),
  ("Brice Matthews","Astros · graffiti insert RC",1,2,4,""),
  ("Cal Raleigh","Mariners · graffiti insert",1,3,5,""),
  ("Cam Schlittler","Yankees · graffiti insert RC (2nd design)",2,4,6,""),
  ("Christian Moore","Angels · graffiti insert RC",1,2,4,""),
  ("Alex Freeland","Dodgers · graffiti insert RC",1,2,3,""),
  ("Pete Alonso","Orioles · graffiti insert",1,2,4,""),
  ("Fernando Tatis Jr.","Padres · graffiti insert",1,3,5,""),
 ],
 "Scan 394 — mixed vintage-style + legend inserts": [
  ("Rafael Devers","Red Sox · Topps 75 Grapefruit League",1,2,4,""),
  ("Aaron Judge","Yankees · Topps 75 Grapefruit League",1,3,5,""),
  ("Batting Leaders (Arraez/Ohtani/Ozuna)","Topps 75 NL Leaders",1,2,4,""),
  ("Corey Seager","Rangers · star insert (copy 1)",1,2,3,""),
  ("Corey Seager","Rangers · star insert (copy 2, duplicate)",1,2,3,"same design as copy 1 — confirm you meant to scan two"),
  ("Mark McGwire","Athletics · Upper Deck 'Capture the Flag' vintage insert",2,5,9,"older/vintage insert — worth a closer look, not standard 2026 flagship"),
  ("Bubba Chandler","Pirates · baseballs insert RC",2,4,7,""),
  ("Elly De La Cruz","Reds · RC",1,3,5,""),
  ("Jackson Merrill","Padres · baseballs insert RC",2,4,7,""),
 ],
 "Scan 391 — Topps 75 geometric/chrome parallels": [
  ("Nick Gonzales","Pirates · Topps 75 checkerboard parallel",1,2,3,""),
  ("Troy Melton","Tigers · Topps 75 camo parallel RC",1,2,4,""),
  ("Dansby Swanson","Cubs · sparkle parallel",1,2,3,""),
  ("Andrew Abbott","Reds · Topps 75 checkerboard parallel",1,2,3,""),
  ("Hayden Harris","Braves · Topps 75 crystal parallel RC",1,2,4,""),
  ("Vladimir Guerrero Jr.","Blue Jays · sparkle parallel",1,3,5,""),
  ("Ryan Helsley","Orioles · Topps 75 crystal parallel",1,2,3,""),
  ("Kyle Tucker","Dodgers · Topps 75 crystal parallel",1,3,6,""),
  ("Xander Bogaerts","Padres · gold parallel #0201/2025",2,3,5,"confirmed serialized by JC — but /2025 is a year-tie-in print run (large), so modest bump only, not scarce like a true low-numbered parallel"),
 ],
 "Scan 395 — mixed inserts (Power Players / Bowman / Gameday Drip)": [
  ("Samuel Basallo","Orioles · baseballs insert RC",2,5,10,""),
  ("Seiya Suzuki","Cubs · Topps 75 checkerboard parallel (2nd design)",1,2,3,""),
  ("Manny Machado","Padres · Power Players insert",1,3,5,""),
  ("Shohei Ohtani","Dodgers · Bowman Veterans",1,3,6,""),
  ("Matt Olson","Braves · Power Players insert",1,2,4,""),
  ("Junior Caminero","Rays · star insert",1,3,5,""),
  ("Jung Hoo Lee","Giants · RC",1,2,3,""),
  ("Rhett Lowder","Reds · RC",1,2,3,""),
  ("Bobby Witt Jr.","Royals · Gameday Drip insert",1,3,6,""),
 ],
 "Scan 396 — star/graffiti inserts + Topps 75 All-Star": [
  ("Tarik Skubal","Tigers · star insert (2nd design)",1,3,5,""),
  ("Brooks Lee","Twins · star insert RC (copy 1)",1,2,4,"DUPLICATE — same design as copy 2 below, confirm two real copies"),
  ("Royce Lewis","Twins · star insert",1,2,4,""),
  ("Corbin Carroll","Diamondbacks · graffiti insert",1,3,5,""),
  ("Owen Caissie","Marlins · graffiti insert RC",2,4,7,""),
  ("Brandon Sproat","Brewers · Topps 75 purple parallel RC",1,3,6,""),
  ("Brooks Lee","Twins · star insert RC (copy 2, duplicate)",1,2,4,"DUPLICATE — see copy 1 above"),
  ("Kyle Teel","White Sox · graffiti insert RC",2,4,7,""),
  ("Vladimir Guerrero Jr.","Topps 75 All-Star NL (2nd design)",1,3,5,""),
 ],
 "Scan 398 — Allen & Ginter throwback + Heritage": [
  ("Miguel Cabrera","Allen & Ginter 2012 throwback design",2,4,7,"legend nostalgia — Giants uniform on card is a print quirk, eyeball before listing"),
  ("Detroit Tigers","AL team celebration card",1,2,3,""),
  ("Jacob deGrom","Rangers · Topps Heritage",1,3,5,""),
  ("Erick Aybar","Allen & Ginter 2012 throwback design",1,2,3,""),
  ("Elly De La Cruz","Reds · Topps Heritage",1,3,5,""),
  ("Roenis Elias II","Mariners · Topps Certified Autograph /45",8,12,18,"real numbered autograph — no direct comp found, priced off comparable depth-pitcher certified auto tier"),
  ("Riley Greene","Tigers · 2025 Record Breaker insert",1,2,4,""),
  ("Jose Altuve","Astros · Topps Heritage",1,3,5,""),
  ("Yusei Kikuchi","Angels · Topps Heritage",1,2,3,""),
 ],
 "Scan 408 — Panini Crusade prospects/parallels": [
  ("Jesus Made","Brewers · Panini Crusade",1,3,6,""),
  ("Paul Skenes","Pirates · Panini Crusade base insert",3,5,8,"star power premium even on common insert tier"),
  ("Rhett Lowder","Reds · Panini Crusade Certified Stars RC",1,3,5,""),
  ("Randy Johnson","Diamondbacks · Panini Crusade 'Numbers' Green parallel #025/249",6,10,15,"confirmed by JC: green-background copy is serialized 025/249 — real numbered legend insert, not a scan duplicate"),
  ("Luis Castillo","Mariners · Topps Holiday-style insert",1,2,3,""),
  ("Masyn Winn","Cardinals · Panini Crusade",1,3,5,""),
  ("Owen Caissie","Cubs · Panini Crusade Certified Prospects",1,3,6,""),
  ("Brayden Taylor","Rays · Panini Crusade",1,2,4,""),
  ("Braden Montgomery","White Sox · Panini Crusade Certified Prospects",1,3,5,""),
 ],
 "Scan 409 — mixed chrome parallels (partial page, 6 cards)": [
  ("Gunnar Hoglund","Athletics · Topps Chrome geometric parallel RC",1,2,4,""),
  ("Jackson Chourio","Brewers · baseballs insert",1,3,5,""),
  ("Zac Veen","Rockies · Topps 75 chrome parallel",1,2,3,""),
  ("Munetaka Murakami","White Sox · graffiti insert RC (3rd design)",2,4,7,""),
  ("Nolan Arenado","Diamondbacks · graffiti insert",1,2,4,""),
  ("Trea Turner","Phillies · star insert",1,3,5,""),
 ],
 "Scan 407 — mixed inserts + Crusade + Heritage vintage": [
  ("Payton Tolle","Red Sox · graffiti insert RC",1,2,4,""),
  ("Fernando Tatis Jr.","Padres · baseballs insert",1,3,5,""),
  ("Ben Hess","White Sox · Panini Crusade",1,2,4,""),
  ("Cal Raleigh","Mariners · Topps Heritage AL All-Stars (copy 1)",1,3,5,"DUPLICATE — same design as copy in Scan 401, confirm two real copies"),
  ("Rhett Lowder","Reds · Topps 75 Future Stars",1,2,4,""),
  ("Rhett Lowder","Reds · Topps Chrome jersey-graphic RC (different design)",1,3,5,""),
  ("Ichiro Suzuki","Mariners · Topps Heritage 'Turn Back the Clock'",2,4,7,"legend nostalgia premium"),
  ("Paul Goldschmidt","Yankees · star insert",1,2,4,""),
  ("Jacob Misiorowski","Brewers · Panini Crusade",1,3,6,""),
 ],
 "Scan 406 — Topps Chrome insert families (Fortune 15 / Glove Work)": [
  ("Jose Ramirez","Guardians · Topps Chrome 'Fortune 15' insert",1,2,4,""),
  ("Fernando Tatis Jr.","Padres · Topps Chrome 1990-inspired design",1,3,5,""),
  ("Adrian Beltre","Rangers · Topps 'Glove Work' insert, legend",2,4,6,""),
  ("Corbin Carroll","Diamondbacks · Fortune 15 insert",1,3,5,""),
  ("Marcelo Mayer","Red Sox · Fortune 15 RC",1,3,6,""),
  ("Ivan Rodriguez","Rangers · Glove Work insert, legend",2,4,6,""),
  ("Pete Crow-Armstrong","Cubs · Fortune 15 insert",1,3,5,""),
  ("James Wood","Nationals · star insert RC",2,4,6,""),
  ("Mookie Betts","Dodgers · Glove Work insert",2,4,6,""),
 ],
 "Scan 405 — Panini Crusade + Topps 75 team card": [
  ("Luis Aparicio","White Sox · Panini Crusade, legend",1,2,4,""),
  ("Randy Johnson","Diamondbacks · Panini Crusade jersey-numeral insert, different (non-green, unnumbered) parallel",1,2,4,"confirmed different from the green /249 copy in Scan 408 — not a duplicate"),
  ("Frank Thomas","White Sox · Panini Crusade, legend",2,4,6,""),
  ("Chipper Jones","Braves · Panini Crusade, legend",2,4,6,""),
  ("Aaron Judge","Yankees · Panini Crusade 'Call to Arms' insert",2,4,7,""),
  ("Hunter Janek","Astros · Panini Crusade #230/299",2,4,7,""),
  ("Tomoyuki Sugano","Orioles · Panini Crusade RC",1,3,5,""),
  ("Rhett Lowder","Reds · Panini Crusade 'Call to Arms' insert (3rd design this batch)",1,3,5,""),
  ("Beantown Buds","Red Sox · Topps 75 team insert",1,2,3,""),
 ],
 "Scan 399 — Topps 75 checkerboard/sunburst parallels + legends": [
  ("Kenedy Corona","Astros · Topps 75 checkerboard 'FL' parallel RC",1,2,3,""),
  ("Albert Pujols","Angels · Topps Heritage AL All-Stars, legend",1,3,5,""),
  ("Roberto Clemente","Pirates · Topps Heritage NL All-Stars, legend",2,5,8,""),
  ("Ryne Sandberg","Cubs · Topps 75, legend",1,3,5,""),
  ("Bubba Chandler","Pirates · baseballs insert RC (2nd copy — see Scan 394)",2,4,7,"DUPLICATE — same design as Scan 394 copy, confirm two real copies"),
  ("Vladimir Guerrero Jr.","Blue Jays · Titans of the Game insert",1,3,5,""),
  ("Spencer Torkelson","Tigers · Topps 75 sunburst gold parallel",1,2,4,""),
  ("Cole Young","Mariners · baseballs insert RC",1,3,5,""),
  ("Chicago Cubs","NL team celebration card",1,2,3,""),
 ],
 "Scan 403 — vintage tribute + Heritage parallels": [
  ("Honus Wagner","Pirates · Topps 75 vintage tribute, legend",2,5,9,""),
  ("Garrett Crochet","Red Sox · Topps Heritage pink sparkle parallel",1,3,5,""),
  ("Steve Smyth","Cubs · Topps Heritage RC (printed signature)",1,2,3,""),
  ("Liam Hicks","Marlins · Topps 75 crystal parallel RC",1,2,3,""),
  ("Sandy Koufax","Dodgers · '382 Strikeouts' insert, legend",2,5,9,""),
  ("Jahmai Jones","Tigers · Topps 75 crystal parallel",1,2,3,""),
  ("Drew Sommers","Tigers · Topps 75 crystal parallel RC",1,2,3,""),
  ("Nolan Ryan","Topps Heritage All-Star NL, legend",2,5,9,""),
  ("Jarren Duran","Red Sox · graffiti insert",1,2,4,""),
 ],
 "Scan 402 — vintage tribute + Chrome inserts": [
  ("Bobby Witt Jr.","Royals · Topps Chrome 'Terrors' insert",1,3,5,""),
  ("Corbin Carroll","Diamondbacks · Topps Heritage '35th Anniversary'",1,3,5,""),
  ("Bob Purkey","Pirates · Topps 75 vintage tribute, legend",1,3,5,""),
  ("Aaron Judge","Yankees · Topps Chrome '62 Home Runs' insert",2,4,7,""),
  ("Marion Fricano","Athletics · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Dave Jolly","Braves · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Juan Morillo","Diamondbacks · Topps Chrome auto RC #031/199",8,13,18,"real numbered autograph"),
  ("Clem Labine","Dodgers · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Johnny Logan","Braves · Topps 75 vintage tribute, legend",1,2,4,""),
 ],
 "Scan 404 — vintage tribute + gold sunburst parallels": [
  ("Camilo Pascual","Senators · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Cole Young","Mariners · graffiti insert RC (2nd design — see Scan 399)",1,3,5,""),
  ("Aaron Judge","Yankees · Topps '144 RBI' insert",2,4,7,""),
  ("Ben Wade","Dodgers · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Taylor Ward","Angels · Topps 75 gold sunburst parallel",1,2,4,"card prints Orioles/BAL — known print quirk, see reference_signature_class notes"),
  ("Sal Stewart","Reds · Topps 75 gold sunburst RC",1,3,6,""),
  ("Freddie Freeman","Dodgers · graffiti insert",1,3,5,""),
  ("Brooks Lee","Twins · Topps 75 Future Stars RC (different design from Scan 396 dupe)",1,2,4,""),
  ("Darell Hernaiz","Athletics · Topps Heritage sparkle parallel RC",1,2,4,""),
 ],
 "Scan 401 — mixed inserts + Heritage": [
  ("Vladimir Guerrero Jr.","Blue Jays · graffiti insert",1,3,5,""),
  ("Caden Dana","Angels · Topps Heritage RC",1,2,3,""),
  ("Karl Olson","Red Sox · Topps 75 vintage tribute, legend",1,2,4,""),
  ("Carlos Estevez / Robert Suarez","Leading Firemen combo insert",1,2,3,""),
  ("Reds 'All Smiles'","Team insert",1,2,3,""),
  ("David Bell","Mariners · Topps Heritage RC (printed signature)",1,2,3,""),
  ("Cal Raleigh","Mariners · Topps Heritage AL All-Stars (copy 2)",1,3,5,"DUPLICATE — see copy 1 in Scan 407"),
  ("Max Muncy","Athletics · Topps 75 Future Stars RC",1,2,3,""),
  ("Carlos Rodon","Yankees · Topps Chrome geometric parallel",1,2,4,""),
 ],
 "Scan 400 — Titans of the Game / Glove Work / team cards": [
  ("Yordan Alvarez","Astros · graffiti insert",1,3,5,""),
  ("Oneil Cruz","Pirates · Power Players insert",1,3,5,""),
  ("Aaron Sele","Mariners · Topps Heritage RC (printed signature)",1,2,3,""),
  ("James Wood","Nationals · Titans of the Game insert",2,4,6,""),
  ("Carl Yastrzemski","Red Sox · Glove Work insert, legend",2,4,7,""),
  ("Beantown Boys","Red Sox · team insert, gold parallel",1,2,4,""),
  ("Rafael Devers","Giants · Topps Chrome 'Night Terrors' insert",1,3,5,"uniform/team on card — eyeball before listing"),
  ("Mookie Betts","Dodgers · Titans of the Game insert",2,4,6,""),
  ("Tampa Bay Rays","Topps Heritage team photo card",1,2,3,""),
 ],
 "Scan 410 — mixed inserts + real autograph": [
  ("New York Yankees","Topps 75 All-Star Game team insert",1,2,3,""),
  ("Brady House","Nationals · graffiti insert RC",1,2,4,""),
  ("Bryce Eldridge","Giants · baseballs insert RC",2,4,7,""),
  ("Paul O'Neill","Yankees · Topps Certified Autograph Issue, legend",20,28,38,"real autograph, unnumbered base tier"),
  ("Byron Buxton","Twins · star insert",1,3,5,""),
  ("Chris Sale","Braves · Topps 75 crystal parallel",1,3,5,""),
  ("Jackson Merrill","Padres · graffiti insert (2nd design, see Scan 394)",1,3,5,""),
  ("Kazuma Okamoto","Blue Jays · Topps 75 crystal parallel RC",1,2,4,""),
  ("Reds 'All Smiles'","Team insert, crystal parallel (2nd design, see Scan 401)",1,2,3,""),
 ],
 "Scan 411 — partial page (2 cards)": [
  ("Jackson Chourio","Brewers · graffiti insert (2nd design, see Scan 409)",1,3,5,""),
  ("Steven Kwan","Guardians · Glove Work insert",1,3,5,""),
 ],
}

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2,textColor=BLACK)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=GRAY_MD,spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=BLACK,spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=GRAY_MD,spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12,textColor=BLACK)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

all_rows=[]
for grp_name,cards in GROUPS.items():
    for n,v,lo,ty,hi,nt in cards:
        all_rows.append({"group":grp_name,"card":n,"variant":v,"low":lo,"typical":ty,"high":hi,"note":nt})
tot=lambda k: round(sum(r[k] for r in all_rows),2)
grand={k:tot(k) for k in ("low","typical","high")}
Path("output/_baseball_batch_pricing.json").write_text(json.dumps(
 {"count":len(all_rows),"grand_total":grand,"cards":all_rows,"status":"HOLD - not posted, more scans pending",
  "basis":"raw/ungraded July 2026 eBay comp estimate; set/insert-tier pricing, not every card individually comp'd"},indent=1))

out=Path("docs/baseball_batch_pricing.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Baseball batch &mdash; sort &amp; pricing worksheet (HOLD)",h1),
      Paragraph(f"{len(all_rows)} cards &middot; Scans 391-411 &middot; raw/ungraded eBay-comp estimate &middot; NOT posted &mdash; more scans pending",sub),
      Paragraph(f"<b>Batch total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
                f"(typical ~{money(grand['typical'])})",grp),
      Paragraph("<b>Sort verdict: all lot material, with one exception.</b> Nothing else in this batch clears an "
                "individual-listing threshold on real comps &mdash; even hyped rookie/star names (Burns, Yesavage, "
                "Teel, Caissie, Schlittler, Basallo, Murakami, Skenes, Mayer, Eldridge) and HOF legends (Wagner, "
                "Koufax, Ryan, Clemente, Frank Thomas) are running $1-9 raw for these base/insert versions. Bundle "
                "by theme (rookies / veterans / legends / prospects) at 5 cards or fewer per lot. Three real "
                "numbered/certified autographs are worth pulling as singles: Roenis Elias II /45, Juan Morillo /199, "
                "and the Paul O'Neill Topps Certified Autograph (unnumbered but a real Yankees-legend auto, $20-38).",note)]

def tbl(grp_name,cards):
    flow.append(Paragraph(grp_name,grp))
    sub_ty=round(sum(c[3] for c in cards),2)
    data=[["", "Card", "Variant", "Low", "Typ", "High"]]
    for n,v,lo,ty,hi,nt in cards:
        cardcell=f"<b>{n}</b>"
        vv=v + (f" &middot; <i>{nt}</i>" if nt else "")
        data.append(["☐", Paragraph(cardcell,cardp), Paragraph(f"<font size=8.5>{vv}</font>",cardp),
                     money(lo),money(ty),money(hi)])
    data.append(["","",Paragraph("<b>scan typical</b>",cardp),"","",Paragraph(f"<b>{money(sub_ty)}</b>",cardp)])
    t=Table(data,colWidths=[0.28*inch,1.55*inch,3.15*inch,0.6*inch,0.6*inch,0.6*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),GRAY_DK),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[WHITE,GRAY_LT]),
        ("ALIGN",(3,0),(-1,-1),"RIGHT"),("ALIGN",(0,0),(0,-1),"CENTER"),("FONTSIZE",(0,1),(0,-1),13),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEABOVE",(0,-1),(-1,-1),0.6,GRAY_DK),
        ("GRID",(0,0),(-1,-2),.4,GRAY_MD),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
    flow.append(t)

for grp_name,cards in GROUPS.items(): tbl(grp_name,cards)
flow.append(Paragraph("How to read this: prices are RAW/ungraded July 2026 eBay-comp estimates (asks, sold runs a bit under). "
    "Most of this batch is common Topps/Panini base-insert parallels &mdash; the bulk is $1-4 even for name-brand "
    "rookies and stars. Flagged items worth a second look: the Mark McGwire Upper Deck 'Capture the Flag' vintage "
    "insert (Scan 394, older/different product than the rest); THREE apparent duplicate designs across this batch "
    "&mdash; Brooks Lee star insert (Scan 396, both copies), Cal Raleigh Topps Heritage AL All-Stars (Scans 407 &amp; "
    "401), and Bubba Chandler baseballs insert (Scans 394 &amp; 399) &mdash; confirm each is a real second physical "
    "copy and not an accidental re-scan; and two cards with team-print quirks to eyeball (Miguel Cabrera shows Giants "
    "on an Allen &amp; Ginter throwback, Taylor Ward prints Orioles/BAL, Rafael Devers shows Giants on a Chrome insert). "
    "HOLD: nothing posted, waiting on more scans before finalizing lot groupings.",note))
doc.build(flow)
dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)
print(f"{len(all_rows)} cards · total ${grand['low']:.0f}-{grand['high']:.0f} (typ ${grand['typical']:.0f})")
print(f"wrote {out} -> {dl}  + output/_baseball_batch_pricing.json")
