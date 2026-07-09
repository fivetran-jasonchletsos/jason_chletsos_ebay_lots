"""Fix mislabeled 'Silver' flagship Panini Prizm / Prizm Draft Picks titles
(buyer-confirmed base, not Silver). Strips 'Silver Prizm'/'Silver' from titles
in the flagship-Prizm family only; leaves Select base (Silver Prizm IS the base
finish), named parallels (Die-Cut, Flash, Crusade, Wave, Hyper, Holo) and Mosaic
Silver untouched. Dry-run default; --apply to revise titles."""
import argparse, json, re
from pathlib import Path
import ebay_client, requests

EXCLUDE = ("die-cut","die cut","flash","crusade","mosaic","holo","wave","hyper","select","cracked")

def is_flagship_silver(t):
    tl=t.lower()
    if "silver" not in tl: return False
    if any(w in tl for w in EXCLUDE): return False
    return ("panini prizm" in tl) or ("prizm draft picks" in tl) or ("prizm -" in tl) or (" prizm " in tl and "prizm" in tl)

def fix_title(t):
    t2=re.sub(r"\bSilver Prizm\b","",t)
    t2=re.sub(r"\bSilver\b","",t2)
    t2=re.sub(r"\s{2,}"," ",t2).replace(" - -"," -").replace("- NFL","NFL").strip(" -")
    t2=re.sub(r"\s+"," ",t2).strip()
    return t2

def revise_title(iid, title, cfg, tok):
    body=(f'<?xml version="1.0" encoding="utf-8"?>'
          f'<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
          f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
          f'<Item><ItemID>{iid}</ItemID><Title>{ebay_client.xml_escape(title)}</Title></Item>'
          f'</ReviseItemRequest>')
    h=ebay_client.trading_headers("ReviseItem",cfg,tok)
    r=requests.post(ebay_client.TRADING_URL,data=body.encode(),headers=h,timeout=60)
    ack=ebay_client.find_tag(r.text,"Ack") or "?"
    return ack in ("Success","Warning"), (ebay_client.find_tag(r.text,"LongMessage") or "")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    snap=json.load(open("output/listings_snapshot.json"))
    L=snap.get("listings",snap) if isinstance(snap,dict) else snap
    fix=[]; skip=[]
    for x in L:
        t=x.get("title") or ""
        if "silver" not in t.lower(): continue
        if is_flagship_silver(t):
            nt=fix_title(t)
            if nt and nt!=t and len(nt)<=80: fix.append((str(x.get("item_id")),t,nt))
        else:
            skip.append((str(x.get("item_id")),t))
    print(f"FLAGSHIP SILVER -> fix: {len(fix)}   |   left alone (Select/named parallels): {len(skip)}\n")
    for iid,t,nt in fix:
        print(f'  {iid}\n    OLD: {t}\n    NEW: {nt}')
    print(f"\n--- LEFT ALONE ({len(skip)}) — confirm if any should also change ---")
    for iid,t in skip: print(f'  {iid}  {t[:66]}')
    Path("output/_silver_fix_plan.json").write_text(json.dumps([{"id":i,"old":o,"new":n} for i,o,n in fix],indent=1))
    if a.apply:
        ok=err=0; fails=[]
        for iid,t,nt in fix:
            good,msg=revise_title(iid,nt,cfg,tok)
            if good: ok+=1
            else: err+=1; fails.append((iid,msg))
        print(f"\n=== APPLIED: {ok} titles fixed · {err} failed ===")
        for f in fails[:20]: print(f'  FAIL {f[0]}: {f[1]}')

if __name__=="__main__": main()
