"""Printable B&W pull-aside checklist of cards the automation listed to eBay,
filtered through three integrity gates so Jason isn't sent chasing dead
listings or cards that are already live under a different title.

Gates (in order):
  1. LINKAGE — eBay item must currently be status='live' in linkage_db.
     If status is 'ended' or 'sold', the card doesn't need pulling.
  2. INVENTORY — the collx_id must still be present in inventory.csv.
     If the row vanished from CollX, the card may already be gone.
  3. DUPLICATE — scan output/listings_snapshot.json for another listing
     where the title contains the same player + card number. If hit, the
     auto-pushed card is probably a duplicate of something already live.
     Route to a REVIEW section, do not silently drop.

Rows that fail a gate land in a "do not blindly pull — review first"
appendix at the back of the PDF instead of being silently dropped, so
Jason can see what got filtered and confirm.

Memory rules honored: black & white only, dense rows, no full-page
worksheets, no pipes/markdown tables in user-facing prose.
"""
from __future__ import annotations
import csv
import json
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.lib.colors import HexColor, white

import linkage_db

REPO = Path(__file__).parent
OUT  = Path.home() / "Downloads" / f"harpua2001_pull_aside_{datetime.now():%Y-%m-%d}.pdf"

CACHE_DIR = Path("/tmp/pull_aside_imgs")
CACHE_DIR.mkdir(exist_ok=True)


# ---- candidate gathering ---------------------------------------------------

def gather_batch_pushes():
    """Pull every successful push from output/push_to_ebay_batch_log.json plus
    single-card pushes from push_to_ebay_log.json. Returns list of dicts.
    Missing log files are NOT an error — fresh checkout, or before the first
    push has ever run. Just skip the absent file."""
    rows = []
    batch_path = REPO / "output/push_to_ebay_batch_log.json"
    if batch_path.is_file():
        batch = json.loads(batch_path.read_text())
        for b in batch:
            for r in b.get("results", []):
                if r.get("status") == "success" and r.get("item_id"):
                    rows.append({
                        "ebay_item_id": str(r["item_id"]),
                        "collx_id":     r.get("collx_id", ""),
                        "title":        r.get("title", ""),
                        "price":        float(r.get("price") or 0),
                        "listed_at":    b.get("started_at", ""),
                        "source":       f"batch {b.get('started_at','')[:10]}",
                    })

    single_path = REPO / "output/push_to_ebay_log.json"
    if single_path.is_file():
        single = json.loads(single_path.read_text())
        if isinstance(single, list):
            for s in single:
                if s.get("ack") == "Success" and s.get("item_id"):
                    rows.append({
                        "ebay_item_id": str(s["item_id"]),
                        "collx_id":     s.get("collx_id", ""),
                        "title":        s.get("title", ""),
                        "price":        float(s.get("price") or 0),
                        "listed_at":    s.get("started_at") or s.get("timestamp", ""),
                        "source":       "single push",
                    })
    # Dedupe by item_id
    seen, uniq = set(), []
    for r in rows:
        if r["ebay_item_id"] not in seen:
            seen.add(r["ebay_item_id"])
            uniq.append(r)
    return uniq


def card_number_from_title(title: str) -> str | None:
    """Pull a '#NNN' or '#A-NNN' token if present."""
    m = re.search(r'#([A-Za-z]{0,5}-?\d+)', title)
    return m.group(1) if m else None


def player_token_from_inv(row: dict) -> str:
    return (row.get("player") or "").strip().lower()


# ---- gates -----------------------------------------------------------------

