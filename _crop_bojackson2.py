"""Crop batch-2 Bo Jackson Battle Arena pages: four 3x3 binder pages (one
skipped as an exact re-scan duplicate) plus three 2x3 toploader/foil-parallel
sleeve pages (different aspect ratio, different physical cards).
"""
from pathlib import Path
from PIL import Image
Image.MAX_IMAGE_PIXELS = None

SRC_DIR = "/Users/jason.chletsos/Downloads"
OUT_DIR = "/Users/jason.chletsos/Documents/GitHub/jason_chletsos_ebay_lots/output/bojackson_images"
Path(OUT_DIR).mkdir(parents=True, exist_ok=True)
THUMB_W = 600

GRID_3X3 = {
    "Scan 377.jpeg": [
        ["Reindeer Hunter", "Swervin'", "Jeanetic"],
        ["Merlomes", "Devaulta (2)", "Moose"],
        ["Flippa", "Mod", "McVillain"],
    ],
    # Scan 378.jpeg is an exact re-scan duplicate of Scan 377 -- skipped.
    "Scan 379.jpeg": [
        ["Friday (2)", "Eagle-Eye", "Eagle-Eye (2)"],
        ["First Leap (2)", "Ryptillian", "Golden Bullet (2)"],
        ["Warp", "Brockness", "Golden Bullet (3)"],
    ],
    "Scan 380.jpeg": [
        ["Quarter Staff", "Brawn", "Hillicopter"],
        ["Cannon (2)", "Mod (2)", "Bison (2)"],
        ["Reindeer Hunter (2)", "Skatter (2)", "Coinslot"],
    ],
    "Scan 381.jpeg": [
        ["Friday (3)", "Quarter Staff (2)", "Bayou (2)"],
        ["Coinslot (2)", "Lawman", "Mcarmyknife (2)"],
        ["Warp (2)", "Swervin' (2)", "Hot Rod"],
    ],
}

GRID_2X3_TOPLOADER = {
    "Scan 382.jpeg": [
        ["Warden (2, foil)", "Majik Man (2, foil)"],
        ["Slaughterhouse (2, foil)", "Rockhead (foil)"],
        ["First Leap (3, foil)", "Darn Old (2, foil)"],
    ],
    "Scan 383.jpeg": [
        ["Mod (3, foil)", "Shrouded (2, foil)"],
        ["Swervin' (3, foil)", "Yeti (foil)"],
        ["Shepherd (foil)", "First Leap (4, foil)"],
    ],
    "Scan 384.jpeg": [
        ["Buttman (foil)", "Cannon (2, foil)"],
        ["Hot Rod (2, foil)", "Furnest (foil)"],
        ["Billiard (2, foil)", "Dart-Board (2, foil)"],
    ],
}


def col_row_bounds(im, ncols, nrows):
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

    def gaps_from(profile, total, n):
        expected = [total * i / n for i in range(1, n)]
        window = total * 0.10
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

    return gaps_from(col_profile, w, ncols), gaps_from(row_profile, h, nrows), w, h


def slug(name):
    return (name.lower().replace(" ", "_").replace("(", "").replace(")", "")
            .replace(",", "").replace("-", "_").replace(".", "").replace("'", ""))


def crop_page(fname, names):
    nrows, ncols = len(names), len(names[0])
    im = Image.open(f"{SRC_DIR}/{fname}").convert("RGB")
    col_gaps, row_gaps, w, h = col_row_bounds(im, ncols, nrows)
    xb = [0] + col_gaps + [w]
    yb = [0] + row_gaps + [h]
    pad_x = w * 0.008
    pad_y = h * 0.008
    for r in range(nrows):
        for c in range(ncols):
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
    for fname, names in GRID_3X3.items():
        print(fname)
        crop_page(fname, names)
    for fname, names in GRID_2X3_TOPLOADER.items():
        print(fname)
        crop_page(fname, names)
