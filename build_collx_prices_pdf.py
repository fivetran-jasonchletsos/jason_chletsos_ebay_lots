"""
build_collx_prices_pdf.py — one-page CollX price sheet for the top-10 cards.

Recommended prices (from sold-comp research) to enter into CollX while scanning
the top cards in. Output: ~/Downloads/harpua2001_collx_prices_<date>.pdf
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

OUT = Path.home() / "Downloads" / f"harpua2001_collx_prices_{datetime.now():%Y-%m-%d}.pdf"

INK   = HexColor("#1a1a1a")
GOLD  = HexColor("#b8860b")
GREEN = HexColor("#1d7a3f")
RED   = HexColor("#b03030")
GREY  = HexColor("#777777")
LINE  = HexColor("#d8d8d8")
BG    = HexColor("#f4f1ea")

# (rank, card, detail, item_id, current, collx, note)
ROWS = [
    (1,  "Dak Prescott",    "Roses Acetate SSP",             "307010502095",  99.99, 39.99, "Same acetate case-hit tier as Burrow (which just sold at $44.99)."),
    (2,  "Omarion Hampton", "First Class SSP RC",            "307005018631",  81.99, 29.99, "First Class acetate; even his auto RCs sell $25-32 raw."),
    (3,  "Matthew Golden",  "RC On-Card Auto #212/225",      "307006595551",  71.24, 44.99, "Chrome /299 auto sold $60; this sits below. /225 raw $35-50."),
    (4,  "Jalen Milroe",    "Saturday Stars Auto Green /25",  "307003202154",  51.99, 34.99, "Auto market soft; base auto ~$20. Sub-$40 to convert."),
    (5,  "C.J. Stroud",     "Class Action 10/10 (1-of-10)",  "307006881230",  47.49, 39.99, "True 1/10, but Stroud's market cooled; modest /10 premium."),
    (6,  "Xavier Worthy",   "Red /25 (base, confirmed)",     "307004744383",  36.99, 14.99, "Confirmed base Red /25, not an auto. Keep printed Round/Pick as-is."),
    (7,  "Jackson Hawes",   "RC Auto /100",                  "307010510968",  34.99, 14.99, "5th-round TE; negligible demand even at /100."),
    (8,  "Brock Bowers",    "Orange 12/50 (non-auto)",       "307010519828",  28.99, 14.99, "2nd-year (not RC); base /50. The $275 comp is the AUTO, not this."),
    (9,  "Tony Mandarich",  "Preeminent Ink Auto",           "307004744178",  25.99,  9.99, "Base auto, draft-bust name, no premium. Floor ~$7."),
]


def money(x): return f"${x:,.2f}"


def main():
    PW, PH = letter
    ML, MR = 0.55 * inch, 0.55 * inch
    c = canvas.Canvas(str(OUT), pagesize=letter)

    # header
    HDR = 0.95 * inch
    c.setFillColor(INK); c.rect(0, PH - HDR, PW, HDR, stroke=0, fill=1)
    c.setFillColor(white); c.setFont("Helvetica-Bold", 22)
    c.drawString(ML, PH - 0.52 * inch, "CollX Price Sheet — Top Cards")
    c.setFont("Helvetica", 10); c.setFillColor(HexColor("#cfcfcf"))
    c.drawString(ML, PH - 0.74 * inch, "Recommended prices to enter into CollX (from sold-comp research)")
    c.setFont("Helvetica", 9)
    c.drawRightString(PW - MR, PH - 0.52 * inch, datetime.now().strftime("%b %d, %Y"))
    c.drawRightString(PW - MR, PH - 0.74 * inch, "harpua2001")

    # column x positions
    X_RANK = ML
    X_CARD = ML + 0.30 * inch
    X_CUR  = PW - MR - 1.55 * inch
    X_NEW  = PW - MR - 0.05 * inch

    y = PH - HDR - 0.34 * inch
    c.setFont("Helvetica-Bold", 8.5); c.setFillColor(GREY)
    c.drawString(X_CARD, y, "CARD")
    c.drawRightString(X_CUR, y, "WAS")
    c.drawRightString(X_NEW, y, "COLLX PRICE")
    y -= 0.10 * inch
    c.setStrokeColor(INK); c.setLineWidth(1.2); c.line(ML, y, PW - MR, y)
    y -= 0.26 * inch

    tot_cur = tot_new = 0.0
    for rank, card, detail, iid, cur, new, note in ROWS:
        tot_cur += cur; tot_new += new
        # rank
        c.setFillColor(GOLD); c.setFont("Helvetica-Bold", 13)
        c.drawString(X_RANK, y - 2, str(rank))
        # card + detail
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
        c.drawString(X_CARD, y, card)
        c.setFillColor(GREY); c.setFont("Helvetica", 9)
        c.drawString(X_CARD, y - 12, detail)
        c.setFillColor(HexColor("#999999")); c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(X_CARD, y - 23, note[:96])
        # prices
        c.setFillColor(RED); c.setFont("Helvetica", 10)
        c.drawRightString(X_CUR, y - 2, money(cur))
        # strike-through on the old price
        wcur = c.stringWidth(money(cur), "Helvetica", 10)
        c.setStrokeColor(RED); c.setLineWidth(0.8)
        c.line(X_CUR - wcur, y + 1, X_CUR, y + 1)
        c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 15)
        c.drawRightString(X_NEW, y - 3, money(new))
        # row divider
        y -= 0.46 * inch
        c.setStrokeColor(LINE); c.setLineWidth(0.6); c.line(ML, y + 0.12 * inch, PW - MR, y + 0.12 * inch)

    # totals
    y -= 0.06 * inch
    c.setStrokeColor(INK); c.setLineWidth(1.2); c.line(ML, y + 0.18 * inch, PW - MR, y + 0.18 * inch)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
    c.drawString(X_CARD, y, "TOTAL")
    c.setFillColor(RED); c.setFont("Helvetica", 11)
    c.drawRightString(X_CUR, y, money(tot_cur))
    wt = c.stringWidth(money(tot_cur), "Helvetica", 11)
    c.setStrokeColor(RED); c.line(X_CUR - wt, y + 2, X_CUR, y + 2)
    c.setFillColor(GREEN); c.setFont("Helvetica-Bold", 16)
    c.drawRightString(X_NEW, y - 1, money(tot_new))

    # footer note
    c.setFillColor(GREY); c.setFont("Helvetica-Oblique", 8)
    c.drawString(ML, 0.55 * inch,
                 "Prices triangulated from recent eBay sold comps / SportsCardsPro (June 2026). "
                 "Burrow & Dak already repriced live on eBay. New June-2026 product, so comps are thin — revisit in 1-2 weeks.")
    c.drawString(ML, 0.40 * inch,
                 "Tip: enable Best Offer; accept ~10-15% under list. Worthy #7 — verify whether it's the base Red /25 or the auto before pricing.")

    c.showPage(); c.save()
    print(f"Wrote {OUT}  (was {money(tot_cur)} -> CollX {money(tot_new)})")


if __name__ == "__main__":
    main()
