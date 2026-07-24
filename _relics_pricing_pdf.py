"""Relics batch valuation for the physical relic-card layout photo (2026-07-19).
Raw/ungraded July 2026 eBay-comp estimates. Black-and-white / grayscale print.
Writes docs/relics_pricing.pdf (+ ~/Downloads) and output/_relics_pricing.json.
NOT for posting — valuation only.
"""
import json, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

GRAY_DK = colors.HexColor("#222222")
GRAY_MD = colors.HexColor("#555555")
GRAY_LT = colors.HexColor("#e8e8e8")
BLACK = colors.black
WHITE = colors.white

# (name, variant, low, typ, high, note)
GROUPS = {
 "Confirmed — Select / Score / Contenders / Threads relics": [
  ("Tetairoa McMillan","Panthers · Select Draft Selections RC relic",9,12,15,""),
  ("Justin Herbert","Chargers · Totally Certified Piece of the Game relic",4,12,17,"wide range by parallel — confirm exact one"),
  ("Colston Loveland","Bears · Select RC jersey patch (copy 1)",8,10,15,""),
  ("Colston Loveland","Bears · Select RC jersey patch (copy 2, diff color)",8,10,15,""),
  ("Omarion Hampton","Chargers · Select Draft Selections RC relic",5,7,9,""),
  ("Kaleb Johnson","Steelers · Donruss Optic Phenom RC jersey relic",3,8,12,""),
  ("Christian McCaffrey","49ers · Score Stars of the NFL jersey relic",4,7,10,""),
  ("Lamar Jackson","Ravens · Score Stars of the NFL jersey relic",4,7,13,""),
  ("James Conner","Cardinals · jersey relic (confirm exact insert)",6,10,17,"multiple Conner relic products exist — verify set from card back"),
  ("Bryce Young","Panthers · Donruss Threads RC jersey relic",3,4,5,""),
  ("Tyrion Davis-Price","49ers · Contenders Rookie Ticket jersey relic",3,4,5,""),
  ("Kellen Clemens","Jets · Leaf Rookies & Stars Crusade jersey relic",2,3,3,""),
  ("Jalen Royals","Chiefs · Select RC jersey patch (copy 1)",3,5,6,""),
  ("Jalen Royals","Chiefs · Select RC jersey patch (copy 2, diff color)",3,5,6,""),
  ("Tai Felton","Vikings · Select Rookie Swatches RC patch",2,4,5,""),
  ("Mason Graham","Browns · Select RC jersey patch",2,4,6,""),
  ("Travis Hunter","Jaguars · Select relic",8,12,18,"Hunter carries a premium over set-mates — confirm exact parallel"),
  ("Laiatu Latu","New Generation jersey relic RC",3,4,6,"no direct comp found — priced off comparable rookie relic tier"),
 ],
 "Confirmed — Select Multiverse dual-jersey relics": [
  ("Joe Mixon","Texans/Bengals · Multiverse dual jersey",3,8,18,""),
  ("Marquise Brown / Rico Dowdle","Multiverse dual jersey",1,4,10,"priced off Dowdle solo comps"),
  ("Stefon Diggs / Evan Engram","Multiverse dual jersey",4,8,15,"priced off Engram solo comps"),
  ("Brandin Cooks / Tony Pollard","Multiverse dual jersey",2,8,20,"priced off Pollard solo comps"),
  ("Bobby Wagner / Christian Wilkins","Multiverse dual jersey",1,2,3,"priced off Wilkins solo comps"),
 ],
 "Needs name confirmed — top-section Rookie Gear / Premier / First Year Fresh": [
  ("Unconfirmed RC #1-3","Prizm Rookie Gear-style, cog bg, QB pose, colored patch (navy/navy/red)",3,6,11,"pattern-matches known Rookie Gear tier (Burden/Walker comp'd $3-11) — confirm names off card fronts"),
  ("Unconfirmed RC #4-6","Prizm PREMIER-style relic, red/blue/navy patches",6,11,18,"pattern-matches known Premier tier (Stroud/Allen/Cook comp'd $6-18) — confirm names"),
  ("Unconfirmed single","Dark navy card, gold patch, jersey #1",2,5,9,"team colors suggest Ravens — confirm player"),
  ("Unconfirmed RC #7-10","Donruss Optic 'First Year Fresh' relic, 4 cards, QB poses",2,6,13,"same insert as Mason Taylor ($3.99) already in inventory — confirm remaining 3 names"),
  ("Unconfirmed RC #11-12","Donruss Optic 'Phenom' relic (2 more besides Kaleb Johnson)",3,8,12,"same insert tier as Kaleb Johnson/Omarion Hampton Phenom already priced"),
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
Path("output/_relics_pricing.json").write_text(json.dumps(
 {"count":len(all_rows),"grand_total":grand,"cards":all_rows,
  "basis":"raw/ungraded July 2026 eBay comp estimate; several top-section names unconfirmed pending visual verification"},indent=1))

out=Path("docs/relics_pricing.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.55*inch,bottomMargin=.55*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Relics batch &mdash; pricing worksheet",h1),
      Paragraph(f"{len(all_rows)} cards &middot; raw/ungraded July 2026 eBay-comp estimate &middot; NOT for sale",sub),
      Paragraph(f"<b>Batch total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
                f"(typical ~{money(grand['typical'])})",grp)]

def tbl(grp_name,cards):
    flow.append(Paragraph(grp_name,grp))
    sub_ty=round(sum(c[3] for c in cards),2)
    data=[["", "Card", "Variant", "Low", "Typ", "High"]]
    for n,v,lo,ty,hi,nt in cards:
        cardcell=f"<b>{n}</b>"
        vv=v + (f" &middot; <i>{nt}</i>" if nt else "")
        data.append(["☐", Paragraph(cardcell,cardp), Paragraph(f"<font size=8.5>{vv}</font>",cardp),
                     money(lo),money(ty),money(hi)])
    data.append(["","",Paragraph("<b>group typical</b>",cardp),"","",Paragraph(f"<b>{money(sub_ty)}</b>",cardp)])
    t=Table(data,colWidths=[0.28*inch,1.55*inch,3.15*inch,0.6*inch,0.6*inch,0.6*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),GRAY_DK),("TEXTCOLOR",(0,0),(-1,0),WHITE),
        ("ROWBACKGROUNDS",(0,1),(-1,-2),[WHITE,GRAY_LT]),
        ("ALIGN",(3,0),(-1,-1),"RIGHT"),("ALIGN",(0,0),(0,-1),"CENTER"),("FONTSIZE",(0,1),(0,-1),13),
        ("VALIGN",(0,0),(-1,-1),"MIDDLE"),("LINEABOVE",(0,-1),(-1,-1),0.6,GRAY_DK),
        ("GRID",(0,0),(-1,-2),.4,GRAY_MD),("TOPPADDING",(0,0),(-1,-1),3.5),("BOTTOMPADDING",(0,0),(-1,-1),3.5)]))
    flow.append(t)

