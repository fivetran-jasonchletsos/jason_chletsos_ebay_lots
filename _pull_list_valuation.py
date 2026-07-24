"""Pull-list valuation for Scans 330-334 (36 cards, 2025 Prizm FB + Topps 75 BB).
Raw/ungraded July 2026 eBay-sold estimates (from 3-agent comp research).
Organized BY SCAN with checkboxes so JC can pull + check off physically.
Writes docs/pull_list_valuation.pdf (+ ~/Downloads) and output/_pull_list_valuation.json.
NOT for posting — valuation only.
"""
import json, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# (name, variant, low, typical, high, note)
SCANS = {
 "Scan 334 — Football (Prizm)": [
  ("Caleb Williams","Bears · Prizm base",2,4,7,""),
  ("Will Howard","Steelers · Prizm base · RC",1,2,4,""),
  ("Kalel Mullings","Titans · Prizm Lazer · RC",1,2,3,""),
  ("Travis Hunter","Jaguars · Prizm EMERGENT insert · RC",1,2,4,"common insert"),
  ("Najee Harris","Chargers · Prizm Lazer",1,2,4,""),
 ],
 "Scan 333 — Football (Prizm)": [
  ("Travis Hunter","Jaguars · Prizm Lazer · RC",6,10,18,"TOP card of the batch"),
  ("Jayden Daniels","Commanders · Prizm base",3,6,10,"best base value"),
  ("Patrick Mahomes II","Chiefs · Prizm FRACTAL insert",2,4,8,""),
  ("Jaxon Smith-Njigba","Seahawks · Prizm Lazer",2,4,7,""),
  ("TreVeyon Henderson","Patriots · Prizm Lazer · RC",2,4,8,""),
  ("Dan Fouts","Chargers · Prizm Lazer · legend",2,3,5,""),
  ("Ricky Williams","Prizm Lazer · legend",2,3,5,"card prints Ravens — eyeball"),
  ("Omarion Hampton","Chargers · Prizm PRIZMATIC insert · RC",1,2,4,"common insert"),
  ("Tyleik Williams","Lions · Prizm Lazer · RC",1,2,3,""),
 ],
 "Scan 332 — Football (Prizm)": [
  ("C.J. Stroud","Texans · Prizm PREMIER relic (red swatch)",6,11,18,"TOP card — confirm not #'d"),
  ("Luther Burden III","Bears · Prizm ROOKIE GEAR relic · RC",3,6,11,"confirm not #'d"),
  ("Jalon Walker","Falcons · Prizm ROOKIE GEAR relic · RC",3,6,10,"confirm not #'d"),
  ("Jalen Royals","Chiefs · Prizm Lazer · RC",1,3,5,""),
  ("Sam Darnold","Seahawks · Prizm Lazer",1,2,4,""),
  ("Khalil Shakir","Bills · Prizm Lazer",1,2,4,""),
  ("Dwight Freeney","Colts · Prizm Lazer · legend",1,2,4,""),
  ("Terrell Suggs","Ravens · Prizm Lazer · legend",1,2,4,""),
  ("Carson Schwesinger","Browns · Prizm Lazer · RC",1,2,3,""),
 ],
 "Scan 331 — Baseball (Topps 75)": [
  ("Jarren Duran","Red Sox · Topps art card",2,3,5,""),
  ("Beantown Buds (Duran/Story)","Red Sox · Topps 75 combo",1,3,5,""),
  ("Sal Stewart","Reds · Topps 75 Gold/Sun · RC",1,2,4,""),
  ("Jahmai Jones","Tigers · Topps 75 City Connect sparkle",1,2,3,""),
 ],
 "Scan 330 — Baseball (Topps 75)": [
  ("Aaron Judge","Yankees · Topps 144 RBI insert",2,4,7,""),
  ("Freddie Freeman","Dodgers · Topps art card",2,4,6,""),
  ("Albert Pujols","Angels · Topps 75 All-Star AL",1,3,5,""),
  ("Cole Young","Mariners · Topps art card · RC",2,3,6,""),
  ("Bubba Chandler","Pirates · Topps base · RC",1,3,5,"top pitching prospect"),
  ("Cole Young","Mariners · Topps base · RC",1,2,4,"2nd Cole Young"),
  ("Spencer Torkelson","Tigers · Topps 75 Gold/Sun",1,2,4,""),
  ("Taylor Ward","Topps 75 Gold/Sun",1,2,4,"card prints Orioles/BAL — eyeball"),
  ("Brooks Lee","Twins · Topps 75 Future Stars",1,2,3,""),
 ],
}

