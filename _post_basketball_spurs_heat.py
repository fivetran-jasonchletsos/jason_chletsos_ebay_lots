"""Crop, collage, and post the basketball SELL lots for Spurs through Miami Heat
(18 teams, 67 cards) as brand-new eBay listings. Scan/position map fully
re-verified by direct re-view of all 15 scans on 2026-07-22 (not from memory).

Each entry: (scan_number, grid_position 1-9, display_name)
"""
import json
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
COLLAGE_DIR = Path("/tmp/bball_collages")
COLLAGE_DIR.mkdir(exist_ok=True)

LOTS = {
 "spurs1": ("2025-26 Topps Spurs 5 Card Lot Sochan x2 Barnes Castle Paul", 8.49, [
    (444,1,"Jeremy Sochan copy1"), (435,2,"Jeremy Sochan copy2"), (441,1,"Harrison Barnes Chrome"),
    (436,6,"Stephon Castle Chrome"), (436,7,"Chris Paul"),
 ]),
 "spurs2": ("2025-26 Topps Steve Kerr Spurs Legend Basketball", 2.99, [
    (436,8,"Steve Kerr legend"),
 ]),
 "clippers": ("2025-26 Topps Clippers 4 Card Lot Powell x3 Jones Jr", 7.49, [
    (444,2,"Norman Powell 1"), (440,6,"Norman Powell 2"), (446,5,"Norman Powell 3"), (442,6,"Derrick Jones Jr"),
 ]),
 "pistons1": ("2025-26 Topps Pistons 5 Card Lot Cunningham Thomas Ivey Basketball", 8.99, [
    (444,4,"Cade Cunningham 1"), (440,8,"Cade Cunningham 2"), (433,9,"Isaiah Thomas 1"),
    (446,2,"Isaiah Thomas 2"), (434,5,"Jaden Ivey 1"),
 ]),
 "pistons2": ("2025-26 Topps Pistons 2 Card Lot Ivey Duren Basketball", 4.49, [
    (435,6,"Jaden Ivey 2"), (437,6,"Jalen Duren"),
 ]),
 "nets": ("2025-26 Topps Nic Claxton Nets Basketball", 2.49, [
    (444,5,"Nic Claxton"),
 ]),
 "celtics": ("2025-26 Topps Kristaps Porzingis Celtics Basketball", 2.99, [
    (444,6,"Kristaps Porzingis"),
 ]),
 "bulls1": ("2025-26 Topps Bulls 5 Card Lot White x3 Giddey Ball Basketball", 8.49, [
    (444,7,"Coby White 1"), (440,3,"Coby White 2"), (446,8,"Coby White 3"),
    (439,1,"Josh Giddey"), (439,9,"Lonzo Ball"),
 ]),
 "bulls2": ("2025-26 Topps Patrick Williams Bulls Basketball", 2.99, [
    (442,9,"Patrick Williams"),
 ]),
 "thunder": ("2025-26 Topps Thunder 5 Card Lot Hartenstein Wiggins Holmgren Joe", 8.99, [
    (444,8,"Isaiah Hartenstein 1"), (447,1,"Isaiah Hartenstein 2"), (441,7,"Aaron Wiggins Chrome"),
    (447,9,"Chet Holmgren"), (433,5,"Isaiah Joe"),
 ]),
 "wizards": ("2025-26 Topps Wizards 4 Card Lot Coulibaly Holmes Sarr Basketball", 7.49, [
    (443,8,"Bilal Coulibaly 1"), (435,7,"Bilal Coulibaly 2"), (440,1,"Richaun Holmes Chrome"), (436,4,"Alex Sarr"),
 ]),
 "magic": ("2025-26 Topps Magic 3 Card Lot Black x2 Banchero Basketball", 6.49, [
    (445,1,"Anthony Black 1"), (435,5,"Anthony Black 2"), (445,8,"Paolo Banchero"),
 ]),
 "blazers": ("2025-26 Topps Deni Avdija Trail Blazers Basketball", 2.99, [
    (439,6,"Deni Avdija"),
 ]),
 "cavaliers": ("2025-26 Topps Cavaliers 3 Card Lot Mobley Garland Jerome", 6.49, [
    (445,3,"Evan Mobley Chrome"), (445,7,"Darius Garland"), (437,8,"Ty Jerome"),
 ]),
 "pelicans": ("2025-26 Topps Pelicans 3 Card Lot Missi Jones Murphy Chrome", 6.49, [
    (445,4,"Yves Missi"), (446,9,"Herbert Jones"), (441,6,"Trey Murphy III Chrome"),
 ]),
 "timberwolves": ("2025-26 Topps Timberwolves 4 Card Lot Reid x3 Garnett Legend", 7.49, [
    (434,1,"Naz Reid 1"), (445,5,"Naz Reid 2"), (437,1,"Naz Reid 3"), (436,3,"Kevin Garnett legend"),
 ]),
 "pacers1": ("2025-26 Topps Pacers 5 Card Lot McConnell Mathurin Nembhard", 8.99, [
    (445,6,"TJ McConnell Chrome"), (441,5,"Bennedict Mathurin Chrome"), (434,7,"Andrew Nembhard 1"),
    (442,5,"Andrew Nembhard 2"), (437,4,"Andrew Nembhard 3"),
 ]),
 "pacers2": ("2025-26 Topps Obi Toppin Pacers Basketball", 2.99, [
    (447,2,"Obi Toppin"),
 ]),
 "hornets": ("2025-26 Topps Hornets 3 Card Lot LaMelo Ball x2 Salaun", 6.49, [
    (445,9,"LaMelo Ball Chrome"), (446,4,"LaMelo Ball base"), (433,1,"Tidjane Salaun"),
 ]),
 "warriors": ("2025-26 Topps Warriors 2 Card Lot Post Kuminga Basketball", 4.49, [
    (446,1,"Quinten Post"), (442,8,"Jonathan Kuminga"),
 ]),
 "grizzlies": ("2025-26 Topps Grizzlies 4 Card Lot Bane x3 Jackson Jr Basketball", 7.49, [
    (433,8,"Desmond Bane 1 base"), (441,3,"Desmond Bane 2 Chrome"), (446,6,"Desmond Bane 3 base"),
    (441,4,"Jaren Jackson Jr Chrome"),
 ]),
 "heat": ("2025-26 Topps Heat 4 Card Lot Herro Jaquez Jr x2 Adebayo", 7.49, [
    (444,9,"Tyler Herro"), (443,7,"Jaime Jaquez Jr 1"), (440,4,"Jaime Jaquez Jr 2"), (437,2,"Bam Adebayo"),
 ]),
}

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

Path("/tmp/bball_batch_spurs_heat.json").write_text(json.dumps(batch, indent=1))
print(f"\nWrote batch of {len(batch)} lots to /tmp/bball_batch_spurs_heat.json")
