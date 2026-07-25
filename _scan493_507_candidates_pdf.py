"""Scans 493-507 — individually-worth-posting candidates (raw/ungraded July 2026
eBay-comp estimate). These are the cards flagged out of the full 15-scan batch as
clearing an individual-listing bar (established stars/legends, or real chase
prospects), not the common base/insert bulk. HOLD — not posted, pull each by
scan+position and confirm before listing.

Note on pricing: SportsCardsPro/PriceCharting's automated match returned mostly
garbage for these (Mickey Mouse, Goofy, Jacob deGrom, NHL 2K matches on totally
unrelated products) because these 2025 sets aren't cleanly indexed yet — same
problem hit earlier this batch. These are reasoned market estimates, not hard
comps; a few (marked *) had a genuine PriceCharting hit that looked legitimate.

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

# (name, variant, pos, low, typ, high, note)
GROUPS = {
 "Scan 493": [
  ("Shohei Ohtani", "Dodgers pitcher · rainbow insert (pos 1)", 1, 15, 22, 40, "*biggest name in the batch — get a real comp before pricing, automated data was wildly inconsistent ($12-172 depending on query)"),
  ("Jackson Merrill", "Padres · rainbow insert, 2nd copy (pos 3)", 3, 5, 8, 12, ""),
  ("Chase Burns", "rainbow insert RC (pos 5)", 5, 3, 5, 8, "hyped 2025 pitching prospect debut"),
  ("Jose Ramirez", "Guardians · rainbow insert, 2nd copy (pos 6)", 6, 5, 7, 10, ""),
  ("Colson Montgomery", "White Sox RC (pos 7)", 7, 3, 5, 7, "2025 debut"),
  ("Kyle Schwarber", "Phillies · rainbow insert (pos 9)", 9, 5, 7, 11, ""),
 ],
 "Scan 494": [
  ("Jackson Merrill", "Padres · rainbow insert, 1st copy (pos 1)", 1, 5, 8, 12, ""),
  ("Jose Ramirez", "Guardians · rainbow insert, 1st copy (pos 3)", 3, 5, 7, 10, ""),
  ("Cal Raleigh", "Mariners · Statement-style (pos 4)", 4, 10, 14, 20, "61-HR-chase 2025 season"),
  ("Bubba Chandler", "Pirates RC (pos 7)", 7, 4, 6, 9, "top pitching prospect, 2025 debut"),
  ("Buster Posey", "Giants · Topps 75", 8, 12, 16, 21, "*PriceCharting confirmed match"),
  ("Kyle Tucker", "Dodgers · Topps 75 (pos 9)", 9, 6, 9, 14, ""),
 ],
 "Scan 495": [
  ("Cal Raleigh", "Mariners · graffiti/paint style (pos 7)", 7, 10, 14, 20, ""),
 ],
 "Scan 496": [
  ("Rafael Devers", "Giants · Chrome (pos 2)", 2, 4, 6, 10, ""),
  ("Junior Caminero", "Rays · base Chrome, 2nd copy (pos 3)", 3, 4, 6, 9, ""),
 ],
 "Scan 497": [
  ("Juan Soto", "Yankees · 8-Bit Ballers insert (pos 2)", 2, 8, 12, 18, ""),
  ("Carlos Beltran", "Royals · Heritage (pos 3)", 3, 3, 5, 7, "borderline HOF nostalgia"),
  ("Dylan Crews", "Nationals · 8-Bit Ballers RC (pos 5)", 5, 4, 6, 9, "former #2 overall pick"),
  ("Cal Raleigh", "Mariners · Heritage AL All-Stars (pos 9)", 9, 16, 20, 27, "*PriceCharting confirmed match"),
 ],
 "Scan 498": [
  ("Freddie Freeman", "Dodgers · 35th Anniversary All-Star (pos 1)", 1, 6, 9, 14, ""),
  ("Mookie Betts", "Dodgers · Bowman Veterans (pos 5)", 5, 9, 12, 16, "*PriceCharting confirmed match"),
 ],
 "Scan 499": [
  ("Luis Gil", "Yankees · Topps 75 (pos 2)", 2, 3, 5, 8, "2024 AL Rookie of the Year"),
  ("Marcelo Mayer", "Red Sox · Future Stars insert (pos 3)", 3, 5, 7, 11, "3rd Mayer card in this batch"),
  ("Shohei Ohtani", "Dodgers pitcher · Topps 75 (pos 6)", 6, 15, 22, 40, "*biggest name in the batch — get a real comp before pricing"),
  ("Pedro Martinez", "Red Sox · Topps 75 All-Star (pos 7)", 7, 4, 6, 9, "HOF legend"),
 ],
 "Scan 501": [
  ("Marcelo Mayer", "Red Sox · Chrome RC, bubblegum shot (pos 5)", 5, 5, 8, 12, ""),
  ("Marcelo Mayer", "Red Sox · Heritage 3rd Base (pos 6)", 6, 5, 7, 11, ""),
  ("Paul Skenes", "Pirates · Heritage NL All-Stars (pos 9)", 9, 6, 9, 14, ""),
 ],
 "Scan 502": [
  ("Paul Skenes", "Pirates · Topps 75 (pos 5)", 5, 6, 9, 15, ""),
  ("Junior Caminero", "Rays · Heritage sparkle parallel (pos 7)", 7, 5, 8, 12, ""),
 ],
 "Scan 500": [
  ("Ronald Acuna Jr.", "Braves · Chrome FL parallel (pos 1)", 1, 8, 12, 20, "*PriceCharting hit, but confirm exact parallel"),
 ],
 "Scan 504": [
  ("David Ortiz", "Red Sox · Panini Crusade (pos 3)", 3, 4, 6, 9, "HOF legend"),
  ("Jacob Wilson", "Athletics · Panini Crusade (pos 6)", 6, 4, 7, 10, "real breakout — outselling his father's cards per market chatter"),
 ],
}

st = getSampleStyleSheet()
h1 = ParagraphStyle("h1", parent=st["Title"], fontSize=21, spaceAfter=2, textColor=BLACK)
sub = ParagraphStyle("sub", parent=st["Normal"], fontSize=9.5, textColor=GRAY_MD, spaceAfter=10)
grp = ParagraphStyle("grp", parent=st["Heading2"], fontSize=12.5, textColor=BLACK, spaceBefore=11, spaceAfter=4)
note = ParagraphStyle("note", parent=st["Normal"], fontSize=8.5, textColor=GRAY_MD, spaceBefore=8)
cardp = ParagraphStyle("cardp", parent=st["Normal"], fontSize=10, leading=12, textColor=BLACK)


def money(x):
    return f"${x:,.2f}" if x % 1 else f"${int(x)}"


all_rows = []
for scan_name, cards in GROUPS.items():
    for n, v, pos, lo, ty, hi, nt in cards:
        all_rows.append({"scan": scan_name, "card": n, "variant": v, "pos": pos,
                          "low": lo, "typical": ty, "high": hi, "note": nt})

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
    Paragraph(f"{len(all_rows)} cards &middot; pulled from the full 15-scan batch &middot; "
              "raw/ungraded eBay-comp estimate &middot; NOT posted &mdash; pull each and confirm", sub),
    Paragraph(f"<b>Batch total: {money(grand['low'])} &ndash; {money(grand['high'])}</b> "
              f"(typical ~{money(grand['typical'])})", grp),
    Paragraph("<b>Two Shohei Ohtani cards (Scans 493 &amp; 499) are the wild cards here.</b> "
              "He's the single biggest name in the batch, but the automated pricing data was "
              "genuinely unreliable &mdash; the same product code returned prices from $12 to $172 "
              "depending on query phrasing. Get a real eBay sold-comp on these two specifically "
              "before setting a price; everything else below is a more confident reasoned estimate "
              "off player standing and card scarcity, not a hard comp.", note),
]


def tbl(scan_name, cards):
    flow.append(Paragraph(scan_name, grp))
    sub_ty = round(sum(c[5] for c in cards), 2)
    data = [["", "Card", "Variant", "Low", "Typ", "High"]]
    for n, v, pos, lo, ty, hi, nt in cards:
        cardcell = f"<b>{n}</b>"
        vv = v + (f" &middot; <i>{nt}</i>" if nt else "")
        data.append(["", Paragraph(cardcell, cardp), Paragraph(f"<font size=8.5>{vv}</font>", cardp),
                      money(lo), money(ty), money(hi)])
    data.append(["", "", Paragraph("<b>scan typical</b>", cardp), "", "", Paragraph(f"<b>{money(sub_ty)}</b>", cardp)])
    t = Table(data, colWidths=[0.28 * inch, 1.55 * inch, 3.15 * inch, 0.6 * inch, 0.6 * inch, 0.6 * inch])
    n_rows = len(data)
    box_style = [("BOX", (0, r), (0, r), 1, GRAY_DK) for r in range(1, n_rows - 1)]
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9), ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), GRAY_DK), ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [WHITE, GRAY_LT]),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEABOVE", (0, -1), (-1, -1), 0.6, GRAY_DK),
        ("GRID", (1, 0), (-1, -2), .4, GRAY_MD), ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ] + box_style))
    flow.append(t)


for scan_name, cards in GROUPS.items():
    tbl(scan_name, cards)

flow.append(Paragraph(
    "How to read this: prices are RAW/ungraded July 2026 eBay-comp estimates (asks, sold runs a bit "
    "under). Rows marked * had a plausible automated PriceCharting hit; everything else is a reasoned "
    "estimate off player standing and card scarcity &mdash; verify before finalizing an ask, especially "
    "the two Ohtani cards. Several players repeat across scans (Cal Raleigh x3 in this candidate list "
    "alone, Jackson Merrill x2, Jose Ramirez x2, Marcelo Mayer x3, Paul Skenes x2, Ohtani x2, Junior "
    "Caminero x2) &mdash; confirm each is a genuine second physical copy before listing both.", note))
doc.build(flow)
dl = Path.home() / "Downloads" / out.name
shutil.copy(out, dl)
print(f"{len(all_rows)} cards · total ${grand['low']:.0f}-{grand['high']:.0f} (typ ${grand['typical']:.0f})")
print(f"Wrote {out} and {dl}")
