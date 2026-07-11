"""Post all 9 Chrome cards from scan 317. Dry-run default; --apply."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs, ebay_client
CROP=Path("output/split_cards")
def crop(s,i): return CROP/f"Scan {s}"/f"Scan {s}_{i:02d}.jpg"
# (scan,pos,player,team,parallel_words,serial,rc,price)
C=[
 (317,1,"Noah Fant","Cincinnati Bengals","Aqua Refractor","125/299",False,7.99),
 (317,4,"Darius Robinson","Arizona Cardinals","Gold XFractor",None,False,6.99),
 (317,6,"T.J. Hockenson","Minnesota Vikings","Powers",None,False,4.99),
 (317,7,"Kam Chancellor","Seattle Seahawks","Legends of the Gridiron",None,False,4.99),
 (317,9,"Penei Sewell","Detroit Lions","All-Chrome",None,False,4.99),
 (317,3,"Jonathan Taylor","Indianapolis Colts","Pink XFractor",None,False,4.99),
 (317,2,"Jeremy Ruckert","New York Jets","Pink XFractor",None,False,4.49),
 (317,5,"Keon Coleman","Buffalo Bills","Pink XFractor",None,False,4.49),
 (317,8,"Gunnar Helm","Tennessee Titans","Pink XFractor",None,True,4.49),
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
    Path("output/_chrome317_result.json").write_text(json.dumps(res,indent=1,default=str))
if __name__=="__main__": main()
