"""Value the scanned Marvel cards (two sets) — raw/ungraded estimates.
NOT for posting; personal valuation. Writes output/_marvel_valuation.json and
docs/marvel_valuation.pdf (+ ~/Downloads copy).

Set 1: 2026 Topps Chrome Marvel Comics (63 cards)
Set 2: 2022 Upper Deck Marvel Beginnings Vol. 2 (45 cards)
"""
import json, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# ===================== SET 1 — Topps Chrome Marvel =====================
CHROME = [
 ("White Tiger","base",""),("Hobgoblin","base",""),("Venom","base",""),("Shang-Chi","base",""),
 ("Apocalypse","base",""),("Mister Sinister","base",""),("Wasp","base",""),("Shuri","base",""),("Dormammu","base",""),
 ("Galactus","base",""),("Spider-Punk","base",""),("Spider-Woman","base",""),("Thanos","base",""),("Daredevil","base",""),
 ("Elektra","base",""),("Blade","base",""),("Mystique","base",""),("Moon Knight","base",""),
 ("U.S. Agent","base",""),("Black Cat","base",""),("Groot","base",""),("X-23","base",""),("Psylocke","base",""),
 ("Longshot","base",""),("Jean Grey","base",""),("Scream","base",""),
 ("Ikaris","base",""),("She-Hulk","base",""),("Mysterio","base",""),("Ms. Marvel","base",""),("Jubilee","base",""),("Ironheart","base",""),
 ("Chameleon","base",""),("Captain America","base",""),("Kid Juggernaut","base",""),("Dragonfire","base","1st appearance"),
 ("Toxin","base",""),("Rek-Rap","base",""),("Spider-Boy","base",""),("Vulture","base",""),
 ("Raelith","base","1st appearance"),("Rhino","base",""),("Doyle Dormammu","base",""),("Hellgate","base","1st appearance"),
 ("White Fox","base",""),("Glob","base",""),("Mister Fantastic","base",""),("Thor","base",""),("Devil Dinosaur","base",""),
 ("Tombstone","refractor",""),("Domino","refractor",""),("She-Venom","refractor",""),("Beast","refractor",""),
 ("Dazzler","refractor",""),("Leader","refractor",""),("Ant-Man","refractor",""),("Spider-Man Noir","refractor",""),
 ("Human Torch","insert","65 Fantastic Years"),("Invisible Woman","insert","65 Fantastic Years"),
 ("Doctor Doom","insert","One World Under Doom"),("Black Panther","insert","The Beyond"),("Ghost Rider","insert","Meanwhile..."),
 ("Elbecca Voss","numbered","Purple /99 + 1st appearance"),
]
CHROME_TOP = {"venom","she-venom","spider-man noir","spider-punk","spider-woman","spider-boy","thanos","galactus",
       "doctor doom","black panther","x-23","ghost rider","captain america","thor","toxin","scream","mystique","beast"}
def price_chrome(name, typ, extra):
    t = name.strip().lower() in CHROME_TOP
    if typ == "numbered":   return (10, 17, 28)
    if typ == "insert":     return (3,4,6) if ("Doom" in extra or "Beyond" in extra) else (2,3.25,5)
    if typ == "refractor":  return (3,5,9) if t else (1.5,2.75,5)
    return (0.90,1.75,3.0) if t else (0.35,0.65,1.25)

# ===================== SET 2 — UD Marvel Beginnings Vol.2 =====================
# base cards are a flat ~$1-2 regardless of character; red starburst = Red Supernova.
BEGIN = [
 ("Wave","red",""),("Proteus","base",""),("The Maker","base",""),("The Human Torch","red",""),
 ("Team Formations","insert","Thor Corps"),("Echo","base",""),("Gorilla Girl","red",""),("Colleen Wing","base",""),("Gorgon","base",""),
 ("The Hood","base",""),("Ulik","base",""),("Green Goblin","base",""),("Deep Lore","insert","Weapon Plus (Nuke)"),
 ("Johnny Watts","base",""),("Mister Fantastic","base",""),("Griffin","base",""),("Pepper Potts","base",""),("Dazzler","base",""),
 ("Blade","base",""),("Jubilee","base",""),("Uatu the Watcher","base",""),("Silver Samurai","base",""),
 ("Cosmic Alpha","insert","Mjolnir (die-cut)"),("Profile","base",""),("Eimin","base",""),("Chameleon","base",""),("Mariko Yashida","base",""),
 ("Cassandra Romulus","base",""),("Nightshade","base",""),("Stingray","base",""),("Blastaar","base",""),("Professor X","base",""),
 ("Bats","base",""),("Mary Jane Watson","base",""),("Slingshot","base",""),("Deep Lore","insert","Weapon Plus (Iron Fist)"),
 ("Callisto","base",""),("Team Formations","insert","Wrecking Crew"),("Husk","base",""),("Rogue","base",""),("Enchantress","base",""),
 ("Spot","base",""),("A Point in Time","insert","Black Widow"),("Jack O'Lantern","base",""),("Arcade","base",""),
]
def price_begin(name, typ, extra):
    if typ == "red":    return (2, 3.5, 5)      # Red Supernova, non-headliner
    if typ == "insert": return (1, 2, 3.5)
    return (0.75, 1.25, 2.0)                    # base, character-flat