def gate(rows, inv_by_cid, links_by_ebay, snapshot_listings):
    """Apply the three gates. Returns (pull_now, review_appendix)."""
    pull_now = []
    review = []

    for r in rows:
        cid = r["collx_id"]
        item_id = r["ebay_item_id"]
        inv_row = inv_by_cid.get(cid) or {}
        link = links_by_ebay.get(item_id)

        # ---- GATE 1: linkage status ----
        if link and link.get("status") in ("ended", "sold", "removed_from_collx"):
            r["filter_reason"] = f"linkage_db: status={link['status']} (no longer live)"
            review.append(r); continue

        # ---- GATE 2: inventory presence ----
        if not inv_row:
            r["filter_reason"] = "collx_id no longer in inventory.csv"
            review.append(r); continue

        # Carry enrichment forward
        r["set"]          = inv_row.get("set", "")
        r["parallel"]     = inv_row.get("parallel", "")
        r["card_number"]  = inv_row.get("card_number", "")
        r["player"]       = inv_row.get("player", "")
        r["image_url"]    = inv_row.get("image_url", "")
        r["collx_market"] = inv_row.get("collx_market_value", "")

        # ---- GATE 3: duplicate detection in live snapshot ----
        # Match heuristic: player name appears as a whole word in the eBay title
        # AND the FULL card number appears (e.g. "#BDC-50", not just "#50"). The
        # old short-suffix fallback over-matched: card "BDC-50" used to collide
        # with any "#50" in the same player's other parallels.
        player_lc = player_token_from_inv(inv_row)
        card_num  = (inv_row.get("card_number") or "").strip()
        if not card_num:
            card_num = card_number_from_title(r["title"]) or ""
        dupes = []
        if player_lc and card_num:
            needle_num = f"#{card_num}".lower()
            # \b player_lc \b — whole-word match prevents "Drake" matching "Drake London".
            player_re = re.compile(rf"\b{re.escape(player_lc)}\b")
            for l in snapshot_listings:
                if str(l.get("item_id")) == item_id:
                    continue  # don't match against self
                t = (l.get("title") or "").lower()
                if player_re.search(t) and needle_num in t:
                    dupes.append({
                        "item_id": str(l.get("item_id")),
                        "title":   l.get("title", ""),
                        "price":   l.get("price"),
                    })
        if dupes:
            r["dupes"] = dupes
            r["filter_reason"] = f"possible duplicate of existing live listing(s)"
            review.append(r); continue

        # CollX stock-photo warning (not a gate, just a tag)
        img = inv_row.get("image_url", "")
        if img and re.search(r'-(btox|front|stock)\.jpg$', img):
            r["stock_photo_warning"] = "CollX catalog stock photo, not a user upload — visually confirm before sleeving"

        pull_now.append(r)

    # Highest price first inside each bucket
    pull_now.sort(key=lambda x: -x["price"])
    review.sort(key=lambda x: -x["price"])
    return pull_now, review


# ---- image cache ----------------------------------------------------------

def cache_img(url):
    if not url: return None
    fname = CACHE_DIR / (url.split("/")[-1].split("?")[0])
    if fname.is_file() and fname.stat().st_size > 0:
        return fname
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            fname.write_bytes(resp.read())
        return fname
    except Exception:
        return None


# ---- PDF render (B&W, dense rows) -----------------------------------------

INK   = HexColor("#000000")
DARK  = HexColor("#1f1f1f")
MID   = HexColor("#555555")
LIGHT = HexColor("#9a9a9a")
RULE  = HexColor("#cccccc")
BG    = HexColor("#f5f5f5")
WHITE = white

PAGE_W, PAGE_H = letter
ML = 0.5 * inch
MR = 0.5 * inch
ROW_H = 0.78 * inch

def header(c, title, today):
    c.setFillColor(INK); c.rect(0, PAGE_H - 0.8 * inch, PAGE_W, 0.8 * inch, stroke=0, fill=1)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 16)
    c.drawString(ML, PAGE_H - 0.42 * inch, title)
    c.setFont("Helvetica", 9); c.setFillColor(HexColor("#bbbbbb"))
    c.drawRightString(PAGE_W - MR, PAGE_H - 0.42 * inch, today)

def render_table_row(c, y, idx, card):
    row_top = y
    row_bottom = y - ROW_H

    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
    c.drawString(ML, row_top - 18, str(idx))

    # checkbox
    cb_x = ML + 0.25 * inch
    cb_y = row_top - 22
    c.setStrokeColor(INK); c.setFillColor(WHITE); c.setLineWidth(1.2)
    c.rect(cb_x, cb_y, 12, 12, stroke=1, fill=1)

    # thumb
    th_x = ML + 0.48 * inch
    th_y = row_bottom + 4
    th_h = ROW_H - 8
    th_w = th_h * 0.72
    c.setFillColor(BG); c.rect(th_x, th_y, th_w, th_h, stroke=0, fill=1)
    img = cache_img(card.get("image_url", ""))
    if img and Path(img).is_file():
        try:
            c.drawImage(str(img), th_x, th_y, width=th_w, height=th_h,
                        preserveAspectRatio=True, mask='auto')
        except Exception: pass
    c.setStrokeColor(INK); c.setLineWidth(0.5)
    c.rect(th_x, th_y, th_w, th_h, stroke=1, fill=0)

    # title + sub
    tx = th_x + th_w + 10
    title = card["title"]
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 10.5)
    c.drawString(tx, row_top - 14, title[:58] + ("…" if len(title) > 58 else ""))

    c.setFont("Helvetica", 8.5); c.setFillColor(MID)
    sub_parts = []
    if card.get("player"):      sub_parts.append(card["player"])
    if card.get("card_number"): sub_parts.append("#" + card["card_number"])
    if card.get("parallel"):    sub_parts.append(card["parallel"])
    c.drawString(tx, row_top - 28, "  ·  ".join(sub_parts)[:75])

    # stock-photo warning if present
    if card.get("stock_photo_warning"):
        c.setFillColor(LIGHT); c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(tx, row_top - 40, "verify visually — CollX stock photo")

    # price + item id columns (right side)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 11)
    c.drawRightString(ML + 5.3 * inch, row_top - 18, f"${card['price']:.2f}")
    c.setFont("Courier-Bold", 9); c.setFillColor(DARK)
    c.drawString(ML + 5.5 * inch, row_top - 18, "item:")
    c.drawString(ML + 6.0 * inch, row_top - 18, card["ebay_item_id"])
    c.setFont("Helvetica", 7.5); c.setFillColor(MID)
    c.drawString(ML + 5.5 * inch, row_top - 30, "WRITE ON SLEEVE")

    # divider
    c.setStrokeColor(RULE); c.setLineWidth(0.4)
    c.line(ML, row_bottom, PAGE_W - MR, row_bottom)

