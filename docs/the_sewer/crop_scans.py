"""Slice Amanda's 3x3 tabletop card-photo pages into individual card images.

Same gap-detection approach as marvel_vault/crop_scans.py, tuned for phone
photos rather than flatbed scans (lower res, less uniform lighting).
"""
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

SCANS = {
    "scan1": "17.png",
    "scan2": "18.png",
    "scan3": "19.png",
    "scan4": "20.png",
    "scan5": "21.png",
    "scan6": "22.png",
    "scan7": "23.png",
    "scan8": "24.png",
}

SRC_DIR = "/Users/jason.chletsos/.claude/image-cache/9c0a0fea-1777-461e-9c7d-f96680f0b40c"
OUT_DIR = "/Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots/docs/the_sewer/images"
THUMB_W = 500


def col_row_bounds(im):
    gray = im.convert("L")
    w, h = gray.size
    px = gray.load()
    col_profile = []
    y0, y1 = int(h * 0.3), int(h * 0.7)
    for x in range(0, w, max(1, w // 1000)):
        s = 0
        cnt = 0
        for y in range(y0, y1, max(1, (y1 - y0) // 150)):
            s += px[x, y]
            cnt += 1
        col_profile.append((x, s / cnt))
    row_profile = []
    x0, x1 = int(w * 0.3), int(w * 0.7)
    for y in range(0, h, max(1, h // 1000)):
        s = 0
        cnt = 0
        for x in range(x0, x1, max(1, (x1 - x0) // 150)):
            s += px[x, y]
            cnt += 1
        row_profile.append((y, s / cnt))

    def gaps_from(profile, total):
        xs = [x for x, _ in profile]
        vals = [v for _, v in profile]
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

    return gaps_from(col_profile, w), gaps_from(row_profile, h), w, h


def crop_grid(path, out_prefix):
    im = Image.open(path).convert("RGB")
    col_gaps, row_gaps, w, h = col_row_bounds(im)
    xb = [0] + col_gaps + [w]
    yb = [0] + row_gaps + [h]
    pad_x = w * 0.008
    pad_y = h * 0.008
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
            cell.save(f"{OUT_DIR}/{out_prefix}_{r}_{c}.jpg", quality=88)
            idx += 1
    print(f"{out_prefix}: wrote {idx} tiles from {path}")


if __name__ == "__main__":
    for prefix, fname in SCANS.items():
        crop_grid(f"{SRC_DIR}/{fname}", prefix)
