"""Drop lot prices ~20% (clean .99 endings, $5.99 floor), keeping Best Offer.
Reuses repricing_agent.revise_price (minimal-ReviseItem fallbacks included).
Dry-run default; --apply to push."""
import argparse, json, math
from pathlib import Path
import repricing_agent as ra
import ebay_client

CUT, FLOOR = 0.20, 5.99

def revise_lot(item_id, np, ebc, tok):
    """Price + Best Offer only (NO condition field — lots reject the singles
    condition id). Falls back to price-only if Best Offer isn't enabled, then to
    a bare minimal revise for inventory-flagged items (err 21919474)."""
    acc = round(np * ra.REVISE_ACCEPT_PCT, 2); dec = round(np * ra.REVISE_DECLINE_PCT, 2)
    NS = ra.EBAY_NS
    def wrap(inner):
        return (f'<?xml version="1.0" encoding="utf-8"?>\n<ReviseItemRequest xmlns="{NS}">'
                f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
                f'<Item>{inner}</Item></ReviseItemRequest>')
    price = f'<ItemID>{item_id}</ItemID><StartPrice currencyID="USD">{np:.2f}</StartPrice>'
    bo = ('<ListingDetails>'
          f'<BestOfferAutoAcceptPrice currencyID="USD">{acc:.2f}</BestOfferAutoAcceptPrice>'
          f'<MinimumBestOfferPrice currencyID="USD">{dec:.2f}</MinimumBestOfferPrice></ListingDetails>')
    r = ra._post_revise(wrap(price + bo), ebc)
    if not r["ok"] and any("offer" in (e.get("msg") or "").lower() for e in r["errors"]):
        r = ra._post_revise(wrap(price), ebc)
    if not r["ok"] and any(e.get("code") == "21919474" or "inventory item" in (e.get("msg") or "").lower() for e in r["errors"]):
        r = ra._post_revise(wrap(price), ebc)
    return r

def is_lot(x):
    t = (x.get("title") or "").lower()
    cat = str(x.get("category_id") or x.get("primary_category") or x.get("categoryId") or "")
    return (" lot" in t or "lot of" in t or t.startswith("lot") or cat == "261329")

def new_price(p):
    target = p * (1 - CUT)
    # round to nearest .99 at or below target
    n = math.floor(target) + 0.99
    if n > target: n -= 1.0
    return max(FLOOR, round(n, 2))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text()); ebc = cfg["ebay"] if "ebay" in cfg else cfg
    tok = ebay_client.get_write_token(cfg)
    snap = json.load(open("output/listings_snapshot.json"))
    L = snap.get("listings", snap) if isinstance(snap, dict) else snap
    plan = []
    for x in L:
        if not is_lot(x): continue
        cur = x.get("price") or x.get("current_price") or x.get("start_price")
        iid = x.get("item_id") or x.get("itemId")
        if not cur or not iid: continue
        cur = float(cur); np = new_price(cur)
        if np < cur - 0.005:
            plan.append({"id": str(iid), "title": x.get("title",""), "old": cur, "new": np})
    plan.sort(key=lambda z: -z["old"])
    print(f"lots to drop: {len(plan)}  (cut {int(CUT*100)}%, floor ${FLOOR})")
    tot_old = sum(p["old"] for p in plan); tot_new = sum(p["new"] for p in plan)
    print(f"sticker sum ${tot_old:.2f} -> ${tot_new:.2f}  (avg drop ${(tot_old-tot_new)/max(1,len(plan)):.2f}/lot)\n")
    for p in plan[:12]:
        print(f'  ${p["old"]:>6.2f} -> ${p["new"]:>6.2f}   {p["title"][:60]}')
    print("  ...") if len(plan) > 12 else None
    Path("output/_lot_drop_plan.json").write_text(json.dumps(plan, indent=1))
    if not a.apply:
        print("\nDRY-RUN. Re-run with --apply to push."); return
    ok = err = 0; fails = []
    for p in plan:
        r = revise_lot(p["id"], p["new"], ebc, tok)
        if r["ok"]: ok += 1
        else:
            err += 1; fails.append((p["id"], p["title"][:40], (r["errors"][0]["msg"] if r["errors"] else "?")))
    print(f"\n=== APPLIED: {ok} dropped · {err} failed ===")
    for f in fails[:15]: print(f'  FAIL {f[0]} {f[1]} :: {f[2]}')

if __name__ == "__main__": main()