for grp_name,cards in GROUPS.items(): tbl(grp_name,cards)
flow.append(Paragraph("How to read this: prices are RAW/ungraded July 2026 eBay comp estimates (mostly active/OBO asks, sold will run a bit under). "
    "Justin Herbert, Travis Hunter, and James Conner carry wider ranges since exact parallel/insert wasn't confirmed from the photo &mdash; check the card back before listing. "
    "The bottom section is priced off the SAME insert tiers already confirmed elsewhere on this sheet (Rookie Gear, Premier, First Year Fresh, Phenom) "
    "but the specific player names weren't legible enough in the photo to state with confidence &mdash; read the card fronts and swap in exact names/comps before finalizing. "
    "Note: the four grouped rows above (RC #1-3, #4-6, #7-10, #11-12) each price MULTIPLE physical cards as a single line, so the card count and grand total on this sheet are a floor, not the true batch total &mdash; do not treat them as final until each card is itemized individually. "
    "Valuation only, nothing posted.",note))
doc.build(flow)
dl=Path.home()/"Downloads"/out.name; shutil.copy(out,dl)
print(f"{len(all_rows)} cards · total ${grand['low']:.0f}-{grand['high']:.0f} (typ ${grand['typical']:.0f})")
print(f"wrote {out} -> {dl}  + output/_relics_pricing.json")
