"""Printable pull list for the next-10 sourcing targets. Big numbered names,
grayscale, ~5 per page — per JC's pull-list style (simple names, not dense)."""
import json
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.pdfgen import canvas

REPO = Path(__file__).parent
targets = json.loads((REPO / "output/sourcing_targets.json").read_text())["targets"]

OUT = REPO / "output/pull_list_targets_june2026.pdf"
PAGE_W, PAGE_H = letter
ML = 0.9 * inch
INK = HexColor("#000000"); MID = HexColor("#666666")
PER_PAGE = 10  # all 10 on one page

c = canvas.Canvas(str(OUT), pagesize=letter)

def header(page_no, pages):
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 22)
    c.drawString(ML, PAGE_H - 0.7 * inch, "Sourcing Pull List — Next 10 Targets")
    c.setFillColor(MID); c.setFont("Helvetica", 9)
    c.drawString(ML, PAGE_H - 0.92 * inch, f"JC2 Cards · pull/buy priority · page {page_no} of {pages}")
    c.setStrokeColor(MID); c.setLineWidth(0.5)
    c.line(ML, PAGE_H - 1.02 * inch, PAGE_W - ML, PAGE_H - 1.02 * inch)

pages = (len(targets) + PER_PAGE - 1) // PER_PAGE
top0 = PAGE_H - 1.45 * inch
row_h = (top0 - 0.55 * inch) / PER_PAGE

for i, t in enumerate(targets):
    slot = i % PER_PAGE
    if slot == 0:
        if i: c.showPage()
        header(i // PER_PAGE + 1, pages)
    y = top0 - slot * row_h
    # big number — readable without reading glasses
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 36)
    c.drawString(ML, y - 30, f"{t['rank']}.")
    # big name
    c.setFont("Helvetica-Bold", 36)
    c.drawString(ML + 0.72 * inch, y - 30, t["player"])
    # subtitle: position · team · tier (still comfortably readable)
    c.setFillColor(MID); c.setFont("Helvetica", 14)
    c.drawString(ML + 0.72 * inch, y - 50, f"{t['position']} · {t['team']} · {t['tier']}")
    # checkbox
    c.setStrokeColor(INK); c.setLineWidth(1.4)
    c.rect(PAGE_W - ML - 0.40 * inch, y - 38, 0.34 * inch, 0.34 * inch)

c.showPage(); c.save()
print(f"wrote {OUT} ({pages} pages, {len(targets)} names)")
