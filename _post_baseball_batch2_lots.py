"""Crop, collage, and post the baseball batch-2 team lots (Scans 476-486,
73 cards, 19 lots -- Angels split into two 5-card-or-fewer lots). JC has
physically pulled these off the sorted stack; individuals were already
posted separately. See _baseball_batch2_sort_pdf.py for the sort.

Each entry: (scan_number, grid_position 1-9, display_name)
"""
import json
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
COLLAGE_DIR = Path("/tmp/bb2_lot_collages")
COLLAGE_DIR.mkdir(exist_ok=True)

LOTS = {
 "angels1": ("2025 Topps Chrome Angels 5 Card Lot McDaniels x2 Soler x2 Dana", 8.49, [
    (476,7,"Garrett McDaniels 1"), (481,1,"Garrett McDaniels 2"), (478,2,"Jorge Soler 1"),
    (480,2,"Jorge Soler 2"), (481,5,"Caden Dana"),
 ]),
 "angels2": ("2025 Topps Chrome Angels 3 Card Lot Lugo Bush Kikuchi", 5.49, [
    (482,1,"Matthew Lugo"), (483,2,"Ky Bush"), (486,1,"Yusei Kikuchi"),
 ]),
 "astros": ("2025 Topps Chrome Astros 4 Card Lot VanWey Paredes Gordon x2", 6.99, [
    (477,6,"Logan VanWey"), (482,2,"Isaac Paredes"), (485,4,"Colton Gordon 1"), (485,6,"Colton Gordon 2"),
 ]),
 "twins": ("2025 Topps Chrome Twins 4 Card Lot Roden Matthews Keaschall Fitzgerald", 6.99, [
    (477,3,"Alan Roden"), (477,7,"Zebby Matthews"), (483,9,"Luke Keaschall"), (484,1,"Ryan Fitzgerald"),
 ]),
 "tigers": ("2025 Topps Chrome Tigers 5 Card Lot Lee x2 Torkelson Paddack x2", 8.49, [
    (477,9,"Chase Lee 1"), (486,8,"Chase Lee 2"), (478,3,"Spencer Torkelson"),
    (479,8,"Chris Paddack 1"), (480,5,"Chris Paddack 2"),
 ]),
 "redsox": ("2025 Topps Chrome Red Sox 3 Card Lot Chapman May Rafaela", 5.49, [
    (482,6,"Aroldis Chapman"), (485,9,"Dustin May"), (485,8,"Ceddanne Rafaela"),
 ]),
 "bluejays": ("2025 Topps Chrome Blue Jays 3 Card Lot Dominguez x2 Barger", 5.49, [
    (479,1,"Seranthony Dominguez 1"), (485,2,"Seranthony Dominguez 2"), (480,6,"Addison Barger"),
 ]),
 "pirates": ("2025 Topps Chrome Pirates 4 Card Lot Cheng x2 Ashcraft Simon", 6.99, [
    (479,2,"Tsung-Che Cheng 1"), (484,3,"Tsung-Che Cheng 2"), (477,8,"Braxton Ashcraft"), (484,6,"Ronny Simon"),
 ]),
 "cubs": ("2025 Topps Chrome Cubs 4 Card Lot Horton x2 Alcantara Ballesteros", 6.99, [
    (481,6,"Cade Horton 1"), (482,8,"Cade Horton 2"), (485,3,"Kevin Alcantara"), (481,9,"Moises Ballesteros"),
 ]),
 "padres": ("2025 Topps Chrome Padres 5 Card Lot Wagner Adam Sears x2 Laureano", 8.49, [
    (478,5,"Will Wagner"), (478,7,"Jason Adam"), (480,1,"JP Sears 1"), (486,6,"JP Sears 2"), (486,2,"Ramon Laureano"),
 ]),
 "rangers": ("2025 Topps Chrome Rangers 3 Card Lot Rocker Crim Osuna", 5.49, [
    (477,4,"Kumar Rocker"), (478,9,"Blaine Crim"), (486,4,"Alejandro Osuna"),
 ]),
 "braves": ("2025 Topps Chrome Braves 3 Card Lot Schwellenbach Wiles Baldwin", 5.49, [
    (478,1,"Spencer Schwellenbach"), (482,7,"Nathan Wiles"), (484,8,"Drake Baldwin"),
 ]),
 "yankees": ("2025 Topps Chrome Yankees 4 Card Lot McMahon Rosario Bednar Escarra", 6.99, [
    (479,7,"Ryan McMahon"), (481,4,"Amed Rosario"), (486,5,"David Bednar"), (486,3,"JC Escarra"),
 ]),
 "rays": ("2025 Topps Chrome Rays 3 Card Lot Simpson Mangum x2 Baseball", 5.49, [
    (481,7,"Chandler Simpson"), (485,1,"Jake Mangum 1"), (485,7,"Jake Mangum 2"),
 ]),
 "royals": ("2025 Topps Chrome Royals 4 Card Lot Yastrzemski x2 Hill Cameron", 6.99, [
    (480,7,"Mike Yastrzemski 1"), (482,4,"Mike Yastrzemski 2"), (482,5,"Rich Hill"), (479,5,"Noah Cameron"),
 ]),
 "reds": ("2025 Topps Chrome Reds 2 Card Lot Stephenson Trevino Baseball", 4.49, [
    (482,3,"Tyler Stephenson"), (484,9,"Jose Trevino"),
 ]),
 "multiteam1": ("2025 Topps Chrome 5 Card Lot Gibson Henry Veen Evans Woo", 8.49, [
    (485,5,"Cade Gibson"), (486,7,"Cole Henry"), (478,8,"Zac Veen"), (476,1,"Logan Evans"), (483,3,"Bryan Woo"),
 ]),
 "multiteam2": ("2025 Topps Chrome 5 Card Lot Henderson Svanson Locklear Kim Handley", 8.49, [
    (476,4,"Logan Henderson"), (476,5,"Matt Svanson"), (477,2,"Tyler Locklear"),
    (477,1,"Hyeseong Kim"), (479,4,"Maverick Handley"),
 ]),
 "multiteam3": ("2025 Panini Prizm 4 Card Lot Fabian Williams Nikhazy Duran", 6.99, [
    (480,8,"Jud Fabian"), (480,9,"Jett Williams"), (482,9,"Doug Nikhazy"), (484,4,"Jhoan Duran"),
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
total_cards = 0
for key,(title, price, cards) in LOTS.items():
    crops = [crop_position(s,p) for s,p,n in cards]
    out = COLLAGE_DIR / f"{key}.jpg"
    build_collage(crops, out)
    entry = {"image": str(out), "title": title, "price": price, "category": "261329", "condition": "3000"}
    batch.append(entry)
    total_cards += len(cards)
    print(f"{key}: {len(cards)} cards -> {out.name}  (${price})")

Path("/tmp/bb2_lots_batch.json").write_text(json.dumps(batch, indent=1))
total_price = sum(l[1] for l in LOTS.values())
print(f"\nWrote batch of {len(batch)} lots, {total_cards} cards, ${total_price:.2f} total -> /tmp/bb2_lots_batch.json")
