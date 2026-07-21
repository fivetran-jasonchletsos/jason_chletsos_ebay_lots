"""Crop, collage, and post the first 25 baseball team lots (from baseball_posting_plan.pdf)
as brand-new eBay listings (category 261329, Sports Trading Card Lot).

Each entry: (scan_number, grid_position 1-9, display_name)
Grid position is row-major (1=top-left ... 9=bottom-right) in the 3x3 scan.
"""
import json, math
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
CROPS_DIR = Path("/tmp/lot_crops")
COLLAGE_DIR = Path("/tmp/lot_collages")
CROPS_DIR.mkdir(exist_ok=True)
COLLAGE_DIR.mkdir(exist_ok=True)

# lot_key -> (title, price, [(scan, pos, name), ...])
LOTS = {
 "angels1": ("2025 Topps Angels 5 Card Lot Dana Kikuchi Moore Neto Pujols Baseball", 8.99, [
    (401,2,"Caden Dana"), (398,9,"Yusei Kikuchi"), (392,6,"Christian Moore"),
    (397,3,"Zach Neto"), (399,2,"Albert Pujols"),
 ]),
 "athletics1": ("2025 Topps Athletics 5 Card Lot Fricano Hernaiz Hoglund Jackson McGwire", 8.99, [
    (402,5,"Marion Fricano"), (404,9,"Darell Hernaiz"), (409,1,"Gunnar Hoglund"),
    (397,5,"Reggie Jackson"), (394,6,"Mark McGwire"),
 ]),
 "astros1": ("2025 Topps Astros 5 Card Lot Altuve Alvarez Corona Diaz Janek Baseball", 8.99, [
    (398,8,"Jose Altuve"), (400,1,"Yordan Alvarez"), (399,1,"Kenedy Corona"),
    (397,7,"Yainer Diaz"), (405,6,"Hunter Janek"),
 ]),
 "bluejays": ("2025 Topps Blue Jays 5 Card Lot Guerrero Okamoto Yesavage Baseball", 8.99, [
    (391,6,"Vladimir Guerrero Jr sparkle"), (399,6,"Vladimir Guerrero Jr Titans"),
    (401,1,"Vladimir Guerrero Jr graffiti"), (410,8,"Kazuma Okamoto"), (393,2,"Trey Yesavage"),
 ]),
 "braves1": ("2025 Topps Braves 5 Card Lot Harris Jolly Jones Logan Olson Baseball", 8.99, [
    (391,5,"Hayden Harris"), (402,6,"Dave Jolly"), (405,4,"Chipper Jones"),
    (402,9,"Johnny Logan"), (395,5,"Matt Olson"),
 ]),
 "brewers1": ("2025 Topps Brewers 5 Card Lot Chourio Made Misiorowski Ortiz Baseball", 8.99, [
    (409,2,"Jackson Chourio baseballs"), (411,1,"Jackson Chourio graffiti"), (408,1,"Jesus Made"),
    (407,9,"Jacob Misiorowski"), (397,2,"Joey Ortiz"),
 ]),
 "cubs1": ("2025 Topps Cubs 5 Card Lot Caissie Crow-Armstrong Sandberg Smyth Suzuki", 8.99, [
    (408,7,"Owen Caissie Cubs"), (406,7,"Pete Crow-Armstrong"), (399,4,"Ryne Sandberg"),
    (403,3,"Steve Smyth"), (393,1,"Seiya Suzuki baseballs"),
 ]),
 "diamondbacks": ("2025 Topps Diamondbacks 4 Card Lot Arenado Carroll x3 Baseball", 7.99, [
    (409,5,"Nolan Arenado"), (396,4,"Corbin Carroll graffiti"), (406,4,"Corbin Carroll Fortune15"),
    (402,2,"Corbin Carroll Heritage 35th"),
 ]),
 "dodgers1": ("2025 Topps Dodgers 5 Card Lot Betts Freeland Freeman Koufax Baseball", 9.99, [
    (406,9,"Mookie Betts Glove Work"), (392,7,"Alex Freeland"), (404,7,"Freddie Freeman"),
    (403,5,"Sandy Koufax"), (400,8,"Mookie Betts Titans"),
 ]),
 "giants": ("2025 Topps Giants 4 Card Lot Devers Eldridge Gilbert Lee Baseball", 7.99, [
    (400,7,"Rafael Devers"), (410,3,"Bryce Eldridge"), (397,8,"Drew Gilbert"), (395,7,"Jung Hoo Lee"),
 ]),
 "guardians": ("2025 Topps Guardians 4 Card Lot Burns DeLauter Kwan Ramirez Baseball", 7.99, [
    (393,7,"Chase Burns"), (393,9,"Chase DeLauter"), (411,2,"Steven Kwan"), (406,1,"Jose Ramirez"),
 ]),
 "mariners1": ("2025 Topps Mariners 5 Card Lot Arozarena Bell Castillo Raleigh x2", 8.99, [
    (397,4,"Randy Arozarena"), (401,6,"David Bell"), (408,5,"Luis Castillo"),
    (392,4,"Cal Raleigh graffiti"), (407,4,"Cal Raleigh Heritage 1"),
 ]),
 "marlins": ("2025 Topps Marlins 2 Card Lot Caissie Hicks Baseball", 4.99, [
    (396,5,"Owen Caissie Marlins"), (403,4,"Liam Hicks"),
 ]),
 "multiteam": ("2025 Topps Legends 5 Card Lot Aybar Cabrera Guerrero Ryan Baseball", 8.99, [
    (398,4,"Erick Aybar"), (398,1,"Miguel Cabrera"), (401,4,"Carlos Estevez Robert Suarez"),
    (396,9,"Vladimir Guerrero Jr AllStar NL"), (403,8,"Nolan Ryan"),
 ]),
 "nationals": ("2025 Topps Nationals 3 Card Lot House Wood x2 Baseball", 5.99, [
    (410,2,"Brady House"), (406,8,"James Wood star"), (400,4,"James Wood Titans"),
 ]),
 "orioles": ("2025 Topps Orioles 5 Card Lot Alonso Basallo Helsley Rutschman Sugano", 8.99, [
    (392,8,"Pete Alonso"), (395,1,"Samuel Basallo"), (391,7,"Ryan Helsley"),
    (397,9,"Adley Rutschman"), (405,7,"Tomoyuki Sugano"),
 ]),
 "angels2": ("2025 Topps 75 Taylor Ward Angels Single Baseball", 2.99, [
    (404,5,"Taylor Ward"),
 ]),
 "athletics2": ("2025 Topps 75 Max Muncy Athletics Future Stars RC Baseball", 2.49, [
    (401,8,"Max Muncy"),
 ]),
 "astros2": ("2025 Topps Brice Matthews Astros Graffiti RC Baseball", 2.49, [
    (392,3,"Brice Matthews"),
 ]),
 "braves2": ("2025 Topps 75 Chris Sale Braves Crystal Parallel Baseball", 2.99, [
    (410,6,"Chris Sale"),
 ]),
 "brewers2": ("2025 Topps 75 Brandon Sproat Purple Parallel #246/250 Brewers RC", 4.99, [
    # POSTED then REVISED 2026-07-22: JC confirmed serial 246/250 — title+price updated live
    # on item 307077973371 (was $3.49 unnumbered, now $4.99 with serial in title).
    (396,6,"Brandon Sproat"),
 ]),
 "cubs2": ("2025 Topps Cubs 2 Card Lot Suzuki Swanson Baseball", 4.49, [
    (395,2,"Seiya Suzuki checkerboard"), (391,3,"Dansby Swanson"),
 ]),
 "dodgers2": ("2025 Topps Dodgers 4 Card Lot Labine Ohtani Tucker Wade Baseball", 7.99, [
    (402,8,"Clem Labine"), (395,4,"Shohei Ohtani"), (391,8,"Kyle Tucker"), (404,4,"Ben Wade"),
 ]),
 "mariners2": ("2025 Topps Mariners 5 Card Lot Raleigh Sele Ichiro Young x2 Baseball", 8.99, [
    (401,7,"Cal Raleigh Heritage 2"), (400,3,"Aaron Sele"), (407,7,"Ichiro Suzuki"),
    (399,8,"Cole Young baseballs"), (404,2,"Cole Young graffiti"),
 ]),
 "cardinals": ("2025 Topps Masyn Winn Cardinals Panini Crusade Baseball", 2.99, [
    (408,6,"Masyn Winn"),
 ]),
}

def load(scan_num):
    p = SCANS_DIR / f"Scan {scan_num}.jpeg"
    return Image.open(p)

_scan_cache = {}
def get_scan(scan_num):
    if scan_num not in _scan_cache:
        _scan_cache[scan_num] = load(scan_num)
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
    category = "261328" if len(cards) == 1 else "261329"  # single vs lot
    batch.append({"image": str(out), "title": title, "price": price, "category": category})
    print(f"{key}: {len(cards)} cards -> {out.name}  (${price}, cat {category})")

Path("/tmp/lots_batch.json").write_text(json.dumps(batch, indent=1))
print(f"\nWrote batch of {len(batch)} lots to /tmp/lots_batch.json")
