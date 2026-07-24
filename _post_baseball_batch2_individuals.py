"""Crop and post the 24 individual-listing cards from baseball batch 2
(Scans 476-486, see _baseball_batch2_sort_pdf.py for the sort). Singles only --
lots are being physically pulled by JC and posted separately once ready.

Each entry: (scan_number, grid_position 1-9, title, price)

Corrected 2026-07-23 (see _fix_trout_end_stanton.py): the Trout title dropped
"Shohei Ohtani" (card is Trout-only) and the Giancarlo Stanton entry was
removed -- JC couldn't physically locate that card, so listing 307080372034
was ended rather than posted for a card not in hand (now in do_not_relist.json).
"""
import json
from pathlib import Path
from PIL import Image

SCANS_DIR = Path("/Users/jason.chletsos/Downloads")
CROP_DIR = Path("/tmp/bb2_individuals")
CROP_DIR.mkdir(exist_ok=True)

CARDS = [
 (483,1,"2025 Panini Prizm Marcelo Mayer RC Red Sox Baseball",5.99),
 (484,2,"2025 Topps Chrome Jackson Jobe RC Tigers Baseball",5.99),
 (483,6,"2025 Topps Chrome Chase Dollander RC Rockies Baseball",4.99),
 (477,5,"2025 Topps Chrome Cam Smith RC Astros Baseball",3.99),
 (481,3,"2025 Topps Chrome Dylan Crews RC Nationals Baseball",3.99),
 (479,9,"2025 Topps Chrome Cade Horton RC Cubs Baseball",3.99),
 (481,2,"2025 Topps Chrome Chandler Simpson RC Rays Baseball",2.99),
 (476,2,"2025 Topps Chrome Hyeseong Kim RC Dodgers Baseball",2.99),
 (476,9,"2025 Topps Chrome Kevin Alcantara RC Cubs Baseball",2.99),
 (481,8,"2025 Topps Chrome Brooks Lee RC Twins Baseball",2.99),
 (483,8,"2025 Panini Prizm Eury Perez Marlins Baseball",2.99),
 (476,8,"2025 Topps Chrome Mike Trout Fortune 15 Insert Angels Baseball",3.99),
 (479,6,"2025 Topps Chrome Vladimir Guerrero Jr All Star Blue Jays",3.99),
 # Giancarlo Stanton Holiday Yankees (scan 483 pos 5, $2.99) removed 2026-07-23:
 # JC could not physically locate the card; listing 307080372034 was ended
 # (EndingReason=NotAvailable) rather than shipped for a card not in hand.
 (478,4,"2025 Topps Chrome Mason Miller Future Star Padres Baseball",2.99),
 (480,4,"2025 Topps Chrome Jeremy Pena Astros Baseball",2.99),
 (478,6,"2025 Topps Chrome Aroldis Chapman Red Sox Baseball",1.99),
 (476,3,"Panini Prizm Nomar Garciaparra Red Sox Legend Baseball",2.99),
 (476,6,"Panini Prizm Omar Vizquel Cleveland Legend Baseball",1.99),
 (483,4,"Panini Prizm Jim Edmonds Cardinals Legend Baseball",1.99),
 (483,7,"Panini Prizm Tim Salmon Angels Legend Baseball",1.99),
 (480,3,"Panini Prizm Paul Molitor Brewers Legend Baseball",1.99),
 (484,7,"2025 Topps Chrome Dustin May RC Red Sox Baseball",2.99),
 (484,5,"2025 Topps Chrome David Bednar Yankees Baseball",1.99),
 (479,3,"2025 Topps Chrome Bryan Woo Mariners Baseball",1.99),
]

for s, p, t, price in CARDS:
    if len(t) > 80:
        raise ValueError(f"title too long ({len(t)}): {t}")

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

batch = []
for i, (scan, pos, title, price) in enumerate(CARDS, 1):
    crop = crop_position(scan, pos)
    out = CROP_DIR / f"{i:02d}_{title[:30].replace(' ','_').replace('/','-')}.jpg"
    crop.save(out, quality=92)
    batch.append({"image": str(out), "title": title, "price": price, "category": "261328", "condition": "4000"})
    print(f"{i:02d}. Scan{scan} pos{pos} -> {out.name}  ${price}")

Path("/tmp/bb2_individuals_batch.json").write_text(json.dumps(batch, indent=1))
print(f"\nWrote batch of {len(batch)} individual listings to /tmp/bb2_individuals_batch.json")
