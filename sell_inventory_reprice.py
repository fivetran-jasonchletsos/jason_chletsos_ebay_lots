"""
sell_inventory_reprice.py — reprice CollX/Inventory-API-managed listings.

The Trading API ReviseItem call is rejected (error 21919474) for listings
created via the eBay Sell Inventory API (CollX imports, SKU pattern CDP-*).
This tool reprices them the supported way:

    Trading GetItem(item_id) -> SKU
    GET  /sell/inventory/v1/offer?sku=SKU   -> offerId (+ listingId, current price)
    POST /sell/inventory/v1/bulk_update_price_quantity  (batches of 25)

Source of targets: output/repricing_plan.json (decision == "apply").

Usage:
    python3 sell_inventory_reprice.py                 # dry run, all targets
    python3 sell_inventory_reprice.py --limit 2       # dry run, first 2 (smoke test)
    python3 sell_inventory_reprice.py --apply --limit 2
    python3 sell_inventory_reprice.py --apply --chunk 1/6   # slice 1 of 6 (for fan-out)
    python3 sell_inventory_reprice.py --apply              # everything
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

import ebay_client
import promote

PLAN_PATH   = Path("output/repricing_plan.json")
INV_BASE    = "https://api.ebay.com/sell/inventory/v1"
MARKETPLACE = "EBAY_US"
BULK_MAX    = 25          # bulk_update_price_quantity max requests per call
SLEEP       = 0.15        # gentle throttle between resolution GETs


def load_targets() -> list[dict]:
    p = json.loads(PLAN_PATH.read_text())
    items = p if isinstance(p, list) else next(
        (v for v in p.values() if isinstance(v, list)), [])
    out = []
    for it in items:
        if it.get("decision") != "apply":
            continue
        tp, cp = it.get("target_price"), it.get("current_price")
        if tp is None or tp == cp:
            continue
        out.append({"item_id": str(it["item_id"]),
                    "target_price": round(float(tp), 2),
                    "current_price": cp,
                    "title": it.get("title", "")})
    return out


def apply_chunk(targets: list[dict], spec: str) -> list[dict]:
    """spec like '2/6' -> keep every item where idx % 6 == 1."""
    i, n = (int(x) for x in spec.split("/"))
    return [t for k, t in enumerate(targets) if k % n == (i - 1)]


def get_sku(item_id: str, cfg: dict, trade_token: str) -> str | None:
    hdr = ebay_client.trading_headers("GetItem", cfg, trade_token)
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f'<RequesterCredentials><eBayAuthToken>{trade_token}</eBayAuthToken></RequesterCredentials>'
           f'<ItemID>{item_id}</ItemID></GetItemRequest>')
    r = requests.post(ebay_client.TRADING_URL, headers=hdr, data=xml.encode(), timeout=30)
    import re
    m = re.search(r"<SKU>(.*?)</SKU>", r.text)
    return m.group(1) if m else None


def get_offer(sku: str, bearer: str) -> dict | None:
    h = {"Authorization": f"Bearer {bearer}", "Accept": "application/json"}
    r = None
    for attempt in range(4):                       # retry transient failures / rate limits
        r = requests.get(f"{INV_BASE}/offer", headers=h,
                         params={"sku": sku, "marketplace_id": MARKETPLACE}, timeout=30)
        if r.ok:
            break
        time.sleep(0.6 * (attempt + 1))
    if not r or not r.ok:
        return None
    offers = r.json().get("offers", [])
    pub = next((o for o in offers if o.get("status") == "PUBLISHED"), None) or (offers[0] if offers else None)
    if not pub:
        return None
    price = (pub.get("pricingSummary") or {}).get("price", {}).get("value")
    return {"offerId": pub.get("offerId"),
            "listingId": (pub.get("listing") or {}).get("listingId"),
            "qty": pub.get("availableQuantity", 1) or 1,
            "current": price}


def _offer_put_reprice(row: dict, bearer: str) -> tuple[bool, dict]:
    """Fallback for Best Offer conflicts (err 25002): GET the full offer, set the
    new price AND pull the Best Offer auto-accept/decline below it, then PUT."""
    h = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json",
         "Accept": "application/json", "Content-Language": "en-US"}
    oid = row["offerId"]
    g = requests.get(f"{INV_BASE}/offer/{oid}", headers=h, timeout=30)
    if not g.ok:
        return False, {"sku": row["sku"], "stage": "get_offer", "body": g.text[:200]}
    offer = g.json()
    tp = row["target"]
    offer.setdefault("pricingSummary", {})["price"] = {"value": f"{tp:.2f}", "currency": "USD"}
    bot = (offer.get("listingPolicies") or {}).get("bestOfferTerms")
    if bot and bot.get("bestOfferEnabled"):
        if "autoAcceptPrice" in bot:
            bot["autoAcceptPrice"] = {"value": f"{round(tp*0.95,2):.2f}", "currency": "USD"}
        if "autoDeclinePrice" in bot:
            bot["autoDeclinePrice"] = {"value": f"{round(tp*0.60,2):.2f}", "currency": "USD"}
    p = requests.put(f"{INV_BASE}/offer/{oid}", headers=h, data=json.dumps(offer), timeout=30)
    if p.status_code in (200, 204):
        return True, {}
    return False, {"sku": row["sku"], "stage": "put_offer", "http": p.status_code, "body": p.text[:200]}


def bulk_update(rows: list[dict], bearer: str) -> tuple[int, int, list]:
    """rows: [{sku, offerId, qty, target}]. Returns (ok, fail, errors).
    On Best Offer conflict (err 25002) retries via per-offer PUT fallback."""
    ok = fail = 0
    errors = []
    h = {"Authorization": f"Bearer {bearer}", "Content-Type": "application/json",
         "Accept": "application/json", "Content-Language": "en-US"}
    for start in range(0, len(rows), BULK_MAX):
        batch = rows[start:start + BULK_MAX]
        body = {"requests": [{
            "sku": r["sku"],
            "offers": [{"offerId": r["offerId"],
                        "availableQuantity": r["qty"],
                        "price": {"value": f'{r["target"]:.2f}', "currency": "USD"}}],
        } for r in batch]}
        resp = requests.post(f"{INV_BASE}/bulk_update_price_quantity",
                             headers=h, data=json.dumps(body), timeout=60)
        try:
            responses = resp.json().get("responses", [])
        except ValueError:
            responses = []
        # eBay returns HTTP 400 when all items fail, but still includes a
        # per-item responses[] we can act on (e.g. trigger the Best Offer fallback).
        if not responses:
            fail += len(batch)
            errors.append({"http": resp.status_code, "body": resp.text[:300]})
            continue
        for r, item in zip(batch, responses):
            sc = item.get("statusCode")
            if sc == 200:
                ok += 1
                continue
            errs = item.get("errors") or item.get("warnings") or []
            # 25002 / 25016 = Best Offer auto-accept/decline conflicts with the new price.
            if any(e.get("errorId") in (25002, 25016) for e in errs):
                fixed, ferr = _offer_put_reprice(r, bearer)
                if fixed:
                    ok += 1
                    continue
                errors.append({"sku": r["sku"], "fallback_failed": ferr})
            else:
                errors.append({"sku": r["sku"], "status": sc, "errors": errs})
            fail += 1
    return ok, fail, errors


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--chunk", type=str, default="")
    ap.add_argument("--items", type=str, default="", help="comma-separated item_ids to target")
    args = ap.parse_args()

    cfg = json.loads(Path("configuration.json").read_text())
    trade_token = promote.get_access_token(cfg)
    bearer = ebay_client.get_write_token(cfg)

    targets = load_targets()
    if args.items:
        want = {x.strip() for x in args.items.split(",") if x.strip()}
        targets = [t for t in targets if t["item_id"] in want]
    if args.chunk:
        targets = apply_chunk(targets, args.chunk)
    if args.limit:
        targets = targets[:args.limit]

    print(f"Targets to reprice: {len(targets)}  "
          f"({'APPLY' if args.apply else 'dry-run'}"
          f"{' chunk ' + args.chunk if args.chunk else ''})")

    rows, skipped = [], []
    for t in targets:
        sku = get_sku(t["item_id"], cfg, trade_token)
        time.sleep(SLEEP)
        if not sku:
            skipped.append((t["item_id"], "no SKU (Trading listing)"))
            continue
        off = get_offer(sku, bearer)
        time.sleep(SLEEP)
        if not off or not off["offerId"]:
            skipped.append((t["item_id"], f"no offer for {sku}"))
            continue
        try:
            if off["current"] is not None and abs(float(off["current"]) - t["target_price"]) < 0.005:
                skipped.append((t["item_id"], f"already at ${t['target_price']:.2f}"))
                continue
        except (TypeError, ValueError):
            pass
        rows.append({"sku": sku, "offerId": off["offerId"], "qty": off["qty"],
                     "target": t["target_price"], "current": off["current"],
                     "item_id": t["item_id"], "title": t["title"]})
        print(f"  {t['item_id']}  {sku}  ${off['current']} -> ${t['target_price']:.2f}  {t['title'][:42]}")

    print(f"\nResolved {len(rows)} repriceable · skipped {len(skipped)}")
    for iid, why in skipped[:10]:
        print(f"  skip {iid}: {why}")

    if not args.apply:
        print("\nDry run only. Re-run with --apply to push prices.")
        return

    ok, fail, errors = bulk_update(rows, bearer)
    print(f"\nResult: {ok} applied · {fail} failed")
    for e in errors[:10]:
        print("  ERR", json.dumps(e)[:200])


if __name__ == "__main__":
    main()
