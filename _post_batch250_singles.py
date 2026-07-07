"""Post the batch250 SINGLES (scans 252-261) via post_from_scan.post_card.
Crops resolve through the verified REMAP (catalog block -> real scan file).
Titles built from the verified catalog. [VERIFY-LIVE] singles are EXCLUDED
(likely already listed). Dry-run by default; --apply to post for real."""
import argparse, json
from pathlib import Path
import post_from_scan as pfs
import ebay_client, promote
from _batch250_catalog import C   # (block, idx, player, product, parallel, rc)

REMAP = {252:257, 253:261, 254:253, 255:255, 256:256,
         257:260, 258:258, 259:259, 260:254, 261:252}
CAT = {(b, i): (player, prod, par, rc) for (b, i, player, prod, par, rc) in C}

# (block, idx, price) — the NON-live singles from the alphabetized pull sheet.
# The 7 [VERIFY-LIVE] singles are intentionally omitted.
SINGLES = [
 (253,1,10.99),(261,5,8.99),(260,9,5.99),(256,2,4.99),(259,5,4.99),
 (259,3,5.99),(252,3,6.99),(259,9,5.99),(258,3,7.99),(253,2,4.99),
 (257,3,3.99),(257,1,3.99),(261,4,8.99),(256,8,4.99),(259,1,4.99),
 (256,5,3.99),(256,7,3.99),(255,6,4.99),(260,3,3.99),(259,2,4.99),
 (253,3,3.99),(253,9,3.99),(252,7,3.99),(254,6,6.99),(258,9,6.99),
]

BRAND = {
 "Prizm":"Panini Prizm","Select":"Panini Select","Mosaic":"Panini Mosaic",
 "Panini Revolution":"Panini Revolution","Phoenix":"Panini Phoenix",
 "Donruss":"Panini Donruss","Optic":"Panini Donruss Optic",
 "Contenders":"Panini Contenders","Totally Certified":"Panini Totally Certified",
 "Prizm Draft":"Panini Prizm Draft Picks","Topps Cosmic":"Topps Chrome Cosmic",
 "Topps":"Topps",
}

def crop_path(block, idx):
    f = REMAP.get(block, block)
    return Path(f"output/split_cards/Scan {f}/Scan {f}_{idx:02d}.jpg")

def make_title(player, product, parallel, rc):
    parts = ["2025", BRAND.get(product, product), player]
    if parallel: parts.append(parallel)
    if rc: parts.append("RC")
    parts.append("Football")
    return " ".join(parts)[:80]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--force", action="store_true", help="post even if a title dupe is found")
    args = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    token = ebay_client.get_write_token(cfg)
    if args.force:
        pfs.post_card.force = True

    results = []
    for block, idx, price in SINGLES:
        meta = CAT.get((block, idx))
        if not meta:
            print(f"  SKIP ({block},{idx}) — not in catalog"); continue
        player, prod, par, rc = meta
        img = crop_path(block, idx)
        if not img.exists():
            print(f"  SKIP {player} — crop missing {img}"); continue
        title = make_title(player, prod, par, rc)
        r = pfs.post_card(img, title, price, cfg, token, apply=args.apply)
        r["block_idx"] = f"{block}_{idx}"
        results.append(r)

    posted = [r for r in results if r.get("item_id")]
    blocked = [r for r in results if r.get("ack") == "Blocked"]
    failed = [r for r in results if r.get("ack") not in ("Success","Warning","Blocked") and not r.get("dry_run")]
    print(f"\n=== {'APPLIED' if args.apply else 'DRY-RUN'}: "
          f"{len(results)} singles | posted {len(posted)} | blocked-dupe {len(blocked)} | failed {len(failed)} ===")
    Path("output/_batch250_singles_result.json").write_text(json.dumps(results, indent=1))

if __name__ == "__main__":
    main()
