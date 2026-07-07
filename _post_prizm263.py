"""Post the 2025 Prizm batch (scans 262-264) as singles via post_from_scan.
Holds Jared Goff RWB (already live 307046652363). Dry-run default; --apply to post."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs
import ebay_client

CROP = Path("output/split_cards")
def crop(scan, idx): return CROP / f"Scan {scan}" / f"Scan {scan}_{idx:02d}.jpg"

# (scan, idx, player, parallel, rc, team, price) — Goff RWB (262,2) intentionally omitted (dupe)
C = [
 (262,1,"Derrick Harmon","",1,"Pittsburgh Steelers",2.99),
 (262,3,"Christian Watson","Disco",0,"Green Bay Packers",3.99),
 (262,4,"Donovan Jackson","Red",1,"Minnesota Vikings",3.99),
 (262,5,"Keyshawn Johnson","Red",0,"Carolina Panthers",3.99),
 (262,6,"Mason Taylor","Disco",1,"New York Jets",4.99),
 (262,7,"Tyreek Hill","",0,"Miami Dolphins",3.99),
 (262,8,"Marvin Harrison Jr","Lazer",0,"Arizona Cardinals",9.99),
 (262,9,"Jaylin Noel","Disco",1,"Houston Texans",3.99),
 (263,1,"Trent McDuffie","Red White Blue",0,"Kansas City Chiefs",3.99),
 (263,2,"Amon-Ra St. Brown","",0,"Detroit Lions",3.99),
 (263,3,"Jan Stenerud","Disco",0,"Kansas City Chiefs",3.99),
 (263,4,"Jahmyr Gibbs","",0,"Detroit Lions",4.99),
 (263,5,"Patrick Surtain II","Disco",0,"Denver Broncos",4.99),
 (263,6,"Carl Pickens","Disco",0,"Cincinnati Bengals",2.99),
 (263,7,"Joe Burrow","",0,"Cincinnati Bengals",4.99),
 (263,8,"Jaxon Smith-Njigba","",0,"Seattle Seahawks",4.99),
 (263,9,"Evan Engram","Lazer",0,"Denver Broncos",3.99),
 (264,1,"Younghoe Koo","Lazer",0,"Atlanta Falcons",2.99),
 (264,2,"Jayden Reed","Lazer",0,"Green Bay Packers",3.99),
 (264,3,"Ed Reed","Lazer",0,"Houston Texans",3.99),
 (264,4,"Maxwell Hairston","Lazer",1,"Buffalo Bills",3.99),
 (264,5,"Ed Reed","Lazer",0,"Houston Texans",3.99),
 (264,6,"Kurtis Rourke","Lazer",1,"San Francisco 49ers",2.99),
 (264,7,"Michael Penix Jr","Lazer",0,"Atlanta Falcons",4.99),
 (264,8,"Jayden Reed","Lazer",0,"Green Bay Packers",3.99),
 (264,9,"Courtland Sutton","Lazer",0,"Denver Broncos",3.99),
]

def title(pl,par,rc,team):
    parts=["2025 Panini Prizm",pl]
    if par: parts.append(par)
    if rc: parts.append("RC")
    parts.append(team); parts.append("Football")
    return " ".join(parts)[:80]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    res=[]
    for scan,idx,pl,par,rc,team,price in C:
        img=crop(scan,idx)
        if not img.exists(): print("  MISSING",img); continue
        t=title(pl,par,rc,team)
        r=pfs.post_card(img,t,price,cfg,tok,apply=a.apply); r["sid"]=f"{scan}_{idx}"; res.append(r)
    posted=[r for r in res if r.get("item_id")]; blocked=[r for r in res if r.get("ack")=="Blocked"]
    mode = "APPLIED" if a.apply else "DRY-RUN"
    print(f"\n=== {mode}: {len(res)} cards | posted {len(posted)} | blocked {len(blocked)} ===")
    Path("output/_prizm263_result.json").write_text(json.dumps(res,indent=1,default=str))

if __name__=="__main__": main()