def render_review_row(c, y, idx, card):
    """Slightly taller — needs space for the duplicate / filter reason."""
    row_top = y
    row_h = 1.05 * inch
    row_bottom = y - row_h

    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
    c.drawString(ML, row_top - 18, str(idx))

    th_x = ML + 0.45 * inch
    th_y = row_bottom + 6
    th_h = row_h - 12
    th_w = th_h * 0.72
    c.setFillColor(BG); c.rect(th_x, th_y, th_w, th_h, stroke=0, fill=1)
    img = cache_img(card.get("image_url", ""))
    if img and Path(img).is_file():
        try:
            c.drawImage(str(img), th_x, th_y, width=th_w, height=th_h,
                        preserveAspectRatio=True, mask='auto')
        except Exception: pass
    c.setStrokeColor(INK); c.setLineWidth(0.5)
    c.rect(th_x, th_y, th_w, th_h, stroke=1, fill=0)

    tx = th_x + th_w + 10
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 10.5)
    c.drawString(tx, row_top - 14, card["title"][:58] + ("…" if len(card["title"]) > 58 else ""))

    c.setFont("Helvetica-Bold", 8.5); c.setFillColor(INK)
    c.drawString(tx, row_top - 28, f"reason: {card.get('filter_reason','')}")

    if card.get("dupes"):
        c.setFont("Helvetica", 8.5); c.setFillColor(DARK)
        for i, d in enumerate(card["dupes"][:2]):
            dprice = f"${d['price']:.2f}" if isinstance(d.get("price"), (int, float)) else ""
            c.drawString(tx, row_top - 42 - (i * 12),
                         f"  already on eBay: item {d['item_id']} {dprice}  {d['title'][:48]}")

    # right-side metadata
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 11)
    c.drawRightString(ML + 5.3 * inch, row_top - 18, f"${card['price']:.2f}")
    c.setFont("Courier", 8); c.setFillColor(MID)
    c.drawString(ML + 5.5 * inch, row_top - 18, f"item {card['ebay_item_id']}")
    c.drawString(ML + 5.5 * inch, row_top - 30, f"collx {card['collx_id']}")

    c.setStrokeColor(RULE); c.setLineWidth(0.4)
    c.line(ML, row_bottom, PAGE_W - MR, row_bottom)

    return row_h


# ---- main -----------------------------------------------------------------

