"""Post the batch250 LOTS (<=4 cards each) as fresh FixedPriceItem lots
(category 261329) via build_lot_listing.add_lot. Collage built from the
verified crops (REMAP block -> real scan file). Lots whose cards include a
[VERIFY-LIVE] component are HELD (oversell risk) unless --include-flagged.
Dry-run by default; --apply to post."""
import argparse, json
from pathlib import Path
from PIL import Image
import build_lot_listing as bl
import post_from_scan as pfs
import ebay_client

REMAP = {252:257, 253:261, 254:253, 255:255, 256:256,
         257:260, 258:258, 259:259, 260:254, 261:252}
CROP = Path("output/split_cards")
COLL = Path("output/_lot_collages"); COLL.mkdir(exist_ok=True)

def crop_path(block, idx):
    f = REMAP.get(block, block)
    return CROP / f"Scan {f}" / f"Scan {f}_{idx:02d}.jpg"

def build_collage(cards, out_path):
    imgs = [Image.open(crop_path(b, i)).convert("RGB") for (b, i, *_ ) in cards]
    cell_h = 460
    cells = [im.resize((int(im.width * cell_h / im.height), cell_h)) for im in imgs]
    pad, cols = 18, 2
    rows = [cells[i:i+cols] for i in range(0, len(cells), cols)]
    cell_w = max(c.width for c in cells)
    canvas_w = pad + cols * (cell_w + pad)
    canvas_h = pad + len(rows) * (cell_h + pad)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    for r, row in enumerate(rows):
        row_w = len(row) * (cell_w + pad) - pad
        x0 = (canvas_w - row_w) // 2
        y = pad + r * (cell_h + pad)
        for im in row:
            canvas.paste(im, (x0 + (cell_w - im.width)//2, y)); x0 += cell_w + pad
    canvas.save(out_path, "JPEG", quality=90)
    return out_path

# (ebay_title, price, player, team, [ (block, idx, label, live) ... ])
LOTS = [
 ("2025 Mike Evans Buccaneers 4 Card Lot Prizm Select Mosaic Donruss Football",10.99,"Mike Evans","Tampa Bay Buccaneers",
   [(254,3,"Prizm",False),(254,4,"Select",False),(254,5,"Mosaic",False),(254,1,"Donruss",False)]),
 ("2025 Mike Evans Buccaneers 4 Card Lot Cosmic Contenders Totally Certified",9.99,"Mike Evans","Tampa Bay Buccaneers",
   [(254,2,"Topps Chrome Cosmic",False),(254,9,"Prizm Draft",False),(254,7,"Totally Certified",False),(254,8,"Contenders",False)]),
 ("2025 Matthew Stafford Rams 4 Card Lot Prizm Mosaic Contenders Football",9.99,"Matthew Stafford","Los Angeles Rams",
   [(258,5,"Prizm",False),(258,4,"Mosaic",False),(258,7,"Mosaic Silver",False),(258,2,"Contenders",False)]),
 ("2025 Chargers Defense 4 Card Lot Derwin James Tremaine Edmunds Football",6.99,"Various","Various",
   [(261,2,"Derwin James Mosaic",False),(261,6,"Derwin James Mosaic",False),(259,4,"Tremaine Edmunds",False),(261,1,"Jordan James RC",False)]),
 ("2025 Topps Chrome Cosmic Rookie 4 Card Lot Ratledge Savaiinaea RC Football",7.99,"Various","Various",
   [(253,7,"Tate Ratledge RC",False),(260,5,"Jacory Croskey-Merritt RC",False),(255,9,"Mike Evans Cosmic",False),(260,8,"Jonah Savaiinaea RC",False)]),
 ("2025 Rookie WR RB 4 Card Lot Tre Harris Tory Horton Woody Marks RC Football",7.99,"Various","Various",
   [(253,5,"Tre Harris RC",False),(253,4,"Tory Horton RC",False),(257,6,"Woody Marks RC",False),(259,6,"DJ Giddens RC",False)]),
 ("NFL Legends 4 Card Lot Tony Dorsett Hines Ward Michael Irvin Eric Allen HOF",8.99,"Various","Various",
   [(257,7,"Tony Dorsett",False),(259,8,"Hines Ward",False),(253,6,"Michael Irvin",False),(261,7,"Eric Allen HOF",False)]),
 ("NFL 4 Card Lot Jamal Anderson Dwight Freeney Keyshawn Johnson Tillman",6.99,"Various","Various",
   [(261,3,"Jamal Anderson",False),(261,8,"Dwight Freeney",False),(256,9,"Keyshawn Johnson",False),(253,8,"Cedric Tillman",False)]),
 ("2025 4 Card Lot Dalton Kincaid Dawson Knox Evan Engram Jakobi Meyers Football",6.99,"Various","Various",
   [(252,1,"Dalton Kincaid",False),(257,2,"Dawson Knox",False),(252,2,"Evan Engram",False),(252,8,"Jakobi Meyers",False)]),
 ("2025 Panini Prizm 4 Card Lot Lattimore Sneed Kwity Paye Braelon Allen Football",6.99,"Various","Various",
   [(259,7,"Marshon Lattimore",False),(252,4,"L'Jarius Sneed",False),(256,6,"Kwity Paye",False),(256,3,"Braelon Allen",False)]),
 ("2025 4 Card Lot Jake Ferguson Gesicki Jaylen Warren Breece Hall Football",5.99,"Various","Various",
   [(252,9,"Jake Ferguson",False),(257,8,"Mike Gesicki",False),(256,4,"Jaylen Warren",False),(258,1,"Breece Hall Revolution",False)]),
 # --- FLAGGED (contain a [VERIFY-LIVE] component) ---
 ("2025 QB Lot Stafford Jordan Addison Mike Vrabel 4 Cards Football",6.99,"Various","Various",
   [(258,6,"Stafford Contenders",False),(261,9,"Stafford Select",False),(256,1,"Jordan Addison",False),(260,7,"Mike Vrabel",True)]),
 ("2025 Rookie 4 Card Lot Jalen Milroe Arian Smith Jaydon Blue RC Football",7.99,"Various","Various",
   [(252,5,"Arian Smith RC",False),(252,6,"Jalen Milroe RC",False),(257,4,"Jaydon Blue RC",False),(257,5,"Pat Bryant RC",True)]),
 ("2025 Rookie Color 4 Card Lot Tai Felton Emmanwori Tyler Baron RC Football",8.99,"Various","Various",
   [(255,4,"Tai Felton Elevate",True),(258,8,"Tai Felton Select",False),(257,9,"Nick Emmanwori Purple",True),(260,6,"Tyler Baron RC",False)]),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--include-flagged", action="store_true",
                    help="also post lots that contain a [VERIFY-LIVE] card (oversell risk)")
    args = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    token = ebay_client.get_write_token(cfg)

    results = []
    for title, price, player, team, cards in LOTS:
        flagged = any(c[3] for c in cards)
        if flagged and not args.include_flagged:
            print(f"  HOLD (verify-live): {title[:60]}")
            results.append({"title": title, "held": True}); continue
        # verify all crops exist
        missing = [f"{b}_{i}" for (b,i,*_) in cards if not crop_path(b,i).exists()]
        if missing:
            print(f"  SKIP {title[:40]} — missing crops {missing}"); continue
        coll = build_collage(cards, COLL / (f"lot_{abs(hash(title))%10**8}.jpg"))
        print(f"\n  Lot: {title[:70]}  (${price:.2f})")
        if not args.apply:
            print(f"    [dry-run] collage {coll.name}; cards: " + ", ".join(c[2] for c in cards))
            results.append({"title": title, "dry_run": True}); continue
        purl = pfs.upload_image(coll, token, cfg)
        lot = {"title": title, "price": price, "player": player, "team": team,
               "cards": [(i, name) for (b, i, name, live) in cards]}
        new_id = bl.add_lot(lot, purl, token, cfg, apply=True)
        results.append({"title": title, "item_id": new_id})

    posted = [r for r in results if r.get("item_id")]
    held = [r for r in results if r.get("held")]
    print(f"\n=== {'APPLIED' if args.apply else 'DRY-RUN'}: lots posted {len(posted)} | held {len(held)} ===")
    Path("output/_batch250_lots_result.json").write_text(json.dumps(results, indent=1))

if __name__ == "__main__":
    main()
