"""
build_top10_post_pdf.py — 1-page B&W picking sheet: top 10 unlisted cards.
Shows CollX market value, eBay/SCI market estimate, and delta so you can
see where CollX over- or under-values a card before pricing the listing.

Loads multi-source pricing from output/top10_research_prices.json when
present. Re-run after updating that file to refresh pricing columns.

Run:
    python3 build_top10_post_pdf.py

Output: ~/Downloads/harpua2001_top10_post_<date>.pdf
"""
from __future__ import annotations

import csv
import json
import urllib.request
from datetime import datetime
from pathlib import Path

from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

import linkage_db

REPO    = Path(__file__).parent
OUT     = Path.home() / "Downloads" / f"harpua2001_top10_post_{datetime.now():%Y-%m-%d}.pdf"
CACHE   = Path("/tmp/top10_imgs")
CACHE.mkdir(exist_ok=True)

RESEARCH_PATH = REPO / "output" / "top10_research_prices.json"

PAGE_W, PAGE_H = letter
ML   = 0.45 * inch
MR   = 0.45 * inch
USABLE_W = PAGE_W - ML - MR

INK   = HexColor("#000000")
DARK  = HexColor("#1f1f1f")
MID   = HexColor("#555555")
LIGHT = HexColor("#9a9a9a")
RULE  = HexColor("#d0d0d0")
BG    = HexColor("#f3f3f3")
WHITE = white

# ---- image cache -----------------------------------------------------------

def _img(url: str):
    if not url:
        return None
    fname = CACHE / url.split("/")[-1].split("?")[0]
    if fname.is_file() and fname.stat().st_size > 0:
        return fname
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            fname.write_bytes(r.read())
        return fname
    except Exception:
        return None


# ---- data ------------------------------------------------------------------

def _top10() -> list[dict]:
    inv: dict[str, dict] = {}
    with (REPO / "inventory.csv").open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("collx_id"):
                inv[r["collx_id"]] = r

    # Load multi-source research prices if available
    research: dict[str, dict] = {}
    if RESEARCH_PATH.is_file():
        for rec in json.loads(RESEARCH_PATH.read_text()):
            research[rec["collx_id"]] = rec

    seen_names: set[str] = set()
    candidates: list[dict] = []
    for link in linkage_db.all_links():
        if link.get("status") != "unlisted":
            continue
        cid = link.get("collx_id", "")
        row = inv.get(cid)
        if not row:
            continue
        try:
            mv = float(row.get("collx_market_value") or 0)
        except (TypeError, ValueError):
            mv = 0.0
        key = f"{row.get('player','')}|{row.get('card_number','')}|{row.get('set','')}"
        if key in seen_names:
            continue
        seen_names.add(key)
        res = research.get(cid, {})
        ebay_est  = res.get("ebay_est")
        ebay_src  = res.get("ebay_source", "")
        candidates.append({
            "collx_id":    cid,
            "mv":          mv,
            "ebay_est":    ebay_est,
            "ebay_source": ebay_src,
            "player":      row.get("player", ""),
            "set":         row.get("set", ""),
            "card_number": row.get("card_number", ""),
            "parallel":    row.get("parallel", ""),
            "year":        row.get("year", ""),
            "sport":       row.get("sport", ""),
            "image_url":   row.get("image_url", ""),
            "name":        row.get("name", ""),
        })

    candidates.sort(key=lambda x: -x["mv"])
    return candidates[:10]


# ---- PDF -------------------------------------------------------------------

