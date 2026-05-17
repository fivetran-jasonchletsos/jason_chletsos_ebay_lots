#!/usr/bin/env python3
"""Generate square logo variants from the Harpua2001 storefront banner.

The source banner is a 3:1 horizontal image (2000x667) with the title block
"Harpua2001 STOREFRONT" centered. A naive square crop loses most content, so
we take the center 667x667 square (which preserves the central title) and
downscale it with Lanczos filtering for each target size.

Outputs (saved to ./docs/):
  - store_logo_310.jpg   310x310 JPEG  (eBay store logo spec)
  - store_logo_1200.jpg  1200x1200 JPEG (high-res social profile pic)
  - store_logo_512.png   512x512 PNG  (favicon / modern app icon, with alpha)
  - store_icon.svg       Vector "H2K" gold-on-black fallback brand mark
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image

REPO_ROOT = Path(__file__).resolve().parent
DOCS = REPO_ROOT / "docs"

# Preferred input: the originally-specified cache path. Fall back to the
# repo's own docs/banner.png (which is the same 2000x667 asset) if the
# cache file is no longer present on disk.
PRIMARY_INPUT = Path(
    "/Users/jason.chletsos/.claude/image-cache/"
    "9c3f5fe5-8f0d-4811-94f8-5a184bf0f21b/7.png"
)
FALLBACK_INPUT = DOCS / "banner.png"

# Brand colors (matched against the existing banner palette).
GOLD = "#d4a73a"
BLACK = "#0a0a0a"


def resolve_input() -> Path:
    if PRIMARY_INPUT.is_file():
        return PRIMARY_INPUT
    if FALLBACK_INPUT.is_file():
        return FALLBACK_INPUT
    raise FileNotFoundError(
        f"Neither {PRIMARY_INPUT} nor {FALLBACK_INPUT} exists"
    )


def center_square_crop(img: Image.Image) -> Image.Image:
    """Crop the centered square of the image (uses the shorter side)."""
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return img.crop((left, top, left + side, top + side))


def save_jpeg(img: Image.Image, path: Path, size: int) -> None:
    out = img.resize((size, size), Image.LANCZOS)
    if out.mode != "RGB":
        # JPEG has no alpha; composite onto black background to match brand.
        bg = Image.new("RGB", out.size, BLACK)
        if out.mode in ("RGBA", "LA"):
            bg.paste(out, mask=out.split()[-1])
        else:
            bg.paste(out)
        out = bg
    out.save(path, format="JPEG", quality=90, optimize=True, progressive=True)


def save_png(img: Image.Image, path: Path, size: int) -> None:
    out = img.resize((size, size), Image.LANCZOS)
    if out.mode != "RGBA":
        out = out.convert("RGBA")
    out.save(path, format="PNG", optimize=True)


SVG_TEMPLATE = """<?xml version=\"1.0\" encoding=\"UTF-8\"?>
<svg xmlns=\"http://www.w3.org/2000/svg\" viewBox=\"0 0 512 512\"
     width=\"512\" height=\"512\" role=\"img\"
     aria-label=\"Harpua2001 storefront mark\">
  <defs>
    <linearGradient id=\"gold\" x1=\"0\" y1=\"0\" x2=\"0\" y2=\"1\">
      <stop offset=\"0\" stop-color=\"#f1c75b\"/>
      <stop offset=\"1\" stop-color=\"#b8862a\"/>
    </linearGradient>
  </defs>
  <rect width=\"512\" height=\"512\" rx=\"72\" fill=\"{black}\"/>
  <rect x=\"24\" y=\"24\" width=\"464\" height=\"464\" rx=\"56\"
        fill=\"none\" stroke=\"url(#gold)\" stroke-width=\"6\"/>
  <text x=\"256\" y=\"312\" text-anchor=\"middle\"
        font-family=\"Georgia, 'Times New Roman', serif\"
        font-weight=\"700\" font-size=\"220\" fill=\"url(#gold)\"
        letter-spacing=\"-6\">H2K</text>
  <text x=\"256\" y=\"400\" text-anchor=\"middle\"
        font-family=\"Helvetica, Arial, sans-serif\"
        font-weight=\"600\" font-size=\"42\" fill=\"{gold}\"
        letter-spacing=\"8\">HARPUA2001</text>
</svg>
"""


def write_svg(path: Path) -> None:
    path.write_text(SVG_TEMPLATE.format(black=BLACK, gold=GOLD), encoding="utf-8")


def kb(path: Path) -> str:
    return f"{path.stat().st_size / 1024:.1f} KB"


def main() -> int:
    DOCS.mkdir(parents=True, exist_ok=True)
    src_path = resolve_input()
    print(f"[logo] input: {src_path}")
    with Image.open(src_path) as src:
        src.load()
        print(f"[logo] source size: {src.size} mode={src.mode}")
        square = center_square_crop(src)
        print(f"[logo] center square: {square.size}")

        targets = [
            ("store_logo_310.jpg", 310, save_jpeg),
            ("store_logo_1200.jpg", 1200, save_jpeg),
            ("store_logo_512.png", 512, save_png),
        ]
        for name, size, fn in targets:
            out_path = DOCS / name
            fn(square, out_path, size)
            print(f"[logo] wrote {out_path}  ({size}x{size}, {kb(out_path)})")

    svg_path = DOCS / "store_icon.svg"
    write_svg(svg_path)
    print(f"[logo] wrote {svg_path}  (vector, {kb(svg_path)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
