"""apply_audit_reprice.py — apply the top-100 audit cuts.

Reads output/_reprice100_master.json, reprices every card where recommended <
current. Inventory-API (CollX) listings go through the Sell Inventory API
(bulk_update_price_quantity with Best Offer PUT fallback); legacy Trading
listings fall back to Trading ReviseItem. Dry-run unless --apply.
"""
from __future__ import annotations
import argparse, json, time
from pathlib import Path
import promote, ebay_client
import sell_inventory_reprice as sir
from repricing_agent import revise_price

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    trade = promote.get_access_token(cfg); bearer = ebay_client.get_write_token(cfg)
    rows = json.loads(Path("output/_reprice100_master.json").read_text())
    cuts = [r for r in rows if float(r["rec"]) < float(r["cur"]) - 0.001]
    print(f"cuts to apply: {len(cuts)}  ({'APPLY' if a.apply else 'dry-run'})")

    inv_rows, trading, skipped = [], [], []
    for r in cuts:
        iid = str(r["item_id"]); target = round(float(r["rec"]), 2)
        sku = sir.get_sku(iid, cfg, trade); time.sleep(0.12)
        if sku:
            off = sir.get_offer(sku, bearer); time.sleep(0.12)
            if off and off["offerId"]:
                inv_rows.append({"sku": sku, "offerId": off["offerId"], "qty": off["qty"] or 1,
                                 "target": target, "item_id": iid})
            elif sku.startswith("CDP"):
                skipped.append((iid, "CDP sku, offer unresolved"))   # inventory-managed; don't Trading-revise
            else:
                trading.append((iid, target))   # non-CDP sku, no offer → legacy Trading
        else:
            trading.append((iid, target))
    print(f"inventory: {len(inv_rows)}  trading: {len(trading)}  skipped: {len(skipped)}")
    if not a.apply:
        print("dry-run — re-run with --apply"); return

    ok, fail, errs = sir.bulk_update(inv_rows, bearer)
    print(f"Sell-API: {ok} applied, {fail} failed")
    tok = tfail = 0
    for iid, target in trading:
        res = revise_price(iid, target, cfg, trade)
        if res["ok"]: tok += 1
        else: tfail += 1
    print(f"Trading: {tok} applied, {tfail} failed")
    print(f"TOTAL applied: {ok + tok} / {len(cuts)}")
    for e in errs[:8]: print("  ERR", json.dumps(e)[:160])

if __name__ == "__main__":
    main()
