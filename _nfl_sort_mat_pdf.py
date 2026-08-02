"""Printable NFL team-sort mat for physical (not-yet-listed) card inventory.
One page per division (8 pages), 2x2 grid of team zones per page -- JC lays
the page on the table and stacks cards for each team in its zone.
Output -> output/nfl_sort_mat.pdf, copied to ~/Downloads."""
import shutil
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white, black
from reportlab.pdfgen import canvas

OUT = Path("output/nfl_sort_mat.pdf")
PAGE_W, PAGE_H = letter

DIVISIONS = [
    ("AFC East",  [("Bills", "Buffalo", "#00338D"), ("Dolphins", "Miami", "#008E97"),
                   ("Patriots", "New England", "#002244"), ("Jets", "New York", "#125740")]),
    ("AFC North", [("Ravens", "Baltimore", "#241773"), ("Bengals", "Cincinnati", "#FB4F14"),
                   ("Browns", "Cleveland", "#311D00"), ("Steelers", "Pittsburgh", "#FFB612")]),
    ("AFC South", [("Texans", "Houston", "#03202F"), ("Colts", "Indianapolis", "#002C5F"),
                   ("Jaguars", "Jacksonville", "#006778"), ("Titans", "Tennessee", "#0C2340")]),
    ("AFC West",  [("Broncos", "Denver", "#FB4F14"), ("Chiefs", "Kansas City", "#E31837"),
                   ("Raiders", "Las Vegas", "#000000"), ("Chargers", "Los Angeles", "#0080C6")]),
    ("NFC East",  [("Cowboys", "Dallas", "#041E42"), ("Giants", "New York", "#0B2265"),
                   ("Eagles", "Philadelphia", "#004C54"), ("Commanders", "Washington", "#5A1414")]),
    ("NFC North", [("Bears", "Chicago", "#0B162A"), ("Lions", "Detroit", "#0076B6"),
                   ("Packers", "Green Bay", "#203731"), ("Vikings", "Minnesota", "#4F2683")]),
    ("NFC South", [("Falcons", "Atlanta", "#A71930"), ("Panthers", "Carolina", "#0085CA"),
                   ("Saints", "New Orleans", "#D3BC8D"), ("Buccaneers", "Tampa Bay", "#D50A0A")]),
    ("NFC West",  [("Cardinals", "Arizona", "#97233F"), ("Rams", "Los Angeles", "#003594"),
                   ("49ers", "San Francisco", "#AA0000"), ("Seahawks", "Seattle", "#002244")]),
]

MARGIN = 0.5 * inch
GRID_TOP = PAGE_H - 1.15 * inch
GRID_BOTTOM = MARGIN
GRID_LEFT = MARGIN
GRID_RIGHT = PAGE_W - MARGIN
GUTTER = 0.25 * inch

CELL_W = (GRID_RIGHT - GRID_LEFT - GUTTER) / 2
CELL_H = (GRID_TOP - GRID_BOTTOM - GUTTER) / 2
BAR_H = 0.62 * inch


def readable_text_color(hex_color):
    c = HexColor(hex_color)
    lum = 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue
    return black if lum > 0.55 else white


def draw_page(c, conf_div, teams, page_no, total_pages):
    conf, div = conf_div.split(" ", 1)
    c.setFillColor(HexColor("#0b1b3a"))
    c.setFont("Helvetica-Bold", 20)
    c.drawString(MARGIN, PAGE_H - 0.65 * inch, f"{conf} {div}")
    c.setFont("Helvetica", 10)
    c.setFillColor(HexColor("#667"))
    c.drawString(MARGIN, PAGE_H - 0.85 * inch,
                 "NFL Team Sort Mat -- place non-eBay physical cards in each team's zone")
    c.drawRightString(PAGE_W - MARGIN, PAGE_H - 0.65 * inch, f"Page {page_no} of {total_pages}")

    positions = [(GRID_LEFT, GRID_TOP - CELL_H),
                 (GRID_LEFT + CELL_W + GUTTER, GRID_TOP - CELL_H),
                 (GRID_LEFT, GRID_BOTTOM),
                 (GRID_LEFT + CELL_W + GUTTER, GRID_BOTTOM)]

    for (x, y), (name, city, hexcolor) in zip(positions, teams):
        c.setStrokeColor(HexColor("#ccd"))
        c.setLineWidth(1.5)
        c.rect(x, y, CELL_W, CELL_H, stroke=1, fill=0)

        c.setFillColor(HexColor(hexcolor))
        c.rect(x, y + CELL_H - BAR_H, CELL_W, BAR_H, stroke=0, fill=1)
        text_color = readable_text_color(hexcolor)
        c.setFillColor(text_color)
        c.setFont("Helvetica-Bold", 22)
        c.drawString(x + 0.2 * inch, y + CELL_H - BAR_H + 0.22 * inch, name)
        c.setFont("Helvetica", 11)
        c.drawString(x + 0.2 * inch, y + CELL_H - BAR_H + 0.06 * inch, city)

        c.setFillColor(HexColor("#aab"))
        c.setFont("Helvetica-Oblique", 9)
        c.drawCentredString(x + CELL_W / 2, y + 0.18 * inch, "(place cards here)")


def build():
    c = canvas.Canvas(str(OUT), pagesize=letter)
    total = len(DIVISIONS)
    for i, (div_name, teams) in enumerate(DIVISIONS, 1):
        draw_page(c, div_name, teams, i, total)
        c.showPage()
    c.save()
    print(f"wrote {OUT} ({total} pages)")

    dl = Path.home() / "Downloads" / "nfl_sort_mat.pdf"
    shutil.copy(OUT, dl)
    print(f"copied to {dl}")


if __name__ == "__main__":
    build()
