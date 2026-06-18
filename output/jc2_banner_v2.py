from PIL import Image, ImageDraw, ImageFont
import os, math

W, H = 1200, 270
OUT = os.path.join(os.path.dirname(__file__), "jc2_banner_v2.png")

img = Image.new("RGB", (W, H), "#0d1117")
draw = ImageDraw.Draw(img)

# ── Background: clean dark with subtle left-to-right gradient ──────────────
for x in range(W):
    t = x / W
    r = int(13 + 8 * t)
    g = int(17 + 4 * t)
    b = int(23 + 6 * t)
    draw.line([(x, 0), (x, H)], fill=(r, g, b))

# Gold accent bars (top/bottom/left edge)
GOLD = "#C9A84C"
draw.rectangle([(0, 0), (W, 4)], fill=GOLD)
draw.rectangle([(0, H - 4), (W, H)], fill=GOLD)
draw.rectangle([(0, 0), (5, H)], fill=GOLD)

# ── Fonts ──────────────────────────────────────────────────────────────────
def font(paths, size):
    for p in paths:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            pass
    return ImageFont.load_default()

BOLD_PATHS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
]
REG_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
]

f_jc   = font(BOLD_PATHS, 148)
f_sq   = font(BOLD_PATHS, 72)
f_tc   = font(BOLD_PATHS, 44)
f_cards= font(BOLD_PATHS, 44)
f_tag  = font(REG_PATHS,  20)
f_cat  = font(BOLD_PATHS, 16)

# ── Left block: JC² Trading Cards ─────────────────────────────────────────
# "JC" in gold
draw.text((28, 28), "JC", font=f_jc, fill=GOLD)
jc_w = draw.textlength("JC", font=f_jc)

# "²" smaller, raised
draw.text((28 + jc_w + 2, 32), "2", font=f_sq, fill=GOLD)

# Vertical divider
div_x = 390
draw.rectangle([(div_x, 30), (div_x + 3, H - 30)], fill=GOLD)

# "TRADING CARDS" right of divider
draw.text((div_x + 22, 52), "TRADING", font=f_tc, fill="#FFFFFF")
draw.text((div_x + 22, 100), "CARDS", font=f_cards, fill=GOLD)

# Tagline
draw.text((div_x + 22, 158), "Jason & Jack Chletsos  ·  Wynnewood, PA", font=f_tag, fill="#8899aa")
draw.text((div_x + 22, 185), "Premium Sports & Pokémon Cards", font=f_tag, fill="#667788")

# ── Right block: Three sport panels ───────────────────────────────────────
PANEL_W = 162
PANEL_H = 208
PANEL_Y = 31
GAP     = 12
PANEL_START = 640

panels = [
    {
        "label": "FOOTBALL",
        "bg":    "#1a2d1a",
        "border":"#3a8a3a",
        "accent":"#5cb85c",
        "draw_icon": "football",
    },
    {
        "label": "BASEBALL",
        "bg":    "#2d1a1a",
        "border":"#cc3333",
        "accent":"#e05555",
        "draw_icon": "baseball",
    },
    {
        "label": "POKÉMON",
        "bg":    "#2a2200",
        "border":"#cc9900",
        "accent":"#ffcc00",
        "draw_icon": "pokeball",
    },
]

def draw_football(d, cx, cy, r=42):
    # Brown oval
    d.ellipse([cx - r, cy - int(r * 0.62), cx + r, cy + int(r * 0.62)], fill="#7B4A1E", outline="#5a3010", width=2)
    # White lace stripe
    lace_len = int(r * 0.65)
    d.line([(cx - lace_len, cy), (cx + lace_len, cy)], fill="white", width=3)
    for offset in [-14, 0, 14]:
        d.line([(cx + offset, cy - 10), (cx + offset, cy + 10)], fill="white", width=2)

def draw_baseball(d, cx, cy, r=40):
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#F8F8F0", outline="#ddddcc", width=2)
    # Red stitching curves
    for flip in [-1, 1]:
        pts = []
        for i in range(20):
            angle = math.radians(-60 + i * 6)
            rx = flip * (10 + 8 * math.sin(i * math.pi / 19))
            ry = (r - 10) * math.sin(angle)
            pts.append((cx + rx, cy + int(ry)))
        if len(pts) > 1:
            d.line(pts, fill="#CC0000", width=2)
    # Simple V-stitch marks
    for y_off in [-16, -8, 0, 8, 16]:
        for x_off in [flip * 10 for flip in [-1, 1]]:
            d.line([(cx + x_off - 3, cy + y_off - 4),
                    (cx + x_off,     cy + y_off),
                    (cx + x_off + 3, cy + y_off - 4)], fill="#CC0000", width=2)

def draw_pokeball(d, cx, cy, r=40):
    # Bottom half (white)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="white", outline="#222", width=2)
    # Top half (red)
    d.pieslice([cx - r, cy - r, cx + r, cy + r], start=180, end=360, fill="#CC0000", outline="#222", width=2)
    # Center band
    d.line([(cx - r, cy), (cx + r, cy)], fill="#222", width=4)
    # Center circle outer
    d.ellipse([cx - 12, cy - 12, cx + 12, cy + 12], fill="#222")
    # Center circle inner
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill="white")

f_icon_label = font(BOLD_PATHS, 14)

for i, panel in enumerate(panels):
    px = PANEL_START + i * (PANEL_W + GAP)
    py = PANEL_Y

    # Panel background + border
    draw.rectangle([(px, py), (px + PANEL_W, py + PANEL_H)],
                   fill=panel["bg"], outline=panel["border"], width=2)

    # Sport icon centered in top portion
    icon_cx = px + PANEL_W // 2
    icon_cy = py + 90

    if panel["draw_icon"] == "football":
        draw_football(draw, icon_cx, icon_cy)
    elif panel["draw_icon"] == "baseball":
        draw_baseball(draw, icon_cx, icon_cy)
    elif panel["draw_icon"] == "pokeball":
        draw_pokeball(draw, icon_cx, icon_cy)

    # Horizontal divider inside panel
    draw.line([(px + 16, py + 148), (px + PANEL_W - 16, py + 148)],
              fill=panel["border"], width=1)

    # Category label
    lw = draw.textlength(panel["label"], font=f_icon_label)
    draw.text((px + (PANEL_W - lw) // 2, py + 158), panel["label"],
              font=f_icon_label, fill=panel["accent"])

    # Sub-label
    sub = "RC · Base · Prizm"
    sw = draw.textlength(sub, font=f_tag)
    draw.text((px + (PANEL_W - sw) // 2, py + 178), sub,
              font=f_tag, fill="#667788")

img.save(OUT, "PNG", optimize=True)
print(f"Saved: {OUT}  ({W}x{H})")