def main() -> int:
    rows = gather_batch_pushes()
    # Use a `with` block so the file handle closes deterministically.
    inv_csv_path = REPO / "inventory.csv"
    if not inv_csv_path.is_file():
        print(f"NOTE: {inv_csv_path} missing; pull-aside cannot enrich rows.")
        inv = {}
    else:
        with inv_csv_path.open(newline="", encoding="utf-8") as f:
            inv = {r["collx_id"]: r for r in csv.DictReader(f) if r.get("collx_id")}

    # If multiple linkage rows share an ebay_item_id (no UNIQUE constraint),
    # keep the NEWEST (latest updated_at) so Gate 1 reads current status, not
    # a stale row.
    links = {}
    for l in linkage_db.all_links():
        eid = l.get("ebay_item_id")
        if not eid:
            continue
        cur = links.get(eid)
        if cur is None or (l.get("updated_at") or "") > (cur.get("updated_at") or ""):
            links[eid] = l

    snap_path = REPO / "output/listings_snapshot.json"
    if not snap_path.is_file():
        print(f"NOTE: {snap_path} missing; duplicate-gate cannot run.")
        snapshot_listings = []
    else:
        snap = json.loads(snap_path.read_text())
        snapshot_listings = snap.get("listings", []) if isinstance(snap, dict) else (snap or [])

    pull_now, review = gate(rows, inv, links, snapshot_listings)

    c = canvas.Canvas(str(OUT), pagesize=letter)
    today = datetime.now().strftime("%b %d, %Y")

    # COVER
    c.setFillColor(WHITE); c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    c.setFillColor(INK); c.rect(0, PAGE_H - 1.5 * inch, PAGE_W, 1.1 * inch, stroke=0, fill=1)
    c.setFillColor(WHITE); c.setFont("Helvetica-Bold", 26)
    c.drawString(ML, PAGE_H - 1.0 * inch, "Pull these cards aside.")
    c.setFont("Helvetica", 11); c.setFillColor(HexColor("#bbbbbb"))
    c.drawString(ML, PAGE_H - 1.3 * inch, f"Filtered against linkage, inventory, and live eBay duplicates  ·  {today}")

    c.setFillColor(INK); c.setFont("Helvetica-Bold", 11)
    y = PAGE_H - 1.95 * inch
    c.drawString(ML, y, "WHAT'S IN THIS PACKET")
    y -= 18
    c.setFont("Helvetica", 10.5); c.setFillColor(DARK)
    total_in = len(rows)
    pull_v = sum(x["price"] for x in pull_now)
    rev_v  = sum(x["price"] for x in review)
    bullets = [
        f"Section 1 (pull): {len(pull_now)} cards passed all three integrity gates. Combined value ${pull_v:.2f}.",
        f"Section 2 (review): {len(review)} cards failed a gate. DO NOT blindly pull — confirm first.",
        f"Started with {total_in} successful pushes total ({total_in - len(pull_now) - len(review)} duplicates skipped before filtering).",
        "Each row shows the eBay item ID — write it on the sleeve.",
        "Stock-photo warning on a row means CollX matched by catalog, not your photo. Verify visually.",
    ]
    for b in bullets:
        c.drawString(ML, y, "- " + b); y -= 14
    y -= 8

    c.setFont("Helvetica-Bold", 11); c.setFillColor(INK)
    c.drawString(ML, y, "WHY THIS REPLACED THE OLD PULL LIST")
    y -= 18
    c.setFont("Helvetica", 10); c.setFillColor(DARK)
    notes = [
        "Old list trusted the batch push log as ground truth. It included ended listings,",
        "duplicates of cards already live, and cards possibly miss-scanned by CollX catalog match.",
        "Two reviewers flagged the same flaw on 2026-05-29 after Jason caught the Micah Parsons",
        "duplicate and could not find the Tetairoa McMillan Pyramids /85 in his physical pile.",
    ]
    for n in notes:
        c.drawString(ML, y, n); y -= 13

    c.setFont("Helvetica-Oblique", 9); c.setFillColor(MID)
    c.drawCentredString(PAGE_W / 2, 0.35 * inch, "Page 1  ·  Cover")
    c.showPage()

    # SECTION 1 — PULL NOW
    page_num = 2
    if pull_now:
        header(c, f"Section 1  ·  Pull these ({len(pull_now)})", today)
        y = PAGE_H - 1.05 * inch
        for i, card in enumerate(pull_now, 1):
            if y - ROW_H < 0.55 * inch:
                c.setFillColor(MID); c.setFont("Helvetica-Oblique", 9)
                c.drawCentredString(PAGE_W / 2, 0.35 * inch, f"Page {page_num}  ·  Section 1")
                c.showPage()
                page_num += 1
                header(c, f"Section 1  ·  Pull these (continued)", today)
                y = PAGE_H - 1.05 * inch
            render_table_row(c, y, i, card)
            y -= ROW_H + 2
        c.setFillColor(MID); c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(PAGE_W / 2, 0.35 * inch, f"Page {page_num}  ·  Section 1")
        c.showPage()
        page_num += 1

    # SECTION 2 — REVIEW APPENDIX
    if review:
        header(c, f"Section 2  ·  Review before pulling ({len(review)})", today)
        c.setFont("Helvetica", 10.5); c.setFillColor(DARK)
        c.drawString(ML, PAGE_H - 1.0 * inch,
                     "These rows failed an integrity gate. Look at each before sleeving anything.")
        y = PAGE_H - 1.35 * inch
        for i, card in enumerate(review, 1):
            if y - 1.1 * inch < 0.55 * inch:
                c.setFillColor(MID); c.setFont("Helvetica-Oblique", 9)
                c.drawCentredString(PAGE_W / 2, 0.35 * inch, f"Page {page_num}  ·  Section 2")
                c.showPage()
                page_num += 1
                header(c, f"Section 2  ·  Review (continued)", today)
                y = PAGE_H - 1.05 * inch
            used = render_review_row(c, y, i, card)
            y -= used + 4
        c.setFillColor(MID); c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(PAGE_W / 2, 0.35 * inch, f"Page {page_num}  ·  Section 2")
        c.showPage()

    c.save()
    print(f"Wrote {OUT}")
    print(f"  Section 1 (pull):   {len(pull_now)} cards, ${pull_v:.2f}")
    print(f"  Section 2 (review): {len(review)} cards, ${rev_v:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
