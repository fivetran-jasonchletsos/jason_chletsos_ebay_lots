"""Post the reviewed Mosaic batch (scans 307-311) as singles. Reads the deduped
pull list (output/_mosaic_pull2.json) so only the 41 uniques go up; the 2 base
dupes + Drake Maye Notoriety (already listed) are already excluded there.
Dry-run default; --apply to post."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs
import ebay_client

CROP = Path("output/split_cards")
def crop(loc):
    s,p = loc.split("-")
    return CROP / f"Scan {s}" / f"Scan {s}_{int(p):02d}.jpg"

STARS = {"Brock Bowers","Jayden Daniels","A.J. Brown","Jahmyr Gibbs","Puka Nacua",
 "Marvin Harrison Jr.","Dak Prescott","Trey McBride","Shedeur Sanders","Travis Hunter",
 "Quinshon Judkins","Emeka Egbuka","Colston Loveland","Matthew Golden","Kurt Warner",
 "Larry Fitzgerald","John Elway","Calvin Johnson","Michael Irvin","Earl Campbell",
 "DK Metcalf","Bryce Young"}
INSERTS = {"Notoriety","Elevate","Epic Performers","Touchdown Masters","England Games","Hall of Fame"}

def price(u):
    p, rc, pl = u["parallel"], u["rc"], u["player"]
    if p in INSERTS: return 4.99 if pl in STARS else 3.99
    if p == "Red":   return 4.49 if rc else 3.99
    if p == "Genesis": return 3.99
    if pl in STARS:  return 3.49
    return 2.99 if rc else 2.49

def title(u):
    core = f"2025 Panini Mosaic {u['player']}"
    par = u["parallel"]
    if par not in ("base","Position insert"): core += f" {par}"
    if u["rc"]: core += " RC"
    t = f"{core} {u['team']} Football"
    if len(t) <= 80: return t
    t2 = f"{core} {u['team']}"
    return t2 if len(t2) <= 80 else core[:80]

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text()); tok = ebay_client.get_write_token(cfg)
    uniq = json.load(open("output/_mosaic_pull2.json"))["uniq"]
    res = []
    for u in uniq:
        img = crop(u["locs"][0])
        if not img.exists(): print("  MISSING", img); continue
        t = title(u); pr = price(u)
        r = pfs.post_card(img, t, pr, cfg, tok, apply=a.apply)
        r["sid"] = u["locs"][0]; r["title"] = t; r["price"] = pr; res.append(r)
        if not a.apply: print(f'  ${pr:<5} {t}')
    posted = [r for r in res if r.get("item_id")]; blocked = [r for r in res if r.get("ack") == "Blocked"]
    mode = "APPLIED" if a.apply else "DRY-RUN"
    print(f"\n=== {mode}: {len(res)} cards | posted {len(posted)} | blocked {len(blocked)} ===")
    if a.apply:
        for r in posted: print(f'  {r.get("item_id")}  {r["title"]}')
        for r in blocked: print(f'  BLOCKED (dupe): {r["title"]}')
    Path("output/_mosaic307_result.json").write_text(json.dumps(res, indent=1, default=str))

if __name__ == "__main__": main()