# ===================== compute =====================
def build(cards, pricer):
    out=[]
    for name,typ,extra in cards:
        lo,ty,hi=pricer(name,typ,extra)
        out.append({"character":name,"type":typ,"extra":extra,"low":lo,"typical":ty,"high":hi})
    return out
chrome=build(CHROME, price_chrome)
begin=build(BEGIN, price_begin)
def sub(rows,k): return round(sum(r[k] for r in rows),2)
def totals(rows): return {k:sub(rows,k) for k in ("low","typical","high")}
grand={k:round(totals(chrome)[k]+totals(begin)[k],2) for k in ("low","typical","high")}

Path("output/_marvel_valuation.json").write_text(json.dumps({
    "sets":[{"name":"2026 Topps Chrome Marvel Comics","count":len(chrome),"cards":chrome,"totals":totals(chrome)},
            {"name":"2022 Upper Deck Marvel Beginnings Vol.2","count":len(begin),"cards":begin,"totals":totals(begin)}],
    "grand_total":grand,"count":len(chrome)+len(begin),
    "basis":"raw/ungraded eBay estimate 2026-07-13; both sets trade thin/soft, net below active asks"}, indent=1))

print(f"Topps Chrome Marvel: {len(chrome)} -> ${totals(chrome)['low']:.0f}-{totals(chrome)['high']:.0f} (typ ${totals(chrome)['typical']:.0f})")
print(f"UD Marvel Beginnings: {len(begin)} -> ${totals(begin)['low']:.0f}-{totals(begin)['high']:.0f} (typ ${totals(begin)['typical']:.0f})")
print(f"GRAND ({len(chrome)+len(begin)} cards): ${grand['low']:.0f} - ${grand['high']:.0f} (typ ${grand['typical']:.0f})")

# ===================== PDF =====================
styles=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=styles["Title"],fontSize=20,spaceAfter=2)
subp=ParagraphStyle("sub",parent=styles["Normal"],fontSize=9.5,textColor=colors.HexColor("#6b7280"),spaceAfter=10)
grp=ParagraphStyle("grp",parent=styles["Heading2"],fontSize=13,textColor=colors.HexColor("#0B2265"),spaceBefore=12,spaceAfter=4)
note=ParagraphStyle("note",parent=styles["Normal"],fontSize=9,textColor=colors.HexColor("#6b7280"),spaceBefore=8)
out=Path("docs/marvel_valuation.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.6*inch,bottomMargin=.6*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Marvel cards — valuation",h1),
      Paragraph(f"{len(chrome)+len(begin)} cards across 2 sets &middot; raw/ungraded estimate &middot; NOT for sale",subp),
      Paragraph(f"<b>Grand total: ${grand['low']:.0f} &ndash; ${grand['high']:.0f}</b> (typical ~${grand['typical']:.0f})",grp)]
def tbl(title, items):
    flow.append(Paragraph(title,grp))
    data=[["Card","Detail","Low","Typ","High"]]+[[r["character"],(r["extra"] or r["type"].title()),f"${r['low']:.2f}",f"${r['typical']:.2f}",f"${r['high']:.2f}"] for r in items]
    t=Table(data,colWidths=[2.0*inch,2.4*inch,.8*inch,.8*inch,.8*inch])
    t.setStyle(TableStyle([("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0B2265")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f2f6ff")]),("ALIGN",(2,0),(-1,-1),"RIGHT"),
        ("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d5dae3")),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    flow.append(t)

flow.append(Paragraph(f"SET 1 &mdash; 2026 Topps Chrome Marvel Comics ({len(chrome)}) &middot; ${totals(chrome)['low']:.0f}-{totals(chrome)['high']:.0f}",grp))
tbl("Value cards (sell as singles)", [r for r in chrome if r["type"] in ("numbered","insert","refractor")])
tbl("Base cards (mostly bulk / lot)", [r for r in chrome if r["type"]=="base"])
flow.append(Paragraph(f"SET 2 &mdash; 2022 Upper Deck Marvel Beginnings Vol.2 ({len(begin)}) &middot; ${totals(begin)['low']:.0f}-{totals(begin)['high']:.0f}",grp))
tbl("Parallels &amp; inserts (the better cards)", [r for r in begin if r["type"] in ("red","insert")])
tbl("Base cards (flat ~$1-2; lot them)", [r for r in begin if r["type"]=="base"])
flow.append(Paragraph("Basis: raw/ungraded eBay estimates pulled 2026-07-13 from active asking prices (true sold prices run "
    "below asks). The Topps Chrome set is ~2 weeks old so prices are still settling. In BOTH sets the base cards are "
    "essentially bulk (better sold as lots than one-by-one). The real value sits in: Topps Chrome &mdash; the numbered "
    "Elbecca Voss /99 (1st appearance), the inserts, and the refractors; Marvel Beginnings &mdash; the three Red Supernova "
    "parallels and the die-cut/insert cards. Note: in Marvel Beginnings the base price is flat regardless of character; "
    "character premium only shows on scarce NUMBERED parallels (none numbered here). Not for sale &mdash; valuation only.",note))
doc.build(flow)
dl=Path.home()/"Downloads"/"marvel_valuation.pdf"; shutil.copy(out,dl)
print(f"wrote {out} -> {dl}  + output/_marvel_valuation.json")
