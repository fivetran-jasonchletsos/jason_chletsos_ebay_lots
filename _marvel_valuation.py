"""Value the scanned 2026 Topps Chrome Marvel Comics cards (63) — raw/ungraded
estimates. NOT for posting; personal valuation. Writes output/_marvel_valuation.json
and docs/marvel_valuation.pdf (+ ~/Downloads copy)."""
import json, shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

# (character, type, extra)  type: base|refractor|insert|numbered
CARDS = [
 # --- base ---
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
 # --- refractor ---
 ("Tombstone","refractor",""),("Domino","refractor",""),("She-Venom","refractor",""),("Beast","refractor",""),
 ("Dazzler","refractor",""),("Leader","refractor",""),("Ant-Man","refractor",""),("Spider-Man Noir","refractor",""),
 # --- inserts ---
 ("Human Torch","insert","65 Fantastic Years"),("Invisible Woman","insert","65 Fantastic Years"),
 ("Doctor Doom","insert","One World Under Doom"),("Black Panther","insert","The Beyond"),
 ("Ghost Rider","insert","Meanwhile..."),
 # --- numbered parallel ---
 ("Elbecca Voss","numbered","Purple /99 + 1st appearance"),
]

# Top-tier characters that carry a premium at every rarity.
TOP = {"venom","she-venom","spider-man noir","spider-punk","spider-woman","spider-boy","thanos","galactus",
       "doctor doom","black panther","x-23","ghost rider","captain america","thor","toxin","scream","mystique","beast"}
def top(name): return name.strip().lower() in TOP

def price(name, typ, extra):
    t = top(name)
    if typ == "numbered":            # Elbecca Voss purple /99, minor 1st-app character
        return (10, 17, 28)
    if typ == "insert":
        return (3, 4, 6) if ("Doom" in extra or "Beyond" in extra) else (2, 3.25, 5)
    if typ == "refractor":
        return (3, 5, 9) if t else (1.5, 2.75, 5)
    # base
    return (0.90, 1.75, 3.0) if t else (0.35, 0.65, 1.25)

rows = []
for name, typ, extra in CARDS:
    lo, ty, hi = price(name, typ, extra)
    rows.append({"character": name, "type": typ, "extra": extra, "low": lo, "typical": ty, "high": hi})

def tot(k): return round(sum(r[k] for r in rows), 2)
totals = {k: tot(k) for k in ("low","typical","high")}
by_type = {}
for r in rows:
    b = by_type.setdefault(r["type"], {"n":0,"low":0,"typical":0,"high":0})
    b["n"]+=1
    for k in ("low","typical","high"): b[k]=round(b[k]+r[k],2)

Path("output/_marvel_valuation.json").write_text(json.dumps(
    {"set":"2026 Topps Chrome Marvel Comics","count":len(rows),"cards":rows,
     "totals":totals,"by_type":by_type,"basis":"raw/ungraded eBay estimate 2026-07-12; new set, net below active asks"}, indent=1))

# ---- console summary ----
print(f"2026 Topps Chrome Marvel Comics — {len(rows)} cards")
for t in ("numbered","insert","refractor","base"):
    b=by_type.get(t);
    if b: print(f"  {t:9} x{b['n']:<2}  ${b['low']:.2f} - ${b['high']:.2f}  (typ ${b['typical']:.2f})")
print(f"  TOTAL raw estimate: ${totals['low']:.2f} - ${totals['high']:.2f}  (typical ${totals['typical']:.2f})")

# ---- PDF ----
styles=getSampleStyleSheet()
h1=ParagraphStyle("h1",parent=styles["Title"],fontSize=20,spaceAfter=2)
sub=ParagraphStyle("sub",parent=styles["Normal"],fontSize=9.5,textColor=colors.HexColor("#6b7280"),spaceAfter=12)
grp=ParagraphStyle("grp",parent=styles["Heading2"],fontSize=13,textColor=colors.HexColor("#0B2265"),spaceBefore=12,spaceAfter=4)
note=ParagraphStyle("note",parent=styles["Normal"],fontSize=9,textColor=colors.HexColor("#6b7280"),spaceBefore=8)
out=Path("docs/marvel_valuation.pdf")
doc=SimpleDocTemplate(str(out),pagesize=letter,topMargin=.6*inch,bottomMargin=.6*inch,leftMargin=.6*inch,rightMargin=.6*inch)
flow=[Paragraph("Marvel Chrome — card valuation",h1),
      Paragraph(f"2026 Topps Chrome Marvel Comics &middot; {len(rows)} cards &middot; raw/ungraded estimate &middot; NOT for sale",sub),
      Paragraph(f"<b>Estimated total: ${totals['low']:.0f} &ndash; ${totals['high']:.0f}</b> (typical ~${totals['typical']:.0f})",grp)]

def tbl(title, items, showtype=True):
    flow.append(Paragraph(title,grp))
    head=["Card","Detail","Low","Typ","High"]
    data=[head]+[[r["character"], (r["extra"] or r["type"].title()), f"${r['low']:.2f}", f"${r['typical']:.2f}", f"${r['high']:.2f}"] for r in items]
    t=Table(data,colWidths=[2.0*inch,2.4*inch,.8*inch,.8*inch,.8*inch])
    t.setStyle(TableStyle([
        ("FONTSIZE",(0,0),(-1,-1),9),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
        ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#0B2265")),("TEXTCOLOR",(0,0),(-1,0),colors.white),
        ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f2f6ff")]),
        ("ALIGN",(2,0),(-1,-1),"RIGHT"),("GRID",(0,0),(-1,-1),.4,colors.HexColor("#d5dae3")),
        ("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
    flow.append(t)

hits=[r for r in rows if r["type"] in ("numbered","insert","refractor")]
tbl(f"The value cards ({len(hits)}) — sell these as singles", hits)
base=[r for r in rows if r["type"]=="base"]
tbl(f"Base cards ({len(base)}) — mostly bulk; better as a lot", base)
flow.append(Paragraph("Basis: raw/ungraded eBay estimate pulled 2026-07-12. This set is ~11 days old, so "
    "prices are soft and still settling; net sold prices run below current asking prices, so treat the "
    "typical column as realistic and the low column as quick-sale. The 49 base cards are essentially bulk "
    "(often better sold as a single lot than one-by-one). Real value sits in the numbered Elbecca Voss "
    "(purple /99, 1st appearance), the inserts, and the refractors. Not for sale &mdash; valuation only.",note))
doc.build(flow)
dl=Path.home()/"Downloads"/"marvel_valuation.pdf"; shutil.copy(out,dl)
print(f"\nwrote {out} -> {dl}")
print(f"wrote output/_marvel_valuation.json")
