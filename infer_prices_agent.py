"""Run the robust multi-source price inference over every CollX inventory row.

Reads:
  inventory.csv                       (CollX-side data + collx_market_value)
  sportscardspro_prices.json          (SCP cache, keyed by ebay item_id)
  output/inventory_plan.json          (existing single-source price_basis + scp_value)
  output/listings_snapshot.json       (live eBay listings — for ebay_active comp)

Writes:
  output/inferred_prices.json         (keyed by collx_id; recommended price +
                                       full source breakdown + outlier drops)

Run:
  python3 infer_prices_agent.py
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from datetime import datetime, timezone

import price_inference

REPO = Path(__file__).parent
INV       = REPO / "inventory.csv"
SCP_PATH  = REPO / "sportscardspro_prices.json"
PLAN_PATH = REPO / "output" / "inventory_plan.json"
SNAP_PATH = REPO / "output" / "listings_snapshot.json"
OUT_PATH  = REPO / "output" / "inferred_prices.json"

import linkage_db


def _f(v):
    try:
        return float(v) if v not in (None, "", "None") else 0.0
    except (TypeError, ValueError):
        return 0.0


def main() -> int:
    # Inventory rows keyed by collx_id
    inv = {}
    with INV.open() as f:
        for r in csv.DictReader(f):
            cid = (r.get("collx_id") or "").strip()
            if cid:
                inv[cid] = r

    # SCP cache (keyed by ebay item_id). Each value may contain psa10_price etc.
    scp_cache = json.loads(SCP_PATH.read_text()) if SCP_PATH.is_file() else {}

    # Existing per-row plan from inventory_agent (has scp_value, price_basis)
    plan_items_by_cid = {}
    if PLAN_PATH.is_file():
        plan = json.loads(PLAN_PATH.read_text())
        for it in plan.get("items", []):
            raw = it.get("raw") or {}
            cid = (raw.get("collx_id") or "").strip()
            if cid:
                plan_items_by_cid[cid] = it

    # Linkage DB tells us which collx_ids are live (have an ebay_item_id)
    links_by_cid = {l["collx_id"]: l for l in linkage_db.all_links() if l.get("collx_id")}

    rows_out = {}
    counters = {"with_two_plus": 0, "with_collx_only": 0, "with_none": 0,
                "dropped_outliers": 0, "total": 0}

    for cid, row in inv.items():
        counters["total"] += 1
        collx_mv = _f(row.get("collx_market_value"))

        # SCP lookup: linkage DB tells us the ebay_item_id if this card is live;
        # otherwise SCP can't be matched (it's keyed by item_id, not card).
        scp_prices = None
        link = links_by_cid.get(cid) or {}
        ebay_item_id = link.get("ebay_item_id")
        if ebay_item_id and ebay_item_id in scp_cache:
            scp_prices = scp_cache[ebay_item_id]

        # The existing plan_item has a single-source scp_value figure when its
        # matcher hit. Pull it as a fallback so unlisted cards still benefit.
        plan_it = plan_items_by_cid.get(cid) or {}
        plan_scp_value = _f(plan_it.get("scp_value"))
        plan_scp_basis = plan_it.get("scp_basis")
        if plan_scp_value > 0 and not scp_prices:
            # Wrap as a single-key dict so build_sources_for_row sees it.
            scp_prices = {plan_scp_basis or "ungraded_price": plan_scp_value}

        sources = price_inference.build_sources_for_row(
            collx_market=collx_mv,
            scp_prices=scp_prices,
            # eBay market + sold history would require gather_pricing_sources
            # which calls eBay APIs — out of scope for this offline pass.
            # Left as None; integrate later when running inside the main
            # promote.py refresh.
        )

        result = price_inference.infer_price(sources)
        if result["recommended"] is None:
            counters["with_none"] += 1
        elif len(result["kept"]) >= 2:
            counters["with_two_plus"] += 1
        else:
            counters["with_collx_only"] += 1
        counters["dropped_outliers"] += len(result["dropped"])

        rows_out[cid] = {
            "title":       row.get("name", ""),
            "player":      row.get("player", ""),
            "collx_id":    cid,
            "status":      (links_by_cid.get(cid) or {}).get("status", "unlisted"),
            "ebay_item_id": ebay_item_id or None,
            "recommended": result["recommended"],
            "center":      result["center"],
            "confidence":  result["confidence"],
            "basis":       result["basis"],
            "kept":        result["kept"],
            "dropped":     result["dropped"],
            "per_source":  result["per_source"],
            "range_low":   result["range_low"],
            "range_high":  result["range_high"],
        }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "counters":     counters,
        "list_discount": price_inference.LIST_DISCOUNT,
        "outlier_threshold_mad": price_inference.OUTLIER_MAD_THRESHOLD,
        "prices":       rows_out,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2))

    print(f"Wrote {OUT_PATH}")
    print(f"  Total cards scored:        {counters['total']}")
    print(f"  With 2+ sources blended:   {counters['with_two_plus']}")
    print(f"  CollX only (single src):   {counters['with_collx_only']}")
    print(f"  No usable comps:           {counters['with_none']}")
    print(f"  Outliers dropped (total):  {counters['dropped_outliers']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
