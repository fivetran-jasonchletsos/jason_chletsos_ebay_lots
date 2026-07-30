"""Crop and batch the 2024-25 Select basketball posting cards (scans 627-639).

Source of truth: output/bball_select.json (built by _bball_select_build.py).
Selection: typ >= $2, minus JC's keeps (LeBron x3, Towns, Brunson — ruled
2026-07-29), minus 76ers (son's box). One listing per UNIQUE title — duplicate
physical copies (Lillard x3, Clingan x3, ...) are written to
/tmp/bball_copies_on_deck.json to relist after the first copy sells.

Post with:
  python3 post_from_scan.py --batch /tmp/bball_select_batch.json --sport Basketball --apply
"""
import json
import math
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
CROP_DIR = Path("/tmp/bball_select_crops")

# 2026-07-29 second ruling: sell LeBrons + Knicks too; ONLY 76ers held.
KEEP = set()

data = json.load(open("output/bball_select.json"))
cards = [c for c in data["cards"]
         if c["typ"] >= 2 and c["player"] not in KEEP
         and "76" not in c["team"] and "phil" not in c["team"].lower()]

TEAM_SHORT = {
    "Oklahoma City Thunder": "Thunder", "Golden State Warriors": "Warriors",
    "San Antonio Spurs": "Spurs", "Los Angeles Lakers": "Lakers",
    "Denver Nuggets": "Nuggets", "Boston Celtics": "Celtics",
    "Memphis Grizzlies": "Grizzlies", "Phoenix Suns": "Suns",
    "Brooklyn Nets": "Nets", "New Orleans Pelicans": "Pelicans",
    "Los Angeles Clippers": "Clippers", "Charlotte Hornets": "Hornets",
    "Detroit Pistons": "Pistons", "Toronto Raptors": "Raptors",
    "Cleveland Cavaliers": "Cavaliers", "Milwaukee Bucks": "Bucks",
    "Houston Rockets": "Rockets", "Miami Heat": "Heat",
    "Atlanta Hawks": "Hawks", "Chicago Bulls": "Bulls",
    "Minnesota Timberwolves": "Timberwolves", "Utah Jazz": "Jazz",
    "Dallas Mavericks": "Mavericks", "Sacramento Kings": "Kings",
    "Portland Trail Blazers": "Trail Blazers",
}


def title_for(c):
    bits = ["2024-25 Panini Select", c["player"].replace('"', "")]
    par = c["parallel"]
    if par != "Base":
        bits.append(par)
    if c["insert"]:
        bits.append(c["insert"])
    if c["rc"]:
        bits.append("RC")
    bits += [TEAM_SHORT.get(c["team"], c["team"]), "Basketball"]
    t = " ".join(bits)
    if len(t) > 80:
        t = t[: t.rfind(" Basketball")]  # drop trailing sport token first
    if len(t) > 80:
        raise ValueError(f"title too long ({len(t)}): {t}")
    return t


def price_for(typ):
    return max(2.99, math.floor(typ * 1.3) + 0.99)


_scan_cache = {}
def crop_position(scan_num, pos):
    if scan_num not in _scan_cache:
        _scan_cache[scan_num] = Image.open(SCANS_DIR / f"Scan {scan_num}.jpeg")
    im = _scan_cache[scan_num]
    w, h = im.size
    cw, ch = w / 3, h / 3
    row, col = (pos - 1) // 3, (pos - 1) % 3
    crop = im.crop((int(col * cw), int(row * ch), int((col + 1) * cw), int((row + 1) * ch)))
    if min(crop.size) < 500:
        f = 500 / min(crop.size)
        crop = crop.resize((int(crop.width * f), int(crop.height * f)), Image.LANCZOS)
    return crop.convert("RGB")


def main():
    CROP_DIR.mkdir(exist_ok=True)
    seen_titles = {}
    batch, on_deck = [], []
    cards.sort(key=lambda c: -c["typ"])
    for c in cards:
        t = title_for(c)
        out = CROP_DIR / f"{c['scan']}_{c['pos']}.jpg"
        crop_position(c["scan"], c["pos"]).save(out, quality=92)
        rec = {"image": str(out), "title": t, "price": price_for(c["typ"]),
               "category": "261328", "condition": "4000",
               "scan": c["scan"], "pos": c["pos"]}
        tkey = t.lower()  # "Kel'el" vs "Kel'El" — dupes match case-insensitively
        if tkey in seen_titles:
            on_deck.append(rec)
            print(f"  ON DECK (copy of {seen_titles[tkey]}): {c['scan']}/{c['pos']} {t}")
        else:
            seen_titles[tkey] = f"{c['scan']}/{c['pos']}"
            batch.append(rec)
            print(f"  {c['scan']}/{c['pos']}  ${rec['price']:<6} {t}")

    Path("/tmp/bball_select_batch.json").write_text(json.dumps(batch, indent=1))
    Path("/tmp/bball_copies_on_deck.json").write_text(json.dumps(on_deck, indent=1))
    est = sum(b["price"] for b in batch)
    print(f"\n{len(batch)} unique listings (${est:.2f} list total), "
          f"{len(on_deck)} duplicate copies on deck")


if __name__ == "__main__":
    main()
