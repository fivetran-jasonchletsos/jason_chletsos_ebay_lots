"""
scan_splitter.py — splits a flatbed scan of multiple cards into individual card images.

Usage:
    python3 scan_splitter.py /path/to/scan.jpg
    python3 scan_splitter.py /path/to/scan.jpg --out ~/Desktop/cards
    python3 scan_splitter.py /path/to/scan.jpg --prefix "2025 Topps Signature"

Output: one JPEG per detected card, saved to ./output/split_cards/ by default.
Cards are named card_01.jpg, card_02.jpg ... left-to-right, top-to-bottom.
"""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps


# ── tunables ─────────────────────────────────────────────────────────────────
MIN_CARD_PX   = 300     # ignore detected regions smaller than this (noise)
MARGIN        = 12      # pixels of white border to keep around each card
BG_THRESHOLD  = 220     # pixel brightness ≥ this is considered background
GAP_THRESHOLD = 0.80    # fraction of a row/column that must be BG to count as a gap
MIN_GAP_PX    = 8       # gaps narrower than this are ignored
# ─────────────────────────────────────────────────────────────────────────────


def _find_gaps(projection: np.ndarray) -> list[tuple[int, int]]:
    """Return (start, end) index pairs for contiguous gap runs."""
    is_gap = projection >= GAP_THRESHOLD
    gaps: list[tuple[int, int]] = []
    in_gap = False
    g_start = 0
    for i, v in enumerate(is_gap):
        if v and not in_gap:
            in_gap = True
            g_start = i
        elif not v and in_gap:
            in_gap = False
            if i - g_start >= MIN_GAP_PX:
                gaps.append((g_start, i))
    if in_gap and len(is_gap) - g_start >= MIN_GAP_PX:
        gaps.append((g_start, len(is_gap)))
    return gaps


def _gap_to_cuts(gaps: list[tuple[int, int]], size: int) -> list[int]:
    """Convert gap ranges to cut points (midpoints of each gap), plus 0 and size."""
    cuts = [0]
    for s, e in gaps:
        cuts.append((s + e) // 2)
    cuts.append(size)
    return sorted(set(cuts))


def split_scan(img_path: Path, out_dir: Path, prefix: str = "card") -> list[Path]:
    img = Image.open(img_path).convert("RGB")

    # Slight blur to reduce scanner noise, then convert to grayscale for analysis
    blurred = img.filter(ImageFilter.GaussianBlur(radius=2))
    gray    = np.array(ImageOps.grayscale(blurred), dtype=np.float32)

    H, W = gray.shape

    # Horizontal projection: fraction of BG pixels per row
    h_proj = (gray >= BG_THRESHOLD).mean(axis=1)   # shape (H,)
    # Vertical projection: fraction of BG pixels per column
    v_proj = (gray >= BG_THRESHOLD).mean(axis=0)   # shape (W,)

    h_gaps = _find_gaps(h_proj)
    v_gaps = _find_gaps(v_proj)

    row_cuts = _gap_to_cuts(h_gaps, H)
    col_cuts = _gap_to_cuts(v_gaps, W)

    # Build bounding boxes from the cut grid
    boxes: list[tuple[int,int,int,int]] = []
    for r in range(len(row_cuts) - 1):
        for c in range(len(col_cuts) - 1):
            y0 = row_cuts[r]
            y1 = row_cuts[r + 1]
            x0 = col_cuts[c]
            x1 = col_cuts[c + 1]
            h  = y1 - y0
            w  = x1 - x0
            if h >= MIN_CARD_PX and w >= MIN_CARD_PX:
                boxes.append((x0, y0, x1, y1))

    if not boxes:
        print("No cards detected — try adjusting BG_THRESHOLD or scanning with more white border.")
        return []

    # Sort left-to-right, top-to-bottom
    boxes.sort(key=lambda b: (b[1] // (MIN_CARD_PX // 2), b[0]))

    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []

    for i, (x0, y0, x1, y1) in enumerate(boxes, 1):
        # Add margin, clamp to image bounds
        x0c = max(0, x0 - MARGIN)
        y0c = max(0, y0 - MARGIN)
        x1c = min(W, x1 + MARGIN)
        y1c = min(H, y1 + MARGIN)

        card = img.crop((x0c, y0c, x1c, y1c))
        fname = out_dir / f"{prefix}_{i:02d}.jpg"
        card.save(fname, "JPEG", quality=92)
        saved.append(fname)
        print(f"  [{i:02d}] {fname.name}  ({x1c-x0c}×{y1c-y0c}px)")

    return saved


def main():
    ap = argparse.ArgumentParser(description="Split a multi-card scan into individual card images.")
    ap.add_argument("scan", help="Path to the scan image (JPG, PNG, TIFF)")
    ap.add_argument("--out", default=None, help="Output directory (default: output/split_cards/)")
    ap.add_argument("--prefix", default="card", help="Filename prefix for output cards")
    args = ap.parse_args()

    scan_path = Path(args.scan).expanduser().resolve()
    if not scan_path.exists():
        sys.exit(f"File not found: {scan_path}")

    out_dir = Path(args.out).expanduser().resolve() if args.out else \
              Path(__file__).parent / "output" / "split_cards" / scan_path.stem

    print(f"Splitting: {scan_path.name}")
    print(f"Output to: {out_dir}")

    saved = split_scan(scan_path, out_dir, prefix=args.prefix)

    print(f"\nDone — {len(saved)} card(s) extracted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
