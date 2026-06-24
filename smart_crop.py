"""
smart_crop.py — content-aware 3x3 card splitter.

The naive even-thirds crop mis-centers cards (gray scanner gaps are uneven and
cards sit slightly off-grid). This finds each card's real edges by detecting
card pixels (bright white borders OR saturated color) vs. the gray scanner bed,
locating the 2 vertical + 2 horizontal gaps, then tightly trimming each cell.

    python3 smart_crop.py "/path/Scan 114.jpeg" --out "output/split_cards/Scan 114"
    python3 smart_crop.py "/path/Scan 114.jpeg" --test   # writes *_smart.jpg alongside for compare
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from PIL import Image


def card_mask(arr: np.ndarray) -> np.ndarray:
    r, g, b = arr[..., 0].astype(int), arr[..., 1].astype(int), arr[..., 2].astype(int)
    gray = (r + g + b) / 3
    sat = arr.max(2).astype(int) - arr.min(2).astype(int)
    # card = white border (bright) OR colorful OR dark border/nameplate (darker than
    # the mid-gray scanner bed). The scanner bed sits ~130-190, so <100 is card-black.
    return (gray > 205) | (sat > 38) | (gray < 100)


def _gaps(frac: np.ndarray, n: int = 3, lo: float = 0.18) -> list[tuple[int, int]]:
    """Return n (start,end) card spans along an axis given per-index card fraction."""
    is_card = frac >= lo
    spans, in_run, s = [], False, 0
    for i, v in enumerate(is_card):
        if v and not in_run:
            in_run, s = True, i
        elif not v and in_run:
            in_run = False
            spans.append((s, i))
    if in_run:
        spans.append((s, len(is_card)))
    # keep the n widest card spans, restore left->right order
    spans.sort(key=lambda x: x[1] - x[0], reverse=True)
    spans = sorted(spans[:n])
    return spans


def split(path: str, margin_frac: float = 0.015):
    im = Image.open(path).convert("RGB")
    arr = np.asarray(im)
    H, W = arr.shape[:2]
    m = card_mask(arr)
    col_frac = m.mean(0)
    row_frac = m.mean(1)
    col_spans = _gaps(col_frac)
    row_spans = _gaps(row_frac)
    mx, my = int(W * margin_frac), int(H * margin_frac)
    cells = []
    for (y0, y1) in row_spans:
        for (x0, x1) in col_spans:
            # tight-trim within the span using the local card mask
            sub = m[y0:y1, x0:x1]
            cols = np.where(sub.mean(0) >= 0.12)[0]
            rows = np.where(sub.mean(1) >= 0.12)[0]
            if len(cols) and len(rows):
                cx0, cx1 = x0 + cols[0], x0 + cols[-1] + 1
                cy0, cy1 = y0 + rows[0], y0 + rows[-1] + 1
            else:
                cx0, cx1, cy0, cy1 = x0, x1, y0, y1
            cx0, cy0 = max(0, cx0 - mx), max(0, cy0 - my)
            cx1, cy1 = min(W, cx1 + mx), min(H, cy1 + my)
            cells.append((cx0, cy0, cx1, cy1))
    return im, cells, (len(col_spans), len(row_spans))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--out", default="")
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--upscale", type=float, default=2.5)
    args = ap.parse_args()
    im, cells, (nc, nr) = split(args.path)
    print(f"{Path(args.path).name}: {nc} cols x {nr} rows = {len(cells)} cards")
    if args.out:
        Path(args.out).mkdir(parents=True, exist_ok=True)
    for i, (x0, y0, x1, y1) in enumerate(cells, 1):
        c = im.crop((x0, y0, x1, y1))
        if args.upscale != 1:
            c = c.resize((int(c.width * args.upscale), int(c.height * args.upscale)), Image.LANCZOS)
        if args.test:
            p = Path(args.path).with_name(f"card_{i:02d}_smart.jpg")
            c.save(p, quality=92)
        elif args.out:
            c.save(f"{args.out}/card_{i:02d}.jpg", quality=92)
    print("done")


if __name__ == "__main__":
    main()
