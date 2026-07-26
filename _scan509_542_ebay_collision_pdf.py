"""Scans 509-542 — eBay collision check + posting candidates (2026-07-26).

JC suspected already-listed cards got physically mixed into this 34-scan batch
(~303 cards); the tell was a Mason Graham Phoenix /385 RC found loose while its
listing is live. A 5-agent transcription pass + title cross-reference against
output/listings_snapshot.json confirmed it at scale: 118 of the 303 cards match
a live listing at high confidence (player + insert name, or player + brand +
parallel color), concentrated in the 307043xxx/307044xxx/307046xxx/307051xxx
posting batches — i.e. whole previously-posted batches were shuffled back in.
Those cards' live listings total ~$710; selling or lotting them twice is an
oversell. Data: output/_scan509_542_collisions.json (+ /tmp/scan_catalog_*.json).

Section 1: collision checklist (set these aside into the "listed" boxes).
Section 2: posting candidates from the 154 clean modern cards (est. > ~$4).
Remainder: ~110 modern commons -> lot material; 31 vintage/junk-wax -> bulk.

Writes docs/scan509_542_collision_check.pdf (+ ~/Downloads) and
output/_scan509_542_collisions.json.
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

collisions = json.load(open('/tmp/collisions_best.json'))
Path("output/_scan509_542_collisions.json").write_text(json.dumps(
    {"count": len(collisions),
     "live_value": round(sum(float(m['price'] or 0) for m in collisions), 2),
     "collisions": collisions,
     "basis": "player + insert-name or player + brand + parallel-color title match vs "
              "output/listings_snapshot.json 2026-07-26; base cards without a distinctive "
              "insert/color could NOT be checked this way and may hide more collisions"},
    indent=1))

# ---- posting candidates from the clean/unmatched modern pile ----
# (last-sort-key, player, desc, scan, pos, low, typ, high, note)
CANDIDATES = [
 ("Aikman", "Troy Aikman", "Topps Chrome Legends of the Gridiron", 521, 1, 4, 6, 9, "Cowboys legend"),
 ("Allen (1)", "Josh Allen", "Panini Prizm base", 517, 3, 4, 6, 9, ""),
 ("Allen (2)", "Josh Allen", "Topps Chrome All-Chrome insert", 526, 5, 4, 6, 9, ""),
 ("Bowers (1)", "Brock Bowers", "Donruss Optic stars border", 514, 9, 4, 5, 8, ""),
 ("Bowers (2)", "Brock Bowers", "Panini Revolution", 516, 5, 4, 5, 8, ""),
 ("Bowers (3)", "Brock Bowers", "Panini Prizm base", 520, 8, 4, 5, 8, ""),
 ("Bowers (4)", "Brock Bowers", "Select Flash multicolor RC", 532, 9, 4, 6, 9, ""),
 ("Burrow (1)", "Joe Burrow", "Panini Prizm base", 532, 7, 4, 6, 9, ""),
 ("Burrow (2)", "Joe Burrow", "Topps IC Sunday Showcase", 527, 8, 4, 6, 9, ""),
 ("Burrow (3)", "Joe Burrow", "2020 Leaf Draft First Overall", 534, 8, 3, 5, 8, "draft-year issue"),
 ("Campbell", "Earl Campbell", "Mosaic Hall of Fame", 521, 3, 3, 5, 7, "HOF legend"),
 ("Chase", "Ja'Marr Chase", "Topps Chrome Power Players", 536, 1, 4, 6, 9, ""),
 ("Daniels", "Jayden Daniels", "Panini Mosaic base", 522, 4, 4, 6, 9, ""),
 ("Gibbs (1)", "Jahmyr Gibbs", "Panini Prizm base", 517, 1, 4, 6, 8, "2nd Prizm copy at 532/5 — confirm distinct"),
 ("Gibbs (2)", "Jahmyr Gibbs", "Panini Mosaic base", 535, 8, 3, 5, 7, ""),
 ("Henderson (1)", "TreVeyon Henderson", "Chrome Fortune GOLD X-Fractor RC", 528, 7, 8, 12, 20, "gold x-fractors usually serialed — CHECK BACK for /50"),
 ("Henderson (2)", "TreVeyon Henderson", "Select Flash multicolor RC", 516, 7, 4, 6, 9, ""),
 ("Henderson (3)", "TreVeyon Henderson", "Topps IC The Pick RC", 530, 5, 3, 5, 7, ""),
 ("Henry", "Derrick Henry", "Topps Chrome All-Chrome insert", 520, 9, 4, 6, 9, ""),
 ("Hunter", "Travis Hunter", "Panini Mosaic RC", 520, 1, 5, 7, 11, "top-2 pick hype"),
 ("Hurts (1)", "Jalen Hurts", "Topps IC Sunday Showcase", 527, 3, 4, 6, 9, ""),
 ("Hurts (2)", "Jalen Hurts / Saquon Barkley", "Topps IC Paramount Pairings", 526, 9, 4, 6, 10, "2nd copy at 530/1 — confirm distinct"),
 ("Irvin (1)", "Michael Irvin", "Panini Mosaic base", 522, 1, 3, 4, 6, "Cowboys legend"),
 ("Irvin (2)", "Michael Irvin", "Mosaic Touchdown Masters", 525, 1, 3, 5, 7, ""),
 ("Johnson", "Calvin Johnson", "Panini Mosaic base", 522, 7, 3, 5, 7, "HOF legend"),
 ("Judkins", "Quinshon Judkins", "Panini Mosaic RC", 523, 8, 4, 5, 8, ""),
 ("Lamb (1)", "CeeDee Lamb", "Topps IC The Pick", 514, 5, 4, 5, 8, ""),
 ("Lamb (2)", "CeeDee Lamb", "Select Flash multicolor", 522, 3, 4, 6, 9, ""),
 ("Mahomes (1)", "Patrick Mahomes II", "Panini Prizm base", 518, 3, 6, 9, 14, ""),
 ("Mahomes (2)", "Patrick Mahomes II", "Select Red/Blue Flash", 528, 3, 6, 9, 14, ""),
 ("Mahomes (3)", "Patrick Mahomes II / Xavier Worthy", "Donruss Optic Best Buddys", 510, 3, 4, 6, 10, ""),
 ("Manning", "Peyton Manning", "Leaf Draft First Overall 1998", 511, 7, 3, 5, 8, ""),
 ("Maye (1)", "Drake Maye", "Mosaic Notoriety", 524, 2, 4, 6, 9, "2nd copy at 535/3 — confirm distinct"),
 ("McCaffrey", "Christian McCaffrey", "Phoenix hyper red/teal", 515, 8, 4, 6, 9, ""),
 ("Nacua", "Puka Nacua", "Panini Prizm base", 519, 8, 4, 6, 9, ""),
 ("Rice", "Jerry Rice", "Panini Select (Valley State)", 511, 2, 5, 7, 11, "GOAT nostalgia"),
 ("Sanders (1)", "Shedeur Sanders", "Donruss Optic Rated Rookie RC", 511, 1, 5, 7, 11, "hype name"),
 ("Sanders (2)", "Shedeur Sanders", "Donruss Optic Passing Grade RC", 511, 5, 5, 7, 11, ""),
 ("Sanders (3)", "Shedeur Sanders", "Prizm Red White & Blue RC", 541, 4, 5, 8, 12, ""),
 ("Smith-Njigba", "Jaxon Smith-Njigba", "Panini Prizm base", 532, 2, 4, 6, 9, ""),
 ("Ward", "Cam Ward", "Donruss Optic My House RC", 511, 4, 5, 7, 10, ""),
 ("Warner", "Kurt Warner", "Mosaic Touchdown Masters", 524, 9, 3, 5, 7, "HOF legend"),
 ("Watt (1)", "T.J. Watt", "Panini Contours gold", 512, 2, 4, 5, 8, "2nd copy at 512/7 — confirm distinct"),
 ("Auto-Bosma", "Blake Bosma", "SAGE certified AUTO", 533, 3, 3, 5, 8, "real certified autograph"),
 ("Auto-Hurst", "Ted Hurst", "SAGE certified AUTO", 533, 6, 3, 5, 8, "real certified autograph"),
 ("Auto-Matsuzawa", "Kansei Matsuzawa", "SAGE certified AUTO", 534, 4, 3, 5, 8, "real certified autograph — Japan pipeline story"),
 ("Auto-Morton", "Behren Morton", "SAGE certified AUTO", 534, 7, 3, 5, 8, "real certified autograph"),
]

st = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=st["Title"], fontSize=20, spaceAfter=2, textColor=BLACK)
sub = ParagraphStyle("sub", parent=st["Normal"], fontSize=9.5, textColor=GRAY_MD, spaceAfter=10)
grp = ParagraphStyle("grp", parent=st["Heading2"], fontSize=12.5, textColor=BLACK, spaceBefore=11, spaceAfter=4)
note = ParagraphStyle("note", parent=st["Normal"], fontSize=8.5, textColor=GRAY_MD, spaceBefore=8)
cardp = ParagraphStyle("cardp", parent=st["Normal"], fontSize=9, leading=11, textColor=BLACK)


def money(x):
    return f"${x:,.2f}" if x % 1 else f"${int(x)}"


live_value = round(sum(float(m['price'] or 0) for m in collisions), 2)
cand_typ = sum(c[6] for c in CANDIDATES)

out = Path("docs/scan509_542_collision_check.pdf")
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=.5 * inch, bottomMargin=.5 * inch,
                         leftMargin=.55 * inch, rightMargin=.55 * inch)
flow = [
    Paragraph("Scans 509-542 &mdash; eBay collision check + posting candidates", h1),
    Paragraph(f"303 cards across 34 scans &middot; {len(collisions)} already live on eBay (${live_value:,.0f} of listings) "
              f"&middot; {len(CANDIDATES)} clean posting candidates (typ ~{money(cand_typ)}) &middot; rest = lot/bulk", sub),
    Paragraph("<b>Section 1 is the urgent one:</b> every card below matches a live listing at high confidence "
              "(same player + same insert, or same player + same brand + same parallel color). These are the "
              "physical copies of cards already posted &mdash; set each aside into the listed-inventory box, "
              "do NOT re-sell or lot them. Caveat: plain base cards can't be title-matched this way, so a few "
              "more collisions may hide among the base cards &mdash; if you remember listing it, set it aside.", note),
]

# ---- Section 1: collisions, alphabetical by player last name ----
flow.append(Paragraph(f"1 &middot; Already on eBay &mdash; set aside ({len(collisions)} cards)", grp))

def last_name(p):
    parts = [w for w in p.replace("'", "").split() if w.lower() not in ('jr.', 'jr', 'ii', 'iii', 'sr')]
    return parts[-1].lower() if parts else p.lower()

rows = sorted(collisions, key=lambda m: (last_name(m['player']), m['scan'], m['pos']))
data = [["", "Card in pile", "Scan/Pos", "Live listing", "Price"]]
for m in rows:
    desc = f"<b>{m['player']}</b> <font size=7.5>{m['card_desc'][:52]}</font>"
    live = f"<font size=7.5>{m['item_id']}<br/>{m['title'][:54]}</font>"
    data.append(["", Paragraph(desc, cardp), f"{m['scan']}/{m['pos']}",
                  Paragraph(live, cardp), money(float(m['price'] or 0))])
t = Table(data, colWidths=[0.24 * inch, 2.5 * inch, 0.62 * inch, 3.3 * inch, 0.62 * inch])
n_rows = len(data)
box_style = [("BOX", (0, r), (0, r), 1, GRAY_DK) for r in range(1, n_rows)]
t.setStyle(TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_DK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GRAY_LT]),
    ("ALIGN", (2, 0), (2, -1), "CENTER"), ("ALIGN", (4, 0), (4, -1), "RIGHT"),
    ("ALIGN", (0, 0), (0, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (1, 0), (-1, -1), .4, GRAY_MD), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
] + box_style))
flow.append(t)

# ---- Section 2: posting candidates ----
flow.append(Paragraph(f"2 &middot; Clean &mdash; worth posting individually ({len(CANDIDATES)} cards, typ ~{money(cand_typ)})", grp))
flow.append(Paragraph("Raw/ungraded July 2026 reasoned estimates (same basis as the scan 493-507 sheet; automated "
                       "comps unreliable for 2025 sets). Alphabetical by last name; autos at the end.", note))
data2 = [["", "Card", "Detail", "Scan/Pos", "Low", "Typ", "High"]]
for key, player, desc, scan, pos, lo, ty, hi, nt in CANDIDATES:
    vv = desc + (f" &middot; <i>{nt}</i>" if nt else "")
    data2.append(["", Paragraph(f"<b>{player}</b>", cardp), Paragraph(f"<font size=7.5>{vv}</font>", cardp),
                   f"{scan}/{pos}", money(lo), money(ty), money(hi)])
data2.append(["", "", Paragraph("<b>batch typical</b>", cardp), "", "", money(cand_typ), ""])
t2 = Table(data2, colWidths=[0.24 * inch, 1.55 * inch, 3.15 * inch, 0.62 * inch, 0.5 * inch, 0.5 * inch, 0.5 * inch])
n2 = len(data2)
box2 = [("BOX", (0, r), (0, r), 1, GRAY_DK) for r in range(1, n2 - 1)]
t2.setStyle(TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_DK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, GRAY_LT]),
    ("ALIGN", (3, 0), (3, -1), "CENTER"), ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
    ("ALIGN", (0, 0), (0, -1), "CENTER"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("LINEABOVE", (0, -1), (-1, -1), 0.6, GRAY_DK),
    ("GRID", (1, 0), (-1, -2), .4, GRAY_MD), ("TOPPADDING", (0, 0), (-1, -1), 3.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
] + box2))
flow.append(t2)

flow.append(Paragraph(
    "Everything else: ~110 modern commons (Disco Prizm base, Score base, Mosaic base rookies of "
    "day-3 picks, etc.) &mdash; team-lot material per the usual 5-cards-or-fewer bundling; and 31 "
    "vintage/junk-wax cards (Pro Set, 90s Leaf/Edge/Pacific, playing-card oddballs) &mdash; bulk "
    "box, not worth individual effort. Duplicate-copy flags inside the candidates list (Gibbs, "
    "Hurts/Barkley, Maye, Watt) mean the same design appears twice in the batch &mdash; verify "
    "each is a real second physical card before posting both, same drill as the last batch.", note))
doc.build(flow)
dl = Path.home() / "Downloads" / out.name
shutil.copy(out, dl)
print(f"collisions={len(collisions)} (${live_value:,.0f} live) · candidates={len(CANDIDATES)} (typ ${cand_typ})")
print(f"Wrote {out} and {dl}")