st=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=st["Title"],fontSize=21,spaceAfter=2)
sub=ParagraphStyle("sub",parent=st["Normal"],fontSize=9.5,textColor=colors.HexColor("#6b7280"),spaceAfter=10)
grp=ParagraphStyle("grp",parent=st["Heading2"],fontSize=12.5,textColor=colors.HexColor("#0B2265"),spaceBefore=11,spaceAfter=4)
note=ParagraphStyle("note",parent=st["Normal"],fontSize=8.5,textColor=colors.HexColor("#6b7280"),spaceBefore=8)
cardp=ParagraphStyle("cardp",parent=st["Normal"],fontSize=10,leading=12)

def money(x): return f"${x:,.2f}" if x%1 else f"${int(x)}"

# ---- totals + json ----
all_rows=[]
for scan,cards in SCANS.items():
    for n,v,lo,ty,hi,nt in cards:
        all_rows.append({"scan":scan,"card":n,"variant":v,"low":lo,"typical":ty,"high":hi,"note":nt})
tot=lambda k: round(sum(r[k] for r in all_rows),2)
grand={k:tot(k) for k in ("low","typical","high")}
Path("output/_pull_list_valuation.json").write_text(json.dumps(
 {"count":len(all_rows),"grand_total":grand,"cards":all_rows,
  "basis":"raw/ungraded July 2026 eBay-sold estimate; 3-agent comp research; Lazer=common blaster parallel (tiny premium over base)"},indent=1))

# ---- pdf ----
out=Path("docs/pull_list_valuation.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Pull list &amp; valuation &mdash; Scans 330-334",h1),
      Paragraph(f"{len(all_rows)} cards &middot; raw/ungraded eBay-sold estimate (Jul 2026) &middot; NOT for sale",sub),
      Paragraph(f"<b>Batch total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
                f"(typical ~{money(grand['typical'])})",grp)]

def tbl(scan,cards):
    flow.append(Paragraph(scan,grp))
    sub_ty=round(sum(c[3] for c in cards),2)
    data=[["", "Card", "Variant", "Low", "Typ", "High"]]
    for n,v,lo,ty,hi,nt in cards:
        cardcell=f"<b>{n}</b>"
        vv=v + (f" <font color='#b45309'>· {nt}</font>" if nt else "")
        data.append(["☐", Paragraph(cardcell,cardp), Paragraph(f"<font size=8.5 color='#555'>{vv}</font>",cardp),
                     money(lo),money(ty),money(hi)])
    data.append(["","",Paragraph("<b>scan typical</b>",cardp),"","",Paragraph(f"<b>{money(sub_ty)}</b>",cardp)])
    t=Table(data,colWidths=[0.28*inch,1.7*inch,3.0*inch,0.6*inch,0.6*inch,0.6*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0B2265")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[colors.white,colors.HexColor("#f2f6ff")]),
        ("ALIGN",(3,0),(-1,-1),"RIGHT"),("ALIGN",(0,0),(0,-1),"CENTER"),("FONTSIZE",(0,1),(0,-1),13),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEABOVE",(0,-1),(-1,-1),0.6,colors.HexColor("#0B2265")),
        ("GRID",(0,0),(-1,-2),.4,colors.HexColor("#d5dae3")),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
    flow.append(t)

for scan,cards in SCANS.items(): tbl(scan,cards)
flow.append(Paragraph("How to read this: prices are RAW/ungraded July 2026 eBay-SOLD estimates (sold, not asking &mdash; asks run higher). "
    "Most 2025 Prizm base and <b>Lazer</b> cards are common blaster-box parallels, so Lazer carries only a tiny premium over base &mdash; "
    "the bulk of the batch is $1-4. The real value sits in a few cards: <b>Travis Hunter Lazer RC</b> and the <b>C.J. Stroud Premier relic</b> "
    "(both up to ~$18), the <b>Rookie Gear relics</b> (Burden, Walker), and <b>Jayden Daniels</b>. "
    "Before pricing the three relic/swatch cards as base, confirm none are serial-numbered &mdash; a #'d version is worth materially more. "
    "The Ricky Williams (Ravens) and Taylor Ward (BAL/Orioles) cards print teams the players aren't on &mdash; eyeball them. Valuation only, nothing posted.",note))
doc.build(flow)
dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)
print(f"{len(all_rows)} cards · total ${grand['low']:.0f}-{grand['high']:.0f} (typ ${grand['typical']:.0f})")
print(f"wrote {out} -> {dl}  + output/_pull_list_valuation.json")
