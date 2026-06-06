"""
build_signature_class_ref_pdf.py — 2025 Topps Signature Class Football
reference sheet for base and Chrome base pulls. No autos.

2 pages:
  Page 1 — Top rookies to pull (both base #101-250 and Chrome #101-250)
  Page 2 — Top veterans to pull + key non-auto inserts

Output: ~/Downloads/harpua2001_signature_class_ref_2025.pdf
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path.home() / "Downloads" / "harpua2001_signature_class_ref_2025.pdf"

PAGE_W, PAGE_H = letter
ML = 0.45 * inch
MR = 0.45 * inch
USABLE_W = PAGE_W - ML - MR

INK   = HexColor("#000000")
DARK  = HexColor("#1f1f1f")
MID   = HexColor("#555555")
LIGHT = HexColor("#9a9a9a")
RULE  = HexColor("#d0d0d0")
BG    = HexColor("#f3f3f3")
BG2   = HexColor("#e8e8e8")
WHITE = white
GOLD  = HexColor("#b8860b")
GREEN = HexColor("#1a6b1a")
RED   = HexColor("#cc2020")

# ---- Data ------------------------------------------------------------------

# Tier 1 = must pull, high demand. Tier 2 = solid. Tier 3 = situational.
# Chrome versions of all these are more valuable — noted in column.
# base_num = card number in base and chrome sets (same numbering)

ROOKIES = [
    # (card_num, player, team, tier, note)
    (102, "Ashton Jeanty",       "Raiders",    1, "ROTY favorite — top priority"),
    (101, "Cam Ward",            "Titans",     1, "QB1 of class"),
    (224, "Travis Hunter",       "Jaguars",    1, "2-way player, massive hype"),
    (228, "Shedeur Sanders",     "Browns",     1, "High profile, polarizing demand"),
    (106, "Jaxson Dart",         "Giants",     1, "QB demand always strong"),
    (130, "James Pearce Jr.",    "Falcons",    1, "Top pass rusher this class"),
    (230, "Tetairoa McMillan",   "Panthers",   1, "WR1 of class"),
    (118, "Abdul Carter",        "Giants",     2, "Elite edge, top-10 pick"),
    (109, "Omarion Hampton",     "Chargers",   2, "RB1 of class"),
    (110, "Tyler Warren",        "Colts",      2, "TE1 of class"),
    (105, "Emeka Egbuka",        "Buccaneers", 2, "WR talent, solid market"),
    (141, "Mason Graham",        "Browns",     2, "Top DT, picks vary"),
    (119, "Cam Skattebo",        "Giants",     2, "RB, Giants hype"),
    (113, "Colston Loveland",    "Bears",      2, "TE2 of class"),
    (127, "RJ Harvey",           "Broncos",    2, "RB sleeper"),
    (103, "Dillon Gabriel",      "Browns",     3, "Backup QB, situational"),
    (115, "Quinshon Judkins",    "Browns",     3, "RB, Cleveland depth"),
    (111, "Matthew Golden",      "Packers",    3, "WR, watch real role"),
    (128, "Tre Harris",          "Chargers",   3, "WR with upside"),
    (140, "Malaki Starks",       "Ravens",     3, "S, DB cards are slow"),
]

VETERANS = [
    (29,  "Patrick Mahomes II",  "Chiefs",    1, "Always pulls premium"),
    (5,   "Lamar Jackson",       "Ravens",    1, "Back-to-back MVP demand"),
    (7,   "Josh Allen",          "Bills",     1, "Top QB market"),
    (12,  "Ja'Marr Chase",       "Bengals",   1, "WR1 — massive year"),
    (16,  "CeeDee Lamb",         "Cowboys",   1, "Elite WR market"),
    (36,  "Justin Jefferson",    "Vikings",   1, "Premium WR always"),
    (42,  "Jalen Hurts",         "Eagles",    2, "SB contender QB"),
    (43,  "Saquon Barkley",      "Eagles",    2, "Hot off SB run"),
    (6,   "Derrick Henry",       "Ravens",    2, "1k+ yards again"),
    (13,  "Joe Burrow",          "Bengals",   2, "Chrome > base here"),
    (34,  "Brock Bowers",        "Raiders",   2, "Best TE market"),
    (80,  "Travis Kelce",        "Chiefs",    2, "Always liquid"),
    (74,  "Aidan Hutchinson",    "Lions",     2, "DPOY candidate"),
    (49,  "Christian McCaffrey", "49ers",     2, "Health-dependent"),
    (11,  "Caleb Williams",      "Bears",     3, "Sophomore bounce-back?"),
    (37,  "J.J. McCarthy",       "Vikings",   3, "Healthy — watch"),
    (40,  "Malik Nabers",        "Giants",    3, "WR talent, team drag"),
    (57,  "Jayden Daniels",      "Commanders",3, "2nd yr QB"),
    (38,  "Drake Maye",          "Patriots",  3, "You know this one"),
    (21,  "Jordan Love",         "Packers",   3, "Solid but saturated"),
]

# Key non-auto inserts (short prints and desirable sets)
INSERTS = [
    ("Fluidity",         "FL-",  "SP/SSP — QBs + top WRs. Chase Mahomes FL-2, Allen FL-4, Chase FL-5"),
    ("Roses",            "ROSES-","SP — rookies + stars. Jeanty ROSES-14, Ward ROSES-15 are keys"),
    ("Leviathans",       "L-",   "SSP — overlaps Monarchs roster. Mahomes L-7, Hunter L-20"),
    ("Monarchs/Game",    "MTG-", "SSP — same checklist as Leviathans. Allen MTG-2, Jackson MTG-3"),
    ("Shattered",        "S-",   "Insert — Jeanty S-17, McMillan S-5 are top RC pulls"),
    ("Zone Out",         "ZO-",  "Insert — RB/WR focus. McCaffrey ZO-7, Bowers ZO-22"),
    ("Star Cast",        "SC-",  "Insert — Jeanty SC-5, Ward SC-1, Mahomes SC-15"),
    ("After Image",      "AI-",  "Insert — Jeanty not on it; Judkins AI-8, Golden AI-11"),
    ("Sunday Showcase",  "SS-",  "Insert — QB set. Allen SS-7, Jackson SS-5"),
    ("First Class",      "FC-",  "Insert — Chase FC-11, Jefferson FC-12, Hunter FC-9"),
]

# ---- Helpers ---------------------------------------------------------------

TIER_COLOR = {1: GREEN, 2: INK, 3: LIGHT}
TIER_LABEL = {1: "TIER 1", 2: "TIER 2", 3: "TIER 3"}

def _header(c, title, today, page_n):
    c.setFillColor(INK)
    c.rect(0, PAGE_H - 0.68 * inch, PAGE_W, 0.68 * inch, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(ML, PAGE_H - 0.43 * inch, title)
    c.setFont("Helvetica", 8.5)
    c.setFillColor(HexColor("#bbbbbb"))
    c.drawRightString(PAGE_W - MR, PAGE_H - 0.43 * inch, f"{today}  ·  page {page_n}")

def _footer(c, note):
    c.setFont("Helvetica-Oblique", 7)
    c.setFillColor(LIGHT)
    c.drawCentredString(PAGE_W / 2, 0.18 * inch, note)

def _col_headers(c, y, cols):
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(LIGHT)
    for txt, x, align in cols:
        if align == "R":
            c.drawRightString(x, y, txt)
        else:
            c.drawString(x, y, txt)
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(ML, y - 3, PAGE_W - MR, y - 3)


# ---- Page 1: Rookies -------------------------------------------------------

def _page_rookies(c, today):
    _header(c, "2025 Topps Signature Class — Rookies to Pull", today, "1")

    # Legend
    LY = PAGE_H - 0.85 * inch
    c.setFont("Helvetica-Bold", 7.5)
    c.setFillColor(GREEN);  c.drawString(ML, LY, "TIER 1 — Pull every copy")
    c.setFillColor(INK);    c.drawString(ML + 1.35 * inch, LY, "TIER 2 — Pull, sell above $5 Chrome")
    c.setFillColor(LIGHT);  c.drawString(ML + 3.10 * inch, LY, "TIER 3 — Pull only if Chrome or parallel")
    c.setFont("Helvetica", 7.5)
    c.setFillColor(MID)
    c.drawRightString(PAGE_W - MR, LY, "Chrome base = same # but glossy, ~2-4x base value")

    # Column headers
    HDR_Y = LY - 0.22 * inch
    cols = [
        ("#",       ML,                          "L"),
        ("PLAYER",  ML + 0.30 * inch,            "L"),
        ("TEAM",    ML + 2.05 * inch,            "L"),
        ("CHROME",  PAGE_W - MR - 0.85 * inch,  "R"),
        ("BASE",    PAGE_W - MR,                 "R"),
    ]
    _col_headers(c, HDR_Y, cols)

    ROW_START = HDR_Y - 0.14 * inch
    BOTTOM    = 0.35 * inch
    available = ROW_START - BOTTOM
    ROW_H     = available / len(ROOKIES)

    for i, (num, player, team, tier, note) in enumerate(ROOKIES):
        y = ROW_START - i * ROW_H
        row_bot = y - ROW_H

        if i % 2 == 0:
            c.setFillColor(BG)
            c.rect(ML - 3, row_bot, USABLE_W + 6, ROW_H, stroke=0, fill=0)
            c.rect(ML - 3, row_bot, USABLE_W + 6, ROW_H, stroke=0, fill=1)

        mid_y = y - ROW_H * 0.42

        # Card number
        c.setFillColor(LIGHT)
        c.setFont("Helvetica", 8)
        c.drawString(ML, mid_y, f"#{num}")

        # Player name
        color = TIER_COLOR[tier]
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if tier == 1 else "Helvetica", 9 if tier == 1 else 8.5)
        c.drawString(ML + 0.30 * inch, mid_y, player)

        # Team
        c.setFont("Helvetica", 8)
        c.setFillColor(MID)
        c.drawString(ML + 2.05 * inch, mid_y, team)

        # Note (truncated)
        c.setFont("Helvetica-Oblique", 7.5)
        c.setFillColor(LIGHT)
        c.drawString(ML + 3.05 * inch, mid_y, note[:42])

        # Chrome column header value
        c.setFillColor(color)
        c.setFont("Helvetica-Bold", 8)
        chrome_lbl = "YES" if tier <= 2 else "if avail"
        c.drawRightString(PAGE_W - MR - 0.85 * inch, mid_y, chrome_lbl)

        # Base column
        base_lbl = "YES" if tier == 1 else ("YES" if tier == 2 else "pass")
        c.setFont("Helvetica", 8)
        c.drawRightString(PAGE_W - MR, mid_y, base_lbl)

        # Row rule
        c.setStrokeColor(RULE)
        c.setLineWidth(0.25)
        c.line(ML, row_bot, PAGE_W - MR, row_bot)

    _footer(c, "Base #101-250  ·  Chrome Base #101-250 (same numbering)  ·  Both sets have identical checklists")
    c.showPage()


# ---- Page 2: Veterans + Inserts --------------------------------------------

def _page_vets_inserts(c, today):
    _header(c, "2025 Topps Signature Class — Veterans + Key Inserts", today, "2")

    # Veterans section
    VET_START_Y = PAGE_H - 0.92 * inch
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(INK)
    c.drawString(ML, VET_START_Y, "VETERANS — Chrome Base and Base")
    c.setFont("Helvetica", 8)
    c.setFillColor(MID)
    c.drawRightString(PAGE_W - MR, VET_START_Y, "Chrome #1-100 and Base #1-100 share the same checklist")

    HDR_Y = VET_START_Y - 0.18 * inch
    cols = [
        ("#",     ML,                         "L"),
        ("PLAYER", ML + 0.30 * inch,          "L"),
        ("TEAM",   ML + 2.05 * inch,          "L"),
        ("CHROME", PAGE_W - MR - 0.85 * inch, "R"),
        ("BASE",   PAGE_W - MR,               "R"),
    ]
    _col_headers(c, HDR_Y, cols)

    VET_ROW_H = 0.255 * inch
    y = HDR_Y - 0.12 * inch

    for i, (num, player, team, tier, note) in enumerate(VETERANS):
        row_bot = y - VET_ROW_H
        if i % 2 == 0:
            c.setFillColor(BG)
            c.rect(ML - 3, row_bot, USABLE_W + 6, VET_ROW_H, stroke=0, fill=1)

        mid_y = y - VET_ROW_H * 0.52

        c.setFillColor(LIGHT); c.setFont("Helvetica", 8)
        c.drawString(ML, mid_y, f"#{num}")

        color = TIER_COLOR[tier]
        c.setFillColor(color)
        c.setFont("Helvetica-Bold" if tier == 1 else "Helvetica", 9 if tier == 1 else 8.5)
        c.drawString(ML + 0.30 * inch, mid_y, player)

        c.setFont("Helvetica", 8); c.setFillColor(MID)
        c.drawString(ML + 2.05 * inch, mid_y, team)

        c.setFont("Helvetica-Oblique", 7.5); c.setFillColor(LIGHT)
        c.drawString(ML + 3.05 * inch, mid_y, note[:40])

        c.setFillColor(color); c.setFont("Helvetica-Bold", 8)
        c.drawRightString(PAGE_W - MR - 0.85 * inch, mid_y, "YES" if tier <= 2 else "if hot")
        c.setFont("Helvetica", 8)
        c.drawRightString(PAGE_W - MR, mid_y, "YES" if tier == 1 else ("sell?" if tier == 2 else "pass"))

        c.setStrokeColor(RULE); c.setLineWidth(0.25)
        c.line(ML, row_bot, PAGE_W - MR, row_bot)

        y -= VET_ROW_H

    # Inserts section
    INS_Y = y - 0.20 * inch
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 9)
    c.drawString(ML, INS_Y, "KEY NON-AUTO INSERTS  (no autos, no numbered SP)")
    c.setFont("Helvetica", 7.5); c.setFillColor(MID)
    c.drawRightString(PAGE_W - MR, INS_Y,
                      "SP = short print  ·  SSP = super short print  ·  these are harder to pull")

    c.setStrokeColor(RULE); c.setLineWidth(0.5)
    c.line(ML, INS_Y - 4, PAGE_W - MR, INS_Y - 4)

    INS_ROW_H = 0.235 * inch
    iy = INS_Y - 0.16 * inch

    for i, (name, prefix, desc) in enumerate(INSERTS):
        row_bot = iy - INS_ROW_H
        if i % 2 == 0:
            c.setFillColor(BG)
            c.rect(ML - 3, row_bot, USABLE_W + 6, INS_ROW_H, stroke=0, fill=1)

        mid_y = iy - INS_ROW_H * 0.52

        c.setFillColor(INK); c.setFont("Helvetica-Bold", 8.5)
        c.drawString(ML, mid_y, name)

        c.setFont("Courier-Bold", 7.5); c.setFillColor(MID)
        c.drawString(ML + 1.15 * inch, mid_y, prefix)

        c.setFont("Helvetica", 7.5); c.setFillColor(MID)
        c.drawString(ML + 1.65 * inch, mid_y, desc[:72])

        c.setStrokeColor(RULE); c.setLineWidth(0.25)
        c.line(ML, row_bot, PAGE_W - MR, row_bot)

        iy -= INS_ROW_H

    _footer(c, "2025 Topps Signature Class  ·  Base only, no autos  ·  Chrome = same # but glossy stock  ·  eBay comps sparse — price cautiously")
    c.showPage()


# ---- Main ------------------------------------------------------------------

def main():
    c = canvas.Canvas(str(OUT), pagesize=letter)
    today = datetime.now().strftime("%B %d, %Y")
    _page_rookies(c, today)
    _page_vets_inserts(c, today)
    c.save()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
