"""Post the batch250 flagged items that dedup + crop verification cleared as
genuinely NEW: 3 singles (Caleb Williams, Kelvin Banks Prizm Green, RJ Harvey)
and the Rookie Skill Fliers lot (Pat Bryant confirmed base Prizm, not the live
Purple/Pink). Dry-run by default; --apply to post."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs
import build_lot_listing as bl
import ebay_client
from _post_batch250_lots import build_collage, COLL

REMAP = {252:257,253:261,254:253,255:255,256:256,257:260,258:258,259:259,260:254,261:252}
CROP = Path("output/split_cards")
def crop(b,i):
    f=REMAP.get(b,b); return CROP/f"Scan {f}"/f"Scan {f}_{i:02d}.jpg"

# (block, idx, title, price)
SINGLES = [
 (260,4,"2025 Panini Prizm Caleb Williams Global Reach Chicago Bears Football",6.99),
 (255,5,"2025 Panini Prizm Kelvin Banks Jr Green RC New Orleans Saints Football",4.99),
 (260,2,"2025 Panini Prizm RJ Harvey Emergent RC Denver Broncos Football",4.99),
]
# One cleared lot
LOT = ("2025 Rookie 4 Card Lot Jalen Milroe Arian Smith Jaydon Blue Pat Bryant RC",7.99,"Various","Various",
       [(252,5,"Arian Smith RC"),(252,6,"Jalen Milroe RC"),(257,4,"Jaydon Blue RC"),(257,5,"Pat Bryant RC")])

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    pfs.post_card.force=True  # dedup already verified by hand; skip title-guard
    res=[]
    for b,i,title,price in SINGLES:
        img=crop(b,i)
        if not img.exists(): print("  MISSING",img); continue
        r=pfs.post_card(img,title,price,cfg,tok,apply=a.apply); res.append(r)
    # lot
    title,price,player,team,cards=LOT
    img=build_collage(cards, COLL/"lot_skillfliers.jpg")
    print(f"\n  Lot: {title[:70]} (${price:.2f})")
    if a.apply:
        purl=pfs.upload_image(img,tok,cfg)
        lot={"title":title,"price":price,"player":player,"team":team,
             "cards":[(i,name) for (b,i,name) in cards]}
        nid=bl.add_lot(lot,purl,tok,cfg,apply=True); res.append({"lot":title,"item_id":nid})
    else:
        print("    [dry-run] collage",img.name)
    Path("output/_post_cleared_result.json").write_text(json.dumps(res,indent=1,default=str))

if __name__=="__main__": main()
