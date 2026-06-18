from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math, os

W, H = 1200, 270
OUTPUT = os.path.join(os.path.dirname(__file__), "jc2_banner.png")

img = Image.new("RGB", (W, H), "#0a0a12")
draw = ImageDraw.Draw(img)

# Background gradient — deep navy to black
for y in range(H):
    t = y / H
    r = int(10 + 8 * (1 - t))
    g = int(10 + 12 * (1 - t))
    b = int(18 + 28 * (1 - t))
    draw.line([(0, y), (W, y)], fill=(r, g, b))

# Subtle card-pattern overlay — faint diagonal lines
for x in range(-H, W, 40):
    draw.line([(x, 0), (x + H, H)], fill=(255, 255, 255, 8), width=1)

# Left gold accent bar
draw.rectangle([(0, 0), (6, H)], fill="#C9A84C")

# Right gold accent bar
draw.rectangle([(W - 6, 0), (W, H)], fill="#C9A84C")

# Top and bottom gold lines
draw.rectangle([(0, 0), (W, 3)], fill="#C9A84C")
draw.rectangle([(0, H - 3), (W, H)], fill="#C9A84C")

# Try system fonts — fall back gracefully
def try_font(names, size):
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()

bold_font  = try_font([
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
], 120)

name_font  = try_font([
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
], 38)

tag_font   = try_font([
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
], 20)

# "JC²" — draw gold shadow then white
jc_text = "JC²"  # JC with superscript 2
x_jc = 60

# Shadow
draw.text((x_jc + 3, 53), jc_text, font=bold_font, fill="#7a5c1a")
# Main gold
draw.text((x_jc, 50), jc_text, font=bold_font, fill="#C9A84C")

# Vertical divider
draw.rectangle([(340, 55), (343, 215)], fill="#C9A84C")

# "TRADING CARDS" stacked right of divider
x_right = 370
draw.text((x_right, 72), "TRADING", font=name_font, fill="#FFFFFF")
draw.text((x_right, 118), "CARDS", font=name_font, fill="#C9A84C")

# Tagline
draw.text((x_right, 172), "Jason & Jack Chletsos  ·  Wynnewood, PA", font=tag_font, fill="#8899aa")

# Right side — decorative card stack suggestion (simple rectangles)
card_x = 900
for i, (angle_offset, alpha) in enumerate([(20, 60), (10, 120), (0, 220)]):
    cx = card_x + i * 8
    cy = 45 + i * 6
    cw, ch = 160, 220
    col = (30 + i * 15, 30 + i * 15, 50 + i * 20)
    border = (150, 130, 60) if i == 2 else (60, 65, 90)
    draw.rectangle([(cx, cy), (cx + cw, cy + ch)], fill=col, outline=border, width=2)

# RC badge on top card
rc_x, rc_y = card_x + 16 + 8, 45 + 12
draw.rectangle([(rc_x, rc_y), (rc_x + 40, rc_y + 22)], fill="#C9A84C")
draw.text((rc_x + 4, rc_y + 2), "RC", font=tag_font, fill="#000000")

# Harpua2001 callout — small, bottom right
draw.text((W - 180, H - 28), "Harpua2001 on eBay", font=tag_font, fill="#445566")

img.save(OUTPUT, "PNG", optimize=True)
print(f"Banner saved: {OUTPUT}  ({W}x{H}px)")
