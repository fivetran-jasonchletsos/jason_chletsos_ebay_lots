"""Pull sheet for the 5 three-card lots — readable layout.

JC asked for a sheet that's easy to read: big player name, the set, the card
type, and a LARGE color thumbnail per card so each exact card is easy to find.
Readability wins over fitting on one page (runs ~2 pages).

The per-card player/set/type fields are hand-curated from the eBay titles so
they're clean (only 15 cards) — see CARD_META keyed by item_id.
"""
import json
from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

REPO = Path(__file__).parent
THUMBS = REPO / "output/lot_thumbs"
lots = json.loads((REPO / "output/_lot_plan.json").read_text())
OUT = REPO / "output/lot_pull_sheet.pdf"

# player / set / card-type, curated from the eBay titles (keyed by item_id)
CARD_META = {
    "307006876717": ("Travis Hunter",     "2025 Panini Select",      "Future insert · RC · Jaguars"),
    "307000542321": ("Cam Ward",          "2025 Rookies & Stars",    "Base RC · Titans"),
    "306962131931": ("Ashton Jeanty",     "2025 Donruss Optic",      "Hidden Potential insert · RC · #5"),
    "307000541879": ("Cam Ward",          "2025 Rookies & Stars",    "Artistry in Motion insert · RC · Titans"),
    "306960322357": ("Shedeur Sanders",   "2025 Panini Mosaic",      "Rookie Variations · RC · #290"),
    "306956326197": ("Tyler Shough",      "2025 Panini Phoenix",     "Thunderbirds insert · RC · #37"),
    "307001106640": ("Tetairoa McMillan", "2025 Panini Select",      "Turbocharged insert · RC · Panthers"),
    "306999509860": ("Emeka Egbuka",      "2025 Panini Mosaic",      "Notoriety insert · RC · Buccaneers"),
    "306956768394": ("Matthew Golden",    "2025 Panini Phoenix",     "Paragon insert · RC · #13"),
    "306953130657": ("Patrick Mahomes",   "2025 Mahomes Collection", "Touchdown Architect insert · #TA-11"),
    "306999507089": ("Josh Allen",        "2025 Panini Select",      "Concourse base · Bills"),
    "306999472549": ("Lamar Jackson",     "2025 Panini Select",      "Premier Level base · #160 · Ravens"),
    "306998478666": ("Ashton Jeanty",     "2025 Panini Donruss",     "Rated Rookie · RC · #305 · Raiders"),
    "306999507035": ("Omarion Hampton",   "2025 Panini Select",      "Concourse · RC · Chargers"),
    "307007567600": ("Kyle Williams",     "2025 Panini Score",       "Rookie · RC · Patriots"),
}

PAGE_W, PAGE_H = letter
ML = 0.6 * inch
INK = HexColor("#111111"); MID = HexColor("#555555")
ACCENT = HexColor("#1a5fb4"); LINE = HexColor("#bbbbbb"); BG = HexColor("#f4f6f9")

ROW = 1.10 * inch          # generous row so the thumb + text breathe
THUMB_H = 0.96 * inch
BOTTOM = 0.4 * inch

c = canvas.Canvas(str(OUT), pagesize=letter)


def header():
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 18)
    c.drawString(ML, PAGE_H - 0.5*inch, "Lot Pull Sheet — 5 Lots / 15 Cards")
    c.setFillColor(MID); c.setFont("Helvetica", 9.5)
    c.drawString(ML, PAGE_H - 0.69*inch,
                 "JC2 Cards · pull these, then CC posts the lots + delists the singles")
    c.setStrokeColor(LINE); c.setLineWidth(0.8)
    c.line(ML, PAGE_H - 0.78*inch, PAGE_W - ML, PAGE_H - 0.78*inch)


header()
y = PAGE_H - 1.05*inch

# y is the TOP of the next element; everything draws downward from it.
for l in lots:
    # keep the whole lot together: need room for the band + all its card rows
    need = 0.40*inch + len(l["cards"]) * ROW + 0.16*inch
    if y - need < BOTTOM:
        c.showPage(); header(); y = PAGE_H - 1.05*inch

    # lot header band (top of band at y, drawn downward)
    BAND_H = 0.30*inch
    c.setFillColor(ACCENT)
    c.rect(ML, y - BAND_H, PAGE_W - 2*ML, BAND_H, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff")); c.setFont("Helvetica-Bold", 12.5)
    c.drawString(ML + 0.10*inch, y - 0.21*inch, f"LOT {l['rank']}:  {l['theme']}")
    c.drawRightString(PAGE_W - ML - 0.10*inch, y - 0.21*inch, f"List ${l['lot_price']:.2f}")
    y -= BAND_H + 0.10*inch

    for card in l["cards"]:
        player, setname, ctype = CARD_META.get(
            card["item_id"], (card["title"][:30], "", ""))

        top = y                       # top of this card row
        bot = y - ROW

        # row background for readability
        c.setFillColor(BG)
        c.rect(ML, bot + 0.04*inch, PAGE_W - 2*ML, ROW - 0.08*inch, fill=1, stroke=0)

        # checkbox (upper-left of the row)
        c.setStrokeColor(INK); c.setLineWidth(1.3); c.setFillColor(HexColor("#ffffff"))
        c.rect(ML + 0.08*inch, top - 0.34*inch, 0.24*inch, 0.24*inch, fill=1, stroke=1)

        # large color thumbnail, vertically centered in the row
        timg = THUMBS / f"{card['item_id']}.jpg"
        tx = ML + 0.45*inch
        thumb_w = 0.72 * inch
        thumb_bot = bot + (ROW - THUMB_H) / 2
        if timg.is_file():
            try:
                img = ImageReader(str(timg))
                iw, ih = img.getSize()
                w = THUMB_H * (iw / ih)
                c.drawImage(img, tx, thumb_bot, width=w, height=THUMB_H,
                            preserveAspectRatio=True, mask='auto')
                thumb_w = w
            except Exception:
                pass

        # text block to the right of the thumb
        text_x = tx + thumb_w + 0.22*inch
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 17)
        c.drawString(text_x, top - 0.34*inch, player)
        c.setFillColor(ACCENT); c.setFont("Helvetica-Bold", 11.5)
        c.drawString(text_x, top - 0.56*inch, setname)
        c.setFillColor(MID); c.setFont("Helvetica", 10.5)
        c.drawString(text_x, top - 0.74*inch, ctype)
        c.setFillColor(MID); c.setFont("Helvetica", 9)
        c.drawString(text_x, top - 0.92*inch,
                     f"single ${card['price']}  ·  item {card['item_id']}")
        y -= ROW
    y -= 0.16*inch

c.showPage(); c.save()
print(f"wrote {OUT}")
