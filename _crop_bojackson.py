"""Slice Amanda's Bo Jackson Battle Arena binder-page photos (batches 1 and 2)
into individual named card images, for eBay listing use and the lots PDF.

Same gap-detection crop approach used elsewhere in this repo.
"""
from pathlib import Path
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

SRC_DIR = "/Users/jason.chletsos/Downloads"
OUT_DIR = "/Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots/output/bojackson_images"
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
THUMB_W = 600

# (source file, row, col) -> card name. One entry per physical card.
PAGES = {
    "Scan 373.jpeg": [
        ["Billiard", "Myracle", "Chanesaw"],
        ["Criscross", "Slaughterhouse", "Hot Sauce"],
        ["Dart-Board", "Muffin Man", "Bayou"],
    ],
    "Scan 374.jpeg": [
        ["Majik Man", "Shrouded", "Phoenix"],
        ["Golden Bullet", "Shrouded (2)", "Devaulta"],
        ["Judkernaught", "Warden", "Furnest"],
    ],
    "Scan 375.jpeg": [
        ["J-Jetts", "Mcarmyknife", "Youngblood"],
        ["Bison", "Shepherd", "Youngblood (2)"],
        ["Mr. Irrelevant", "Darn Old", "Switchblade"],
    ],
    "Scan 376.jpeg": [
        ["Jax-in-the-Box", "Muffin Man (2)", "Joe Cool"],
        ["Myracle (2)", "First Leap", "Skatter"],
        ["Hammer", "Scary", "Friday"],
    ],
}


def col_row_bounds(im):
    gray = im.convert("L")
    w, h = gray.size
    px = gray.load()
    col_profile = []
    y0, y1 = int(h * 0.3), int(h * 0.7)
    for x in range(0, w, max(1, w // 1000)):
        s = 0; cnt = 0
        for y in range(y0, y1, max(1, (y1 - y0) // 150)):
            s += px[x, y]; cnt += 1
        col_profile.append((x, s / cnt))
    row_profile = []
    x0, x1 = int(w * 0.3), int(w * 0.7)
    for y in range(0, h, max(1, h // 1000)):
        s = 0; cnt = 0
        for x in range(x0, x1, max(1, (x1 - x0) // 150)):
            s += px[x, y]; cnt += 1
        row_profile.append((y, s / cnt))

    def gaps_from(profile, total):
        expected = [total / 3, total * 2 / 3]; window = total * 0.10
        out = []
        for center in expected:
            best_x, best_v = None, -1
            for x, v in profile:
                if abs(x - center) <= window and v > best_v:
                    best_v, best_x = v, x
            out.append(best_x if best_x is not None else int(center))
        # Guard against a degenerate detection (e.g. a bright artifact sitting
        # near a boundary window) producing non-increasing gap positions --
        # crop_page() would otherwise pass a zero/negative-width box to
        # im.crop()/resize() and raise ValueError or ZeroDivisionError.
        for i in range(1, len(out)):
            if out[i] <= out[i - 1]:
                out[i] = max(int(expected[i]), out[i - 1] + 1)
        return out

    return gaps_from(col_profile, w), gaps_from(row_profile, h), w, h


def slug(name):
    return name.lower().replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").replace(".", "").replace("'", "")


def crop_page(fname, names):
    im = Image.open(f"{SRC_DIR}/{fname}").convert("RGB")
    col_gaps, row_gaps, w, h = col_row_bounds(im)
    xb = [0] + col_gaps + [w]
    yb = [0] + row_gaps + [h]
    pad_x = w * 0.008
    pad_y = h * 0.008
    for r in range(3):
        for c in range(3):
            name = names[r][c]
            left = xb[c] + pad_x; right = xb[c + 1] - pad_x
            top = yb[r] + pad_y; bottom = yb[r + 1] - pad_y
            cell = im.crop((int(left), int(top), int(right), int(bottom)))
            ratio = THUMB_W / cell.width
            cell = cell.resize((THUMB_W, int(cell.height * ratio)), Image.LANCZOS)
            out_path = f"{OUT_DIR}/{slug(name)}.jpg"
            cell.save(out_path, quality=90)
            print(f"  {name} -> {out_path}")


if __name__ == "__main__":
    for fname, names in PAGES.items():
        print(fname)
        crop_page(fname, names)