def _render(picks: list[dict]) -> None:
    c = canvas.Canvas(str(OUT), pagesize=letter)
    today = datetime.now().strftime("%B %d, %Y")

    # ---- header bar ----
    HDR_H = 0.72 * inch
    c.setFillColor(INK)
    c.rect(0, PAGE_H - HDR_H, PAGE_W, HDR_H, stroke=0, fill=1)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 15)
    c.drawString(ML, PAGE_H - 0.45 * inch, "Top 10 to Post")
    c.setFont("Helvetica", 9)
    c.setFillColor(HexColor("#bbbbbb"))
    c.drawRightString(PAGE_W - MR, PAGE_H - 0.45 * inch, today)

    # ---- sub-header ----
    SH_Y = PAGE_H - HDR_H - 0.22 * inch
    c.setFont("Helvetica", 8.5)
    c.setFillColor(MID)
    c.drawString(ML, SH_Y, "Unlisted cards ranked by CollX market value. Pull, sleeve, and post.")
    c.setFont("Helvetica-Bold", 8.5)
    total_mv = sum(p["mv"] for p in picks)
    c.drawRightString(PAGE_W - MR, SH_Y, f"CollX total  ${total_mv:.2f}")

    # ---- divider under sub-header ----
    DIV_Y = SH_Y - 0.12 * inch
    c.setStrokeColor(RULE)
    c.setLineWidth(0.5)
    c.line(ML, DIV_Y, PAGE_W - MR, DIV_Y)

    # ---- rows ----
    # available height from top of rows to bottom margin
    BOTTOM_MARGIN = 0.35 * inch
    row_area = DIV_Y - BOTTOM_MARGIN
    ROW_H = row_area / len(picks)   # fills page exactly

    IMG_W = ROW_H * 0.68
    IMG_H = ROW_H - 0.10 * inch
    IMG_PAD_L = 0.30 * inch   # space between left edge and thumbnail
    TEXT_X = ML + IMG_PAD_L + IMG_W + 0.10 * inch

    y = DIV_Y  # top of first row

    for idx, pick in enumerate(picks, 1):
        row_top = y
        row_bot = y - ROW_H

        # alternating background
        if idx % 2 == 0:
            c.setFillColor(BG)
            c.rect(ML - 4, row_bot, USABLE_W + 8, ROW_H, stroke=0, fill=1)

        # rank number
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 13)
        c.drawString(ML, row_top - ROW_H * 0.42, str(idx))

        # checkbox
        CB_X = ML + 0.18 * inch
        CB_Y = row_top - ROW_H * 0.55
        c.setFillColor(WHITE)
        c.setStrokeColor(INK)
        c.setLineWidth(1.2)
        c.rect(CB_X, CB_Y, 11, 11, stroke=1, fill=1)

        # thumbnail
        th_x = ML + IMG_PAD_L
        th_y = row_bot + (ROW_H - IMG_H) / 2
        c.setFillColor(BG)
        c.rect(th_x, th_y, IMG_W, IMG_H, stroke=0, fill=1)
        img_path = _img(pick["image_url"])
        if img_path:
            try:
                c.drawImage(str(img_path), th_x, th_y, width=IMG_W, height=IMG_H,
                            preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        c.setStrokeColor(INK)
        c.setLineWidth(0.4)
        c.rect(th_x, th_y, IMG_W, IMG_H, stroke=1, fill=0)

        # player name
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 10.5)
        player_y = row_top - ROW_H * 0.27
        c.drawString(TEXT_X, player_y, pick["player"][:40])

        # set + parallel
        sub_parts = []
        if pick["set"]:       sub_parts.append(pick["set"])
        if pick["card_number"]: sub_parts.append("#" + pick["card_number"])
        if pick["parallel"]:  sub_parts.append(pick["parallel"])
        c.setFont("Helvetica", 8.5)
        c.setFillColor(MID)
        c.drawString(TEXT_X, player_y - 13, "  ·  ".join(sub_parts)[:72])

        # sport tag
        c.setFont("Helvetica", 7.5)
        c.setFillColor(LIGHT)
        c.drawString(TEXT_X, player_y - 24, pick["sport"])

        # ---- price columns (right side) ----
        # Layout: [eBay est] ... [CollX] at far right
        # If ebay_est exists and diverges >20% from CollX, flag it.
        PRICE_Y = row_top - ROW_H * 0.30

        collx_mv  = pick["mv"]
        ebay_est  = pick.get("ebay_est")

        # CollX column (always shown, far right)
        COL_COLLX = PAGE_W - MR
        c.setFillColor(INK)
        c.setFont("Helvetica-Bold", 11)
        c.drawRightString(COL_COLLX, PRICE_Y, f"${collx_mv:.2f}")
        c.setFont("Helvetica", 7)
        c.setFillColor(LIGHT)
        c.drawRightString(COL_COLLX, PRICE_Y - 11, "CollX")

        # eBay est column (if available)
        if ebay_est is not None:
            COL_EBAY = PAGE_W - MR - 1.05 * inch
            delta_pct = (ebay_est - collx_mv) / collx_mv * 100 if collx_mv else 0
            # Color: red if eBay is >20% below CollX (CollX overvalued),
            #        green if eBay is >20% above (undervalued in CollX)
            if delta_pct < -20:
                price_color = HexColor("#cc2222")
            elif delta_pct > 20:
                price_color = HexColor("#1a7a1a")
            else:
                price_color = INK
            c.setFillColor(price_color)
            c.setFont("Helvetica-Bold", 11)
            c.drawRightString(COL_EBAY, PRICE_Y, f"${ebay_est:.2f}")
            c.setFont("Helvetica", 7)
            c.setFillColor(LIGHT)
            c.drawRightString(COL_EBAY, PRICE_Y - 11, "eBay est")
            # Delta badge
            sign = "+" if delta_pct >= 0 else ""
            badge_txt = f"{sign}{delta_pct:.0f}%"
            c.setFillColor(price_color)
            c.setFont("Helvetica-Bold", 7)
            c.drawRightString(COL_EBAY, PRICE_Y - 22, badge_txt)

        # row divider
        c.setStrokeColor(RULE)
        c.setLineWidth(0.35)
        c.line(ML, row_bot, PAGE_W - MR, row_bot)

        y -= ROW_H

    # ---- footer ----
    c.setFont("Helvetica-Oblique", 7.5)
    c.setFillColor(LIGHT)
    c.drawCentredString(PAGE_W / 2, 0.15 * inch, f"harpua2001  ·  generated {today}  ·  1 of 1")

    c.save()


def main() -> int:
    picks = _top10()
    if not picks:
        print("No unlisted cards found.")
        return 1
    print(f"Top {len(picks)} picks:")
    for i, p in enumerate(picks, 1):
        ebay = f"eBay~${p['ebay_est']:.2f}" if p.get("ebay_est") else "eBay~n/a"
        flag = ""
        if p.get("ebay_est") and p["mv"] > 0:
            d = (p["ebay_est"] - p["mv"]) / p["mv"] * 100
            if d < -20: flag = "  ** CollX HIGH"
            elif d > 20: flag = "  ** CollX LOW"
        print(f"  {i:2d}.  CollX=${p['mv']:.2f}  {ebay}  {p['player']:<28}  #{p['card_number']} {p['parallel']}{flag}")
    _render(picks)
    print(f"\nWrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
