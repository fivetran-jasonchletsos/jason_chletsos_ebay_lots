"""Slice 3x3 binder-page scans into 9 individual card images.

Detects the white gutter lines between cards by scanning brightness
profiles, then crops each cell with a small inward pad so no gutter
or torn-edge artifact survives in the thumbnail.
"""
import sys
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

SCANS = {
    "scan1": "Scan 364.jpeg",
    "scan2": "Scan 361.jpeg",
    "scan3": "Scan 363.jpeg",
    "scan4": "Scan 360.jpeg",
    "scan5": "Scan 356.jpeg",
    "scan6": "Scan 357.jpeg",
    "scan7": "Scan 362.jpeg",
    "scan8": "Scan 358.jpeg",
    "scan9": "Scan 359.jpeg",
    "scan10": "Scan 365.jpeg",
    "scan11": "Scan 366.jpeg",
    "scan12": "Scan 367.jpeg",
    "scan13": "Scan 368.jpeg",
    "scan14": "Scan 369.jpeg",
    "scan15": "Scan 370.jpeg",
    "scan16": "Scan 371.jpeg",
    "scan17": "Scan 372.jpeg",
}

SRC_DIR = "/Users/jason.chletsos/Downloads"
OUT_DIR = "/Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots/docs/marvel_vault/images"
THUMB_W = 700


def find_gaps(profile, n_lines, min_gap_frac=0.06):
    """Find n_lines whitest local bands in profile, spread across the image."""
    length = len(profile)
    # coarse candidate positions near expected thirds boundaries
    expected = [length * i / 3 for i in (1, 2)]
    found = []
    window = int(length * 0.08)
    for center in expected:
        lo = max(0, int(center - window))
        hi = min(length, int(center + window))
        seg = profile[lo:hi]
        best_i = max(range(len(seg)), key=lambda i: seg[i])
        found.append(lo + best_i)
    return found


def col_row_bounds(im):
    gray = im.convert("L")
    w, h = gray.size
    # sample brightness along a band near the vertical/horizontal center
    px = gray.load()
    col_profile = []
    y0, y1 = int(h * 0.3), int(h * 0.7)
    for x in range(0, w, max(1, w // 2000)):
        s = 0
        cnt = 0
        for y in range(y0, y1, max(1, (y1 - y0) // 200)):
            s += px[x, y]
            cnt += 1
        col_profile.append((x, s / cnt))
    row_profile = []
    x0, x1 = int(w * 0.3), int(w * 0.7)
    for y in range(0, h, max(1, h // 2000)):
        s = 0
        cnt = 0
        for x in range(x0, x1, max(1, (x1 - x0) // 200)):
            s += px[x, y]
            cnt += 1
        row_profile.append((y, s / cnt))

    def gaps_from(profile, total):
        vals = [v for _, v in profile]
        xs = [x for x, _ in profile]
        expected = [total / 3, total * 2 / 3]
        window = total * 0.10
        out = []
        for center in expected:
            best_x, best_v = None, -1
            for x, v in zip(xs, vals):
                if abs(x - center) <= window and v > best_v:
                    best_v, best_x = v, x
            out.append(best_x if best_x is not None else int(center))
        return out

    col_gaps = gaps_from(col_profile, w)
    row_gaps = gaps_from(row_profile, h)
    return col_gaps, row_gaps, w, h


def crop_grid(path, out_prefix):
    im = Image.open(path)
    im = im.convert("RGB")
    col_gaps, row_gaps, w, h = col_row_bounds(im)
    xb = [0] + col_gaps + [w]
    yb = [0] + row_gaps + [h]
    pad_x = w * 0.006
    pad_y = h * 0.006
    idx = 0
    for r in range(3):
        for c in range(3):
            left = xb[c] + pad_x
            right = xb[c + 1] - pad_x
            top = yb[r] + pad_y
            bottom = yb[r + 1] - pad_y
            cell = im.crop((int(left), int(top), int(right), int(bottom)))
            ratio = THUMB_W / cell.width
            cell = cell.resize((THUMB_W, int(cell.height * ratio)), Image.LANCZOS)
            out_path = f"{OUT_DIR}/{out_prefix}_{r}_{c}.jpg"
            cell.save(out_path, quality=88)
            idx += 1
    print(f"{out_prefix}: wrote {idx} tiles from {path}")


if __name__ == "__main__":
    for prefix, fname in SCANS.items():
        crop_grid(f"{SRC_DIR}/{fname}", prefix)
