"""Scans 493-507 — individually-worth-posting candidates (raw/ungraded July 2026
eBay-comp estimate). These are the cards flagged out of the full 15-scan batch as
clearing an individual-listing bar (established stars/legends, or real chase
prospects), not the common base/insert bulk. HOLD — not posted, pull each by
scan+position and confirm before listing.

Note on pricing: SportsCardsPro/PriceCharting's automated match returned mostly
garbage for these (Mickey Mouse, Goofy, Jacob deGrom, NHL 2K matches on totally
unrelated products) because these 2025 sets aren't cleanly indexed yet. These
are reasoned market estimates, not hard comps; a few (marked *) had a genuine
PriceCharting hit that looked legitimate.

Sorted alphabetically by last name (scan-by-scan was hard to scan through) with
a price-ranked quick-reference up top and a posting suggestion per row.

Writes docs/scan493_507_candidates.pdf (+ ~/Downloads) and
output/_scan493_507_candidates.json.
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

# (last_name_sort_key, name, variant, scan, pos, low, typ, high, note, suggestion)
CARDS = [
 ("Acuna Jr.", "Ronald Acuna Jr.", "Braves · Chrome FL parallel", 500, 1, 8, 12, 20,
  "*PriceCharting hit, but confirm exact parallel", "Post — star player, safe individual listing"),
 ("Beltran", "Carlos Beltran", "Royals · Heritage", 497, 3, 3, 5, 7,
  "borderline HOF nostalgia", "Post"),
 ("Betts", "Mookie Betts", "Dodgers · Bowman Veterans", 498, 5, 9, 12, 16,
  "*PriceCharting confirmed match", "Post — priced off a real comp"),
 ("Burns", "Chase Burns", "rainbow insert RC", 493, 5, 3, 5, 8,
  "hyped 2025 pitching prospect debut", "Post"),
 ("Caminero (1)", "Junior Caminero", "Rays · Heritage sparkle parallel", 502, 7, 5, 8, 12,
  "", "Post — but see Caminero (2), confirm both are real physical copies"),
 ("Caminero (2)", "Junior Caminero", "Rays · base Chrome, 2nd copy", 496, 3, 4, 6, 9,
  "", "Post if genuinely a 2nd copy, else fold into a Rays lot"),
 ("Chandler", "Bubba Chandler", "Pirates RC", 494, 7, 4, 6, 9,
  "top pitching prospect, 2025 debut", "Post"),
 ("Crews", "Dylan Crews", "Nationals · 8-Bit Ballers RC", 497, 5, 4, 6, 9,
  "former #2 overall pick", "Post"),
 ("Devers", "Rafael Devers", "Giants · Chrome", 496, 2, 4, 6, 10,
  "", "Post"),
 ("Freeman", "Freddie Freeman", "Dodgers · 35th Anniversary All-Star", 498, 1, 6, 9, 14,
  "", "Post"),
 ("Gil", "Luis Gil", "Yankees · Topps 75", 499, 2, 3, 5, 8,
  "2024 AL Rookie of the Year", "Post"),
 ("Martinez", "Pedro Martinez", "Red Sox · Topps 75 All-Star", 499, 7, 4, 6, 9,
  "HOF legend", "Post"),
 ("Mayer (1)", "Marcelo Mayer", "Red Sox · Chrome RC, bubblegum shot", 501, 5, 5, 8, 12,
  "", "Post if all 3 Mayers are separate physical copies — confirm first"),
 ("Mayer (2)", "Marcelo Mayer", "Red Sox · Heritage 3rd Base", 501, 6, 5, 7, 11,
  "", "Post if all 3 Mayers are separate physical copies — confirm first"),
 ("Mayer (3)", "Marcelo Mayer", "Red Sox · Future Stars insert", 499, 3, 5, 7, 11,
  "3rd Mayer card in this batch", "Post if all 3 Mayers are separate physical copies — confirm first"),
 ("Merrill (1)", "Jackson Merrill", "Padres · rainbow insert, 1st copy", 494, 1, 5, 8, 12,
  "", "Post — but see Merrill (2), confirm both are real physical copies"),
 ("Merrill (2)", "Jackson Merrill", "Padres · rainbow insert, 2nd copy", 493, 3, 5, 8, 12,
  "", "Post if genuinely a 2nd copy, else fold into a Padres lot"),
 ("Montgomery", "Colson Montgomery", "White Sox RC", 493, 7, 3, 5, 7,
  "2025 debut", "Post"),
 ("Ohtani (1)", "Shohei Ohtani", "Dodgers pitcher · base card, not an insert", 493, 1, 2, 3, 5,
  "JC confirmed in-hand: plain base card, not a special parallel — priced accordingly despite the name",
  "Post as a cheap single, or fold into a Dodgers lot"),
 ("Ohtani (2)", "Shohei Ohtani", "Dodgers pitcher · Topps 75", 499, 6, 15, 22, 40,
  "*biggest name in the batch — get a real comp before pricing", "GET A REAL COMP FIRST — most uncertain price in the batch"),
 ("Ortiz", "David Ortiz", "Red Sox · Panini Crusade", 504, 3, 4, 6, 9,
  "HOF legend", "Post"),
 ("Posey", "Buster Posey", "Giants · Topps 75", 494, 8, 12, 16, 21,
  "*PriceCharting confirmed match", "Post — priced off a real comp"),
 ("Raleigh (1)", "Cal Raleigh", "Mariners · Heritage AL All-Stars", 497, 9, 16, 20, 27,
  "*PriceCharting confirmed match", "Post — priced off a real comp, but see Raleigh (2)/(3), confirm all 3 are separate copies"),
 ("Raleigh (2)", "Cal Raleigh", "Mariners · Statement-style", 494, 4, 10, 14, 20,
  "61-HR-chase 2025 season", "Post if genuinely a separate copy from Raleigh (1)/(3)"),
 ("Raleigh (3)", "Cal Raleigh", "Mariners · graffiti/paint style", 495, 7, 10, 14, 20,
  "", "Post if genuinely a separate copy from Raleigh (1)/(2)"),
 ("Ramirez (1)", "Jose Ramirez", "Guardians · rainbow insert, 1st copy", 494, 3, 5, 7, 10,
  "", "Post — but see Ramirez (2), confirm both are real physical copies"),
 ("Ramirez (2)", "Jose Ramirez", "Guardians · rainbow insert, 2nd copy", 493, 6, 5, 7, 10,
  "", "Post if genuinely a 2nd copy, else fold into a Guardians lot"),
 ("Schwarber", "Kyle Schwarber", "Phillies · rainbow insert", 493, 9, 5, 7, 11,
  "", "Post"),
 ("Skenes (1)", "Paul Skenes", "Pirates · Topps 75", 502, 5, 6, 9, 15,
  "", "Post if genuinely a 2nd copy from Skenes (2), else fold into a Pirates lot"),
 ("Skenes (2)", "Paul Skenes", "Pirates · Heritage NL All-Stars", 501, 9, 6, 9, 14,
  "", "Post if genuinely a 2nd copy from Skenes (1), else fold into a Pirates lot"),
 ("Soto", "Juan Soto", "Yankees · 8-Bit Ballers insert", 497, 2, 8, 12, 18,
  "", "Post"),
 ("Tucker", "Kyle Tucker", "Dodgers · Topps 75", 494, 9, 6, 9, 14,
  "", "Post"),
 ("Wilson", "Jacob Wilson", "Athletics · Panini Crusade", 504, 6, 4, 7, 10,
  "real breakout — outselling his father's cards per market chatter", "Post"),
]

st = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=st["Title"], fontSize=21, spaceAfter=2, textColor=BLACK)
sub = ParagraphStyle("sub", parent=st["Normal"], fontSize=9.5, textColor=GRAY_MD, spaceAfter=10)
grp = ParagraphStyle("grp", parent=st["Heading2"], fontSize=12.5, textColor=BLACK, spaceBefore=11, spaceAfter=4)
note = ParagraphStyle("note", parent=st["Normal"], fontSize=8.5, textColor=GRAY_MD, spaceBefore=8)
cardp = ParagraphStyle("cardp", parent=st["Normal"], fontSize=9.5, leading=11.5, textColor=BLACK)
sugp = ParagraphStyle("sugp", parent=st["Normal"], fontSize=8.5, leading=10.5, textColor=colors.HexColor("#1a5c1a"))
sugp_warn = ParagraphStyle("sugp_warn", parent=st["Normal"], fontSize=8.5, leading=10.5, textColor=colors.HexColor("#8a2b0a"))


def money(x):
    return f"${x:,.2f}" if x % 1 else f"${int(x)}"


all_rows = []
for sort_key, name, variant, scan, pos, lo, ty, hi, nt, sug in CARDS:
    all_rows.append({"sort_key": sort_key, "card": name, "variant": variant, "scan": scan, "pos": pos,
                      "low": lo, "typical": ty, "high": hi, "note": nt, "suggestion": sug})

tot = lambda k: round(sum(r[k] for r in all_rows), 2)
grand = {k: tot(k) for k in ("low", "typical", "high")}
Path("output/_scan493_507_candidates.json").write_text(json.dumps(
    {"count": len(all_rows), "grand_total": grand, "cards": all_rows,
     "status": "HOLD - not posted, pull and confirm before listing",
     "basis": "raw/ungraded July 2026 eBay-comp estimate; automated pricing (PriceCharting) "
              "mostly returned false matches on unrelated products for these fresh 2025 sets — "
              "starred (*) rows had a plausible automated match, everything else is a reasoned estimate"},
    indent=1))

out = Path("docs/scan493_507_candidates.pdf")
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=.55 * inch, bottomMargin=.55 * inch,
                         leftMargin=.6 * inch, rightMargin=.6 * inch)
flow = [
    Paragraph("Scans 493-507 &mdash; individually-worth-posting candidates (HOLD)", h1),
    Paragraph(f"{len(all_rows)} cards &middot; alphabetical by last name &middot; "
              "raw/ungraded eBay-comp estimate &middot; NOT posted &mdash; pull each and confirm", sub),
    Paragraph(f"<b>Batch total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
              f"(typical ~{money(grand['typical'])})", grp),
    Paragraph("<b>Two Shohei Ohtani cards in this batch, priced very differently.</b> "
              "Ohtani (1), Scan 493, is confirmed in-hand as a plain base card (not the special parallel "
              "it looked like from the scan), so it's priced modestly. Ohtani (2), Scan 499 (Topps 75 "
              "insert), is still the wild card &mdash; he's the single biggest name in the batch, but the "
              "automated pricing data was genuinely unreliable for it (the same product code returned "
              "prices from $12 to $172 depending on query phrasing). Get a real eBay sold-comp on that "
              "one before setting a price.", note),
]

# --- Quick reference: top 10 by typical price ---
flow.append(Paragraph("Quick reference &mdash; top 10 by typical price", grp))
top10 = sorted(all_rows, key=lambda r: -r["typical"])[:10]
qdata = [["Card", "Variant", "Scan/Pos", "Typ"]]
for r in top10:
    qdata.append([Paragraph(f"<b>{r['card']}</b>", cardp),
                  Paragraph(f"<font size=8>{r['variant']}</font>", cardp),
                  f"{r['scan']}/{r['pos']}",
                  money(r["typical"])])
qt = Table(qdata, colWidths=[1.7 * inch, 3.1 * inch, 0.8 * inch, 0.6 * inch])
qt.setStyle(TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_DK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, GRAY_LT]),
    ("ALIGN", (2, 0), (-1, -1), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("GRID", (0, 0), (-1, -1), .4, GRAY_MD), ("TOPPADDING", (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
]))
flow.append(qt)

# --- Full alphabetical list ---
flow.append(Paragraph("Full list &mdash; alphabetical by last name", grp))
sorted_rows = sorted(all_rows, key=lambda r: r["sort_key"])
data = [["", "Card", "Variant", "Scan/Pos", "Low", "Typ", "High", "Suggestion"]]
for r in sorted_rows:
    cardcell = f"<b>{r['card']}</b>"
    vv = r["variant"] + (f" &middot; <i>{r['note']}</i>" if r["note"] else "")
    style = sugp_warn if "GET A REAL COMP" in r["suggestion"] else sugp
    data.append(["", Paragraph(cardcell, cardp), Paragraph(f"<font size=8>{vv}</font>", cardp),
                  f"{r['scan']}/{r['pos']}", money(r["low"]), money(r["typical"]), money(r["high"]),
                  Paragraph(r["suggestion"], style)])
data.append(["", "", Paragraph("<b>batch typical</b>", cardp), "", "", money(grand["typical"]), "", ""])
t = Table(data, colWidths=[0.24 * inch, 1.1 * inch, 1.75 * inch, 0.55 * inch, 0.45 * inch, 0.45 * inch, 0.45 * inch, 1.55 * inch])
n_rows = len(data)
box_style = [("BOX", (0, r), (0, r), 1, GRAY_DK) for r in range(1, n_rows - 1)]
t.setStyle(TableStyle([
    ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("BACKGROUND", (0, 0), (-1, 0), GRAY_DK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
    ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, GRAY_LT]),
    ("ALIGN", (3, 0), (6, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEABOVE", (0, -1), (-1, -1), 0.6, GRAY_DK),
    ("GRID", (1, 0), (-1, -2), .4, GRAY_MD), ("TOPPADDING", (0, 0), (-1, -1), 4.5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
] + box_style))
flow.append(t)

flow.append(Paragraph(
    "How to read this: prices are RAW/ungraded July 2026 eBay-comp estimates (asks, sold runs a bit "
    "under). Rows marked * had a plausible automated PriceCharting hit; everything else is a reasoned "
    "estimate off player standing and card scarcity &mdash; verify before finalizing an ask, especially "
    "Ohtani (2). Several players have more than one physical copy flagged (Cal Raleigh x3, Marcelo Mayer "
    "x3, Jackson Merrill/Jose Ramirez/Paul Skenes/Junior Caminero x2 each, Ohtani x2) &mdash; the "
    "suggestion column flags these; confirm each is a genuine second physical card before posting both, "
    "otherwise fold the extra into a team lot instead.", note))
doc.build(flow)
dl = Path.home() / "Downloads" / out.name
shutil.copy(out, dl)
print(f"{len(all_rows)} cards · total ${grand['low']:.0f}-{grand['high']:.0f} (typ ${grand['typical']:.0f})")
print(f"Wrote {out} and {dl}")
