"""
build_og_card.py — Generate docs/og-card.jpg programmatically.

The 1200x630 Open Graph / Twitter Card image referenced by promote.py's
html_shell() helper. Re-run this any time the seller rating changes so
LinkedIn / Twitter / Facebook / Slack scrapers don't 404.

Usage:
    python3 build_og_card.py

Pulls the seller name + rating dynamically from docs/_seller.json (the
canonical source). Visual style matches the site's Dark Luxe palette
(black bg, gold #c9a542 accents, cream text).
"""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- Palette (mirrors _BASE_CSS in promote.py — Dark Luxe theme) -----------
BG          = (10, 10, 10)         # #0a0a0a
SURFACE     = (20, 20, 20)         # #141414
GOLD        = (201, 165, 66)       # #c9a542
GOLD_BRIGHT = (230, 198, 106)      # #e6c66a
GOLD_DIM    = (138, 117, 33)       # #8a7521
TEXT        = (241, 239, 233)      # #f1efe9
TEXT_MUTED  = (154, 147, 136)      # #9a9388
BORDER      = (60, 50, 22)         # subtle gold @ ~10% on black

W, H = 1200, 630

# Mac system fonts — fall back gracefully if anything is missing.
FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/Library/Fonts/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]
FONT_CANDIDATES_REG = [
    "/System/Library/Fonts/HelveticaNeue.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
]


def _load_font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont:
    for p in candidates:
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size=size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_seller() -> dict:
    """Read docs/_seller.json. Returns sensible defaults if missing."""
    defaults = {
        "user_id": "harpua2001",
        "feedback_score": "170",
        "positive_pct": "100.0",
        "member_since": "Dec 1998",
        "member_years": 27,
    }
    p = Path(__file__).parent / "docs" / "_seller.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        merged = dict(defaults)
        merged.update({k: v for k, v in data.items() if v not in (None, "")})
        return merged
    except (OSError, ValueError, json.JSONDecodeError):
        return defaults


def build(out_path: Path | None = None) -> Path:
    seller = _load_seller()
    user_id = (seller.get("user_id") or "Harpua2001").strip()
    # Title-case the user_id (matches SELLER_NAME in promote.py)
    display = user_id[0].upper() + user_id[1:] if user_id else "Harpua2001"

    try:
        reviews = int(float(seller.get("feedback_score", 170)))
    except (TypeError, ValueError):
        reviews = 170
    try:
        pct = float(seller.get("positive_pct", 100.0))
    except (TypeError, ValueError):
        pct = 100.0
    pct_str = f"{pct:.0f}%" if pct == int(pct) else f"{pct:.1f}%"
    member_since = seller.get("member_since", "Dec 1998")

    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img, "RGBA")

    # Soft radial-ish glow in the top-left (cheap fake — concentric circles)
    cx, cy = 220, 180
    for r, a in [(420, 14), (320, 22), (220, 30), (140, 40)]:
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(GOLD[0], GOLD[1], GOLD[2], a))

    # Thin gold accent bar across the top
    d.rectangle([0, 0, W, 6], fill=GOLD)

    # Brand mark — gold square with "H"
    mark_size = 96
    mark_x, mark_y = 72, 96
    d.rounded_rectangle(
        [mark_x, mark_y, mark_x + mark_size, mark_y + mark_size],
        radius=18, fill=GOLD,
    )
    font_mark = _load_font(FONT_CANDIDATES_BOLD, 72)
    bbox = d.textbbox((0, 0), "H", font=font_mark)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(
        (mark_x + (mark_size - tw) / 2 - bbox[0],
         mark_y + (mark_size - th) / 2 - bbox[1] - 4),
        "H", font=font_mark, fill=BG,
    )

    # Eyebrow — small uppercase tag
    font_eyebrow = _load_font(FONT_CANDIDATES_REG, 22)
    d.text((192, 108), "EBAY STOREFRONT", font=font_eyebrow,
           fill=GOLD_BRIGHT, spacing=4)

    # Storefront subhead
    font_sub_top = _load_font(FONT_CANDIDATES_REG, 26)
    d.text((192, 144), "Sports & Pokemon Cards", font=font_sub_top,
           fill=TEXT_MUTED)

    # Big display title — seller name
    font_title = _load_font(FONT_CANDIDATES_BOLD, 148)
    d.text((68, 240), display, font=font_title, fill=TEXT)

    # Gold underline under the title
    title_bbox = d.textbbox((68, 240), display, font=font_title)
    underline_y = title_bbox[3] + 18
    d.rectangle([72, underline_y, 72 + 220, underline_y + 6], fill=GOLD)

    # Stats row — three stat blocks
    stats_y = 472
    stats = [
        (f"{reviews:,}", "REVIEWS"),
        (pct_str,        "POSITIVE"),
        (member_since,   "SELLING SINCE"),
    ]
    font_stat_num = _load_font(FONT_CANDIDATES_BOLD, 52)
    font_stat_lbl = _load_font(FONT_CANDIDATES_REG, 18)

    x = 72
    for i, (num, lbl) in enumerate(stats):
        d.text((x, stats_y), num, font=font_stat_num, fill=GOLD)
        nb = d.textbbox((x, stats_y), num, font=font_stat_num)
        d.text((x, nb[3] + 8), lbl, font=font_stat_lbl, fill=TEXT_MUTED)
        x = nb[2] + 56
        if i < len(stats) - 1:
            # vertical divider
            d.rectangle([x - 28, stats_y + 8, x - 26, stats_y + 62],
                        fill=BORDER)

    # Bottom-right URL hint
    font_url = _load_font(FONT_CANDIDATES_REG, 20)
    url = "ebay.com/str/harpua2001"
    ub = d.textbbox((0, 0), url, font=font_url)
    d.text((W - (ub[2] - ub[0]) - 72, H - 56), url,
           font=font_url, fill=TEXT_MUTED)

    # Thin gold bar at bottom (mirrors top)
    d.rectangle([0, H - 6, W, H], fill=GOLD_DIM)

    out = out_path or (Path(__file__).parent / "docs" / "og-card.jpg")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "JPEG", quality=88, optimize=True, progressive=True)
    return out


if __name__ == "__main__":
    p = build()
    sz = p.stat().st_size
    print(f"  wrote {p} ({sz / 1024:.1f} KB, 1200x630)")
