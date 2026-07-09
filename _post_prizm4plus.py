"""Post the $4+ Prizm cards (scans 268-313) as singles. Reads output/_prizm4plus.json.
Dry-run default; --apply to post."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs, ebay_client
CROP=Path("output/split_cards")
def crop(scan,idx): return CROP/f"Scan {scan}"/f"Scan {scan}_{idx:02d}.jpg"
def title(r):
    pl,par,team,rc=r["player"],r["parallel"],r["team"],r["rc"]
    core=f"2025 Panini Prizm {pl}"
    if par=="Premier Relic": core=f"2025 Panini Prizm Premier {pl} Jersey Relic"
    elif par!="base": core+=f" {par}"
    if rc and par!="Premier Relic": core+=" RC"
    t=f"{core} {team} Football"
    if len(t)<=80: return t
    t2=f"{core} {team}"
    return t2 if len(t2)<=80 else core[:80]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    sel=json.load(open("output/_prizm4plus.json")); res=[]
    for r in sel:
        img=crop(r["scan"],r["pos"])
        if not img.exists(): print("  MISSING",img); continue
        t=title(r); pr=pfs.post_card(img,t,r["price"],cfg,tok,apply=a.apply)
        pr["sid"]=f'{r["scan"]}-{r["pos"]}'; pr["title"]=t; res.append(pr)
        if not a.apply: print(f'  ${r["price"]:<5} {t}')
    posted=[x for x in res if x.get("item_id")]; blocked=[x for x in res if x.get("ack")=="Blocked"]
    print(f'\n=== {"APPLIED" if a.apply else "DRY-RUN"}: {len(res)} | posted {len(posted)} | blocked {len(blocked)} ===')
    if a.apply:
        for x in posted: print(f'  {x.get("item_id")}  {x["title"]}')
        for x in blocked: print(f'  BLOCKED (dupe): {x["title"]}')
    Path("output/_prizm4plus_result.json").write_text(json.dumps(res,indent=1,default=str))
if __name__=="__main__": main()
