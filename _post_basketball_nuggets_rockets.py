"""Crop, collage, and post the basketball SELL lots for Denver Nuggets through
Houston Rockets (7 teams, 25 cards) as brand-new eBay listings. Scan/position
map re-verified by direct re-view of scans 433-450 on 2026-07-22.

Corrections made during this verification pass (JC flagged one, second one
self-caught on the same scan):
- Fred VanVleet (Rockets, Scan438 pos2): sheet said "base", card is Topps
  Chrome. JC caught this by physical pull.
- Jalen Johnson (Hawks, Scan438 pos7): sheet said "base", card is also Topps
  Chrome — same scan as VanVleet, same kind of mislabel, self-caught.
- Immanuel Quickley (Raptors): sheet claimed x3 copies; only 2 physical
  appearances found across all 18 scans (434 pos3, 435 pos3) covering this
  itemized portion of the batch. Posting as x2; flagged to JC.
- Kevin Durant (Rockets, sheet: "base", 1 copy for sale): no third physical
  Durant appearance found in scans 433-450 (only Scan436 pos9, already
  allocated to the KEEP pile). Dropped from this posting batch pending JC
  confirmation of where that physical card actually is.

Each entry: (scan_number, grid_position 1-9, display_name)
"""
import json
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
COLLAGE_DIR = Path("/tmp/bball_collages2")
COLLAGE_DIR.mkdir(exist_ok=True)

LOTS = {
 "nuggets": ("2025-26 Topps Nuggets 5 Card Lot Murray Braun Watson x2 Basketball", 8.99, [
    (443,2,"Jamal Murray"), (441,2,"Christian Braun Chrome"), (447,8,"Christian Braun base"),
    (433,7,"Peyton Watson 1"), (447,4,"Peyton Watson 2"),
 ]),
 "suns": ("2025-26 Topps Suns 4 Card Lot Ighodaro x3 Allen Basketball", 7.49, [
    (433,3,"Oso Ighodaro 1 base"), (438,4,"Oso Ighodaro 2 Chrome"), (446,7,"Oso Ighodaro 3"),
    (447,7,"Grayson Allen"),
 ]),
 "mavericks": ("2025-26 Topps Mavericks 4 Card Lot Irving Washington Christie Basketball", 7.99, [
    (436,1,"Kyrie Irving"), (433,2,"PJ Washington Jr"), (443,4,"Max Christie"), (439,5,"Brandon Williams"),
 ]),
 "raptors": ("2025-26 Topps Raptors 5 Card Lot Agbaji x2 Quickley x2 Dick Basketball", 8.99, [
    (433,6,"Ochai Agbaji 1"), (440,2,"Ochai Agbaji 2"), (434,3,"Immanuel Quickley 1"),
    (435,3,"Immanuel Quickley 2"), (442,3,"Gradey Dick"),
 ]),
 "kings": ("2025-26 Topps Kings 2 Card Lot Monk LaVine Chrome Basketball", 4.99, [
    (433,4,"Malik Monk"), (441,9,"Zach LaVine Chrome"),
 ]),
 "hawks": ("2025-26 Topps Hawks 3 Card Lot Webb Johnson Chrome Capela Basketball", 6.49, [
    (438,6,"Spud Webb legend"), (438,7,"Jalen Johnson Chrome"), (437,9,"Clint Capela"),
 ]),
 "rockets": ("2025-26 Topps Rockets 2 Card Lot VanVleet Chrome Smith Jr Basketball", 4.49, [
    (438,2,"Fred VanVleet Chrome"), (439,7,"Jabari Smith Jr"),
 ]),
}

for key, (title, price, cards) in LOTS.items():
    assert len(title) <= 80, f"{key} title too long: {len(title)}"
    assert len(cards) <= 5, f"{key} has {len(cards)} cards, exceeds 5-card max"

_scan_cache = {}
def get_scan(scan_num):
    if scan_num not in _scan_cache:
        _scan_cache[scan_num] = Image.open(SCANS_DIR / f"Scan {scan_num}.jpeg")
    return _scan_cache[scan_num]

def crop_position(scan_num, pos):
    im = get_scan(scan_num)
    w, h = im.size
    cw, ch = w/3, h/3
    row = (pos-1)//3
    col = (pos-1)%3
    box = (int(col*cw), int(row*ch), int((col+1)*cw), int((row+1)*ch))
    return im.crop(box)

def build_collage(crops, out_path):
    cell_h = 480
    resized = []
    for c in crops:
        w,h = c.size
        nw = int(w * cell_h / h)
        resized.append(c.resize((nw, cell_h)))
    total_w = sum(r.size[0] for r in resized) + 10*(len(resized)+1)
    collage = Image.new("RGB", (total_w, cell_h+20), "white")
    x = 10
    for r in resized:
        collage.paste(r, (x, 10))
        x += r.size[0] + 10
    collage.save(out_path, quality=90)

batch = []
for key,(title, price, cards) in LOTS.items():
    crops = [crop_position(s,p) for s,p,n in cards]
    out = COLLAGE_DIR / f"{key}.jpg"
    build_collage(crops, out)
    if len(cards) == 1:
        entry = {"image": str(out), "title": title, "price": price, "category": "261328"}
    else:
        entry = {"image": str(out), "title": title, "price": price, "category": "261329", "condition": "3000"}
    batch.append(entry)
    print(f"{key}: {len(cards)} cards -> {out.name}  (${price}, cat {entry['category']})")

Path("/tmp/bball_batch_nuggets_rockets.json").write_text(json.dumps(batch, indent=1))
total = sum(l[1] for l in LOTS.values())
total_cards = sum(len(l[2]) for l in LOTS.values())
print(f"\nWrote batch of {len(batch)} lots, {total_cards} cards, ${total:.2f} total -> /tmp/bball_batch_nuggets_rockets.json")
