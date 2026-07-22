"""Crop, collage, and post the remaining 22 baseball team lots (lots 26-47 from
baseball_posting_plan.pdf) as brand-new eBay listings. Skips the team-insert
bundle per JC's instruction ("not the team cards").

Each entry: (scan_number, grid_position 1-9, display_name)
"""
import json
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
COLLAGE_DIR = Path("/tmp/lot_collages2")
COLLAGE_DIR.mkdir(exist_ok=True)

LOTS = {
 "padres1": ("2025 Topps Padres 5 Card Lot Bogaerts Machado Merrill Tatis Baseball", 8.99, [
    (391,9,"Xander Bogaerts"), (395,3,"Manny Machado"), (394,9,"Jackson Merrill baseballs"),
    (410,7,"Jackson Merrill graffiti"), (392,9,"Fernando Tatis Jr graffiti"),
 ]),
 "padres2": ("2025 Topps Fernando Tatis Jr 2 Card Lot Padres Baseball", 4.49, [
    (407,2,"Fernando Tatis Jr baseballs"), (406,2,"Fernando Tatis Jr 1990"),
 ]),
 "phillies": ("2025 Topps Phillies 2 Card Lot Schwarber Turner Baseball", 4.49, [
    (392,2,"Kyle Schwarber"), (409,6,"Trea Turner"),
 ]),
 "pirates1": ("2025 Topps Pirates 5 Card Lot Chandler Clemente Cruz Gonzales", 8.99, [
    (394,7,"Bubba Chandler copy1"), (399,5,"Bubba Chandler copy2"), (399,3,"Roberto Clemente"),
    (400,2,"Oneil Cruz"), (391,1,"Nick Gonzales"),
 ]),
 "pirates2": ("2025 Topps Pirates 3 Card Lot Purkey Skenes Wagner Legends", 6.49, [
    (402,3,"Bob Purkey"), (408,2,"Paul Skenes"), (403,1,"Honus Wagner"),
 ]),
 "rangers1": ("2025 Topps Rangers 5 Card Lot Beltre Burger Langford Seager", 8.99, [
    (406,3,"Adrian Beltre"), (397,6,"Jake Burger"), (392,1,"Wyatt Langford"),
    (406,6,"Ivan Rodriguez"), (394,4,"Corey Seager copy1"),
 ]),
 "rangers2": ("2025 Topps Rangers 2 Card Lot Seager deGrom Baseball", 4.49, [
    (394,5,"Corey Seager copy2"), (398,3,"Jacob deGrom"),
 ]),
 "rays": ("2025 Topps Rays 2 Card Lot Caminero Taylor Baseball", 4.49, [
    (395,6,"Junior Caminero"), (408,8,"Brayden Taylor"),
 ]),
 "redsox1": ("2025 Topps Red Sox 5 Card Lot Crochet Devers Duran Mayer", 8.99, [
    (403,2,"Garrett Crochet"), (394,1,"Rafael Devers Grapefruit"), (393,6,"Jarren Duran Future Stars"),
    (403,9,"Jarren Duran graffiti"), (406,5,"Marcelo Mayer"),
 ]),
 "redsox2": ("2025 Topps Red Sox 3 Card Lot Olson Tolle Yastrzemski", 6.49, [
    (401,3,"Karl Olson"), (407,1,"Payton Tolle"), (400,5,"Carl Yastrzemski"),
 ]),
 "reds1": ("2025 Topps Reds 5 Card Lot Abbott De La Cruz x2 Lowder x2", 8.99, [
    (391,4,"Andrew Abbott"), (394,8,"Elly De La Cruz RC"), (398,5,"Elly De La Cruz Heritage"),
    (395,8,"Rhett Lowder RC"), (408,3,"Rhett Lowder Certified Stars"),
 ]),
 "reds2": ("2025 Topps Reds 4 Card Lot Lowder x3 Stewart Baseball", 7.49, [
    (407,5,"Rhett Lowder Future Stars"), (407,6,"Rhett Lowder Chrome Jersey"),
    (405,8,"Rhett Lowder Call to Arms"), (404,6,"Sal Stewart"),
 ]),
 "rockies": ("2025 Topps 75 Zac Veen Rockies Chrome Parallel Baseball", 2.49, [
    (409,3,"Zac Veen"),
 ]),
 "royals": ("2025 Topps Bobby Witt Jr 2 Card Lot Royals Baseball", 4.99, [
    (395,9,"Bobby Witt Jr Gameday Drip"), (402,1,"Bobby Witt Jr Terrors"),
 ]),
 "senators": ("2025 Topps 75 Camilo Pascual Senators Vintage Tribute Baseball", 2.49, [
    (404,1,"Camilo Pascual"),
 ]),
 "tigers1": ("2025 Topps Tigers 5 Card Lot Greene Jones Melton Skubal x2", 8.99, [
    (398,7,"Riley Greene"), (403,6,"Jahmai Jones"), (391,2,"Troy Melton"),
    (393,8,"Tarik Skubal baseballs"), (396,1,"Tarik Skubal star"),
 ]),
 "tigers2": ("2025 Topps Tigers 2 Card Lot Sommers Torkelson Baseball", 4.49, [
    (403,7,"Drew Sommers"), (399,7,"Spencer Torkelson"),
 ]),
 "twins": ("2025 Topps Twins 5 Card Lot Buxton Lee x3 Lewis Baseball", 8.99, [
    (410,5,"Byron Buxton"), (396,2,"Brooks Lee copy1"), (396,7,"Brooks Lee copy2"),
    (404,8,"Brooks Lee Future Stars"), (396,3,"Royce Lewis"),
 ]),
 "whitesox1": ("2025 Topps White Sox 5 Card Lot Aparicio Hess Montgomery Murakami", 8.99, [
    (405,1,"Luis Aparicio"), (407,3,"Ben Hess"), (408,9,"Braden Montgomery"),
    (393,5,"Munetaka Murakami baseballs"), (409,4,"Munetaka Murakami graffiti"),
 ]),
 "whitesox2": ("2025 Topps White Sox 3 Card Lot Quero Teel Thomas Legend", 6.49, [
    (393,3,"Edgar Quero"), (396,8,"Kyle Teel"), (405,3,"Frank Thomas"),
 ]),
 "yankees1": ("2025 Topps Yankees 5 Card Lot Goldschmidt Judge x4 Baseball", 9.99, [
    (407,8,"Paul Goldschmidt"), (394,2,"Aaron Judge Grapefruit"), (405,5,"Aaron Judge Call to Arms"),
    (402,4,"Aaron Judge 62 HR"), (404,3,"Aaron Judge 144 RBI"),
 ]),
 "yankees2": ("2025 Topps Yankees 4 Card Lot Rodon Schlittler x2 Stanton", 7.49, [
    (401,9,"Carlos Rodon"), (393,4,"Cam Schlittler baseballs"),
    (392,5,"Cam Schlittler graffiti"), (397,1,"Giancarlo Stanton"),
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

Path("/tmp/lots_batch_26_47.json").write_text(json.dumps(batch, indent=1))
print(f"\nWrote batch of {len(batch)} lots to /tmp/lots_batch_26_47.json")
