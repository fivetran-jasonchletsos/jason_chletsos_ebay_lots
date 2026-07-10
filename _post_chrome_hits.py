"""Post the numbered + Gold Chrome hits (4 cards). Dry-run default; --apply."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs, ebay_client
CROP=Path("output/split_cards")
def crop(s,i): return CROP/f"Scan {s}"/f"Scan {s}_{i:02d}.jpg"
# (scan,pos,player,team,parallel_words,serial,rc,price)
C=[
 (316,4,"Breece Hall","New York Jets","Green Refractor","53/99",False,12.99),
 (314,1,"Josh Sweat","Arizona Cardinals","Aqua Refractor","096/150",False,7.99),
 (316,3,"JT Tuimoloau","Indianapolis Colts","Gold XFractor",None,True,6.99),
 (315,1,"Jonah Savaiinaea","Miami Dolphins","Gold XFractor",None,True,6.99),
]
def title(pl,team,par,serial,rc):
    core=f"2025 Topps Chrome {pl} {par}"
    if serial: core+=f" {serial}"
    if rc: core+=" RC"
    t=f"{core} {team} Football"
    if len(t)<=80: return t
    t2=f"{core} {team}"
    return t2 if len(t2)<=80 else core[:80]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    res=[]
    for s,i,pl,team,par,serial,rc,price in C:
        img=crop(s,i)
        if not img.exists(): print("  MISSING",img); continue
        t=title(pl,team,par,serial,rc)
        r=pfs.post_card(img,t,price,cfg,tok,apply=a.apply); r["title"]=t; r["price"]=price; res.append(r)
        if not a.apply: print(f'  ${price:<6} {t}')
    posted=[r for r in res if r.get("item_id")]; blocked=[r for r in res if r.get("ack")=="Blocked"]
    print(f'\n=== {"APPLIED" if a.apply else "DRY-RUN"}: {len(res)} | posted {len(posted)} | blocked {len(blocked)} ===')
    if a.apply:
        for r in posted: print(f'  {r.get("item_id")}  {r["title"]}')
        for r in blocked: print(f'  BLOCKED: {r["title"]}')
    Path("output/_chrome_hits_result.json").write_text(json.dumps(res,indent=1,default=str))
if __name__=="__main__": main()
