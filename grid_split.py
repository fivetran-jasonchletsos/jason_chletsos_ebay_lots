"""
grid_split.py — split a clean NxM scanner sheet into individual cards by forcing
a grid and snapping each interior gridline to the whitest band near it. Robust for
full-bleed / die-cut cards where gap-threshold detection fails.

Usage:
    python3 grid_split.py "/path/Scan 16.jpeg" --rows 3 --cols 3 --prefix "Scan 190" --out "output/split_cards/Scan 16"
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from PIL import Image, ImageOps

BG = 210          # brightness >= BG counts as background/white
MARGIN = 10       # px kept around each card
SEARCH = 0.18     # +/- fraction of cell size to search for the whitest band


def content_bbox(bgmask):
    rows = np.where(bgmask.mean(axis=1) < 0.98)[0]
    cols = np.where(bgmask.mean(axis=0) < 0.98)[0]
    if len(rows) == 0 or len(cols) == 0:
        return 0, 0, bgmask.shape[0], bgmask.shape[1]
    return rows[0], cols[0], rows[-1] + 1, cols[-1] + 1


def snap_cuts(bgfrac, start, end, n):
    """Return n+1 cut positions between start..end; interior cuts snapped to the
    whitest (max bg-fraction) band near each evenly-spaced gridline."""
    span = end - start
    cell = span / n
    cuts = [start]
    for k in range(1, n):
        guess = int(start + k * cell)
        w = int(cell * SEARCH)
        lo, hi = max(start, guess - w), min(end, guess + w)
        band = bgfrac[lo:hi]
        cut = lo + int(np.argmax(band)) if len(band) else guess
        cuts.append(cut)
    cuts.append(end)
    return cuts


def split(path, rows, cols, out_dir, prefix):
    img = Image.open(path).convert("RGB")
    gray = np.array(ImageOps.grayscale(img), dtype=np.float32)
    H, W = gray.shape
    bgmask = (gray >= BG).astype(np.float32)
    y0, x0, y1, x1 = content_bbox(bgmask)

    row_bg = bgmask.mean(axis=1)   # bg fraction per row
    col_bg = bgmask.mean(axis=0)   # bg fraction per col
    rcuts = snap_cuts(row_bg, y0, y1, rows)
    ccuts = snap_cuts(col_bg, x0, x1, cols)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    i = 1
    for r in range(rows):
        for c in range(cols):
            ya, yb = rcuts[r], rcuts[r + 1]
            xa, xb = ccuts[c], ccuts[c + 1]
            crop = img.crop((max(0, xa - MARGIN), max(0, ya - MARGIN),
                             min(W, xb + MARGIN), min(H, yb + MARGIN)))
            fn = out_dir / f"{prefix}_{i:02d}.jpg"
            crop.save(fn, "JPEG", quality=92)
            saved.append(fn)
            print(f"  [{i:02d}] {fn.name}  ({crop.width}x{crop.height})")
            i += 1
    print(f"Done — {len(saved)} cards.")
    return saved


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("scan")
    ap.add_argument("--rows", type=int, default=3)
    ap.add_argument("--cols", type=int, default=3)
    ap.add_argument("--prefix", default="card")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    split(a.scan, a.rows, a.cols, a.out, a.prefix)
