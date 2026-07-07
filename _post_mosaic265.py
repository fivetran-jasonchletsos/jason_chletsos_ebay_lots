"""Post the Mosaic batch (scans 265-267): 20 singles. Holds Drake Maye Notoriety
(base, already listed). Dry-run default; --apply to post."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs
import ebay_client

CROP = Path("output/split_cards")
def crop(scan, idx): return CROP / f"Scan {scan}" / f"Scan {scan}_{idx:02d}.jpg"

# (scan, idx, player, year, parallel/insert, rc, team, price)
C = [
 # Green
 (266,1,"Ray Lewis",2024,"Green",0,"Baltimore Ravens",4.99),
 (265,3,"Kyle Williams",2025,"Green",1,"New England Patriots",3.99),
 (265,5,"Greg Zuerlein",2024,"Green",0,"New York Jets",2.99),
 (265,6,"Will Anderson Jr",2024,"Green",0,"Houston Texans",3.99),
 (265,8,"Drake London",2024,"Green",0,"Atlanta Falcons",4.99),
 (265,9,"J.J. McCarthy",2024,"Green",0,"Minnesota Vikings",4.99),
 # Inserts
 (267,1,"Bijan Robinson",2024,"Epic Performers",0,"Atlanta Falcons",4.99),
 (267,7,"Larry Fitzgerald",2024,"Touchdown Masters",0,"Arizona Cardinals",3.99),
 (266,2,"Peyton Manning",2024,"Epic Performers Fluorescent Pink",0,"Indianapolis Colts",4.99),
 (266,8,"Dan Fouts",2024,"Touchdown Masters",0,"Los Angeles Chargers",2.99),
 (267,3,"Kaleb Johnson",2025,"Notoriety",1,"Pittsburgh Steelers",2.99),
 (265,2,"Colston Loveland",2025,"Notoriety",1,"Chicago Bears",3.99),
 (265,1,"Justin Jefferson",2024,"Elevate Fluorescent Pink",0,"Minnesota Vikings",6.99),
 (266,7,"Puka Nacua",2024,"Epic Performers Green Gold",0,"Los Angeles Rams",4.99),
 (265,4,"Puka Nacua",2024,"Touchdown Masters Green Gold",0,"Los Angeles Rams",4.99),
 # Base / parallel
 (266,4,"Jared Verse",2024,"Mosaic",1,"Los Angeles Rams",2.99),
 (266,5,"Bill Cowher",2024,"Mosaic",0,"Pittsburgh Steelers",2.99),
 (266,6,"Bobby Wagner",2024,"Mosaic",0,"Washington Commanders",1.99),
 (266,9,"Greg Rousseau",2024,"Mosaic",0,"Buffalo Bills",1.99),
 (265,7,"Trey Benson",2024,"Genesis",0,"Arizona Cardinals",3.99),
]

def title(pl,yr,par,rc,team):
    core=f"{yr} Panini Mosaic {pl}"
    if par and par!="Mosaic": core+=f" {par}"
    if rc: core+=" RC"
    t=f"{core} {team} Football"
    if len(t)<=80: return t
    t2=f"{core} {team}"          # drop 'Football'
    if len(t2)<=80: return t2
    return core[:80]             # last resort

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    res=[]
    for scan,idx,pl,yr,par,rc,team,price in C:
        img=crop(scan,idx)
        if not img.exists(): print("  MISSING",img); continue
        t=title(pl,yr,par,rc,team)
        r=pfs.post_card(img,t,price,cfg,tok,apply=a.apply); r["sid"]=f"{scan}_{idx}"; res.append(r)
    posted=[r for r in res if r.get("item_id")]; blocked=[r for r in res if r.get("ack")=="Blocked"]
    mode="APPLIED" if a.apply else "DRY-RUN"
    print(f"\n=== {mode}: {len(res)} cards | posted {len(posted)} | blocked {len(blocked)} ===")
    Path("output/_mosaic265_result.json").write_text(json.dumps(res,indent=1,default=str))

if __name__=="__main__": main()
