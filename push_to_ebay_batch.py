"""
[DEPRECATED — see feedback_no_batch_push in memory]

This batch pusher was retired on 2026-05-29 after the May 27 batch created
ghost/duplicate listings (Cam Ward Pink Refractor, Micah Parsons Pink
Refractor) that Jason had to manually clean up. The batch agent did not
cross-reference output/listings_snapshot.json before pushing, so cards
already live on eBay under hand-edited titles got pushed a second time.

Jason's standing rule: every eBay push must be a single-card decision he
explicitly approves card-by-card via push_to_ebay.py.

This file is preserved for archaeology only. The main() refuses to run.

If you genuinely need batch behavior in the future, copy the candidate-
selection logic into a NEW script that ALSO runs the duplicate-detection
gate (_detect_duplicates in push_to_ebay.py).

----- original docstring below for reference -----

push_to_ebay_batch.py — push many CollX-only (unlisted) cards to eBay in a
single command. Replaces the manual per-card `push_to_ebay.py --row N --apply`
loop with a safety-filtered bulk pass.

Architecture:
  - Pool of candidates: linkage_db.list_unlisted_collx_ids()
  - Joined to inventory.csv for raw fields (title, image, condition)
  - Joined to output/inventory_plan.json for the enriched suggested price and
    price_basis from inventory_agent.py
  - For the AddItem path, we IMPORT push_to_ebay's helpers (XML builders, OAuth,
    Trading headers) so the bulk path is byte-identical to the single-card path

Safety filters skip candidates that match any of:
  - price_basis == 'default'         (unknown CollX market — too risky to auto-price)
  - collx_market_value < floor       (sub-economic — push to the lot generator instead)
  - missing image_url                (eBay AddItem requires at least one photo)
  - linkage DB status != 'unlisted'  (race-condition guard, status changed under us)

CLI:
  python3 push_to_ebay_batch.py                       # dry-run, top 20 candidates
  python3 push_to_ebay_batch.py --max 50              # dry-run, top 50
  python3 push_to_ebay_batch.py --floor 5             # raise the price floor
  python3 push_to_ebay_batch.py --apply               # actually push (asks one confirm)

Confirmation prompt is anti-fat-finger: you must type "apply N" with the
actual count, not just "yes" — prevents accidentally bulk-listing the wrong
batch size.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import linkage_db
import push_to_ebay as p1  # reuse single-card helpers — DO NOT copy-paste

REPO_ROOT  = Path(__file__).parent
PLAN_PATH  = REPO_ROOT / "output" / "inventory_plan.json"
INV_PATH   = REPO_ROOT / "inventory.csv"
CONFIG     = REPO_ROOT / "configuration.json"
BATCH_LOG  = REPO_ROOT / "output" / "push_to_ebay_batch_log.json"

DEFAULT_MAX   = 20
HARD_CEILING  = 50    # runaway guard — refuse --max > 50
DEFAULT_FLOOR = 2.50  # sub-$2.50 cards belong in the lot generator
DEFAULT_DURATION = "GTC"


def load_inventory_by_collx_id() -> dict[str, dict]:
    """inventory.csv keyed on collx_id for fast joins."""
    out: dict[str, dict] = {}
    with INV_PATH.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            cid = (row.get("collx_id") or "").strip()
            if cid:
                out[cid] = row
    return out


def collect_candidates(floor: float) -> tuple[list[dict], dict[str, int]]:
    """Return (passing_candidates, skip_counts).

    Each passing entry is a dict with `collx_id`, `plan_item`, `inv_row`,
    `price`, `price_basis`, `collx_market`, `title`, `image_url`."""
    if not PLAN_PATH.exists():
        raise SystemExit(f"No plan at {PLAN_PATH}. Run inventory_agent.py first.")
    plan = json.loads(PLAN_PATH.read_text())
    items_by_id = {(it["raw"].get("collx_id") or "").strip(): it
                   for it in plan.get("items", [])}
    inv_by_id = load_inventory_by_collx_id()

    unlisted_ids = linkage_db.list_unlisted_collx_ids()

    skipped = {
        "no_plan_entry":          0,
        "default_basis":          0,
        "below_floor":            0,
        "no_image":               0,
        "not_unlisted_anymore":   0,
        "no_inventory_row":       0,
    }
    passing: list[dict] = []

    for cid in unlisted_ids:
        item = items_by_id.get(cid)
        if not item:
            skipped["no_plan_entry"] += 1
            continue
        inv_row = inv_by_id.get(cid)
        if not inv_row:
            skipped["no_inventory_row"] += 1
            continue
        if (item.get("price_basis") or "").strip() == "default":
            skipped["default_basis"] += 1
            continue
        try:
            collx_market = float(item.get("collx_market") or 0)
        except (TypeError, ValueError):
            collx_market = 0.0
        if collx_market < floor:
            skipped["below_floor"] += 1
            continue
        image_url = item.get("image_url") or item["raw"].get("image_url") or ""
        if not image_url:
            skipped["no_image"] += 1
            continue
        # Race-condition guard: re-read linkage DB right now. If the row has
        # already flipped to live/sold/ended/removed_from_collx between the
        # list query above and now, skip it.
        link = linkage_db.get_link(cid)
        if link and (link.get("status") or "").strip() not in ("", "unlisted"):
            skipped["not_unlisted_anymore"] += 1
            continue

        try:
            price = float(item.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        if price <= 0:
            # Suggested price missing or zero — treat as not safe to bulk-push
            skipped["default_basis"] += 1
            continue

        passing.append({
            "collx_id":     cid,
            "plan_item":    item,
            "inv_row":      inv_row,
            "price":        price,
            "price_basis":  item.get("price_basis") or "",
            "collx_market": collx_market,
            "title":        item.get("title", ""),
            "image_url":    image_url,
        })

    # Highest-value first — better candidates list, easier visual review
    passing.sort(key=lambda c: c["price"], reverse=True)
    return passing, skipped


def print_skip_summary(total_unlisted: int, skipped: dict[str, int], passing_n: int) -> None:
    print()
    print("=" * 72)
    print("  CANDIDATE FILTER")
    print("=" * 72)
    print(f"  Unlisted in linkage DB:           {total_unlisted}")
    print(f"  Skipped, no plan entry:           {skipped['no_plan_entry']}")
    print(f"  Skipped, no inventory.csv row:    {skipped['no_inventory_row']}")
    print(f"  Skipped, price_basis = 'default': {skipped['default_basis']}")
    print(f"  Skipped, below price floor:       {skipped['below_floor']}")
    print(f"  Skipped, missing image:           {skipped['no_image']}")
    print(f"  Skipped, status changed under us: {skipped['not_unlisted_anymore']}")
    print(f"  Passing all safety filters:       {passing_n}")
    print("=" * 72)


def print_batch_plan(batch: list[dict], floor: float, max_n: int) -> None:
    total_value = sum(c["price"] for c in batch)
    print()
    print("=" * 72)
    print(f"  BATCH PLAN  ({len(batch)} cards, max {max_n}, floor ${floor:.2f})")
    print("=" * 72)
    print(f"  Total revenue if everything sells:  ${total_value:,.2f}")
    print(f"  Average price:                      ${(total_value / len(batch)) if batch else 0:.2f}")
    print()
    print("  Top by price:")
    for c in batch[:5]:
        title = c["title"][:60]
        print(f"    ${c['price']:>7.2f}  {c['collx_id']}  {title}")
    if len(batch) > 5:
        print(f"    ... and {len(batch) - 5} more")
    print("=" * 72)


def confirm_apply(count: int) -> bool:
    print()
    print(f"  This will create {count} LIVE eBay listings immediately.")
    print(f"  To proceed, type exactly:  apply {count}")
    print( "  Anything else cancels.")
    try:
        line = input("> ").strip().lower()
    except EOFError:
        return False
    return line == f"apply {count}"


def resolve_condition(item: dict) -> str:
    """Resolve the human-readable condition label the way push_to_ebay.py does."""
    cond = (item["raw"].get("condition") or "Near Mint").strip()
    if cond.lower() not in p1.CONDITION_ID:
        # Fall back to a safe default that matches CONDITION_ID
        return "Near Mint"
    return cond


def append_batch_log(entry: dict) -> None:
    BATCH_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if BATCH_LOG.exists():
        try:
            log = json.loads(BATCH_LOG.read_text())
        except json.JSONDecodeError:
            log = []
    log.append(entry)
    BATCH_LOG.write_text(json.dumps(log, indent=2))


def push_one(cand: dict, cfg: dict, token: str, duration: str,
             free_shipping: bool) -> dict:
    """Push a single candidate. Returns a per-card result dict."""
    item = cand["plan_item"]
    price = cand["price"]
    condition = resolve_condition(item)
    result = {
        "collx_id":  cand["collx_id"],
        "title":     cand["title"],
        "price":     price,
        "condition": condition,
        "ack":       None,
        "item_id":   None,
        "errors":    [],
        "status":    "exception",
    }
    try:
        body = p1.build_add_xml(item, token, price, condition, duration, free_shipping)
        r = requests.post(
            p1.TRADING_URL,
            headers=p1.trading_headers("AddItem", cfg, token),
            data=body.encode("utf-8"),
            timeout=60,
        )
        ack = p1.find_tag(r.text, "Ack") or "?"
        item_id = p1.find_tag(r.text, "ItemID")
        errors = p1.find_all(r.text, "Errors")
        result["ack"] = ack
        result["item_id"] = item_id
        result["errors"] = [
            {"code": p1.find_tag(e, "ErrorCode"),
             "message": p1.find_tag(e, "LongMessage") or p1.find_tag(e, "ShortMessage")}
            for e in errors
        ]
        if item_id and ack in ("Success", "Warning"):
            result["status"] = "success"
            # Stamp the linkage DB — durable CollX <-> eBay mapping
            try:
                linkage_db.link_listing(
                    collx_id=cand["collx_id"],
                    ebay_item_id=item_id,
                    listed_price=price,
                    title=cand["title"],
                    sku=cand["collx_id"],
                )
            except Exception as exc:
                # Listing is live but linkage write failed — surface in log
                result["status"] = "success_linkage_failed"
                result["linkage_error"] = str(exc)
        else:
            result["status"] = "ack_failure"
    except Exception as exc:
        result["status"] = "exception"
        result["errors"].append({"code": "PY_EXCEPTION", "message": str(exc)})
    return result


def main() -> int:
    print("=" * 72)
    print("push_to_ebay_batch.py is DEPRECATED as of 2026-05-29.")
    print()
    print("Why: the May 27 batch created duplicate/ghost listings (Cam Ward Pink")
    print("Refractor, Micah Parsons Pink Refractor) that had to be manually ended.")
    print("The batch agent never cross-referenced live eBay listings before pushing.")
    print()
    print("Use the single-card path instead. It now has duplicate detection built in:")
    print("    python3 push_to_ebay.py --collx-id <ID> --price <PRICE> --apply")
    print()
    print("If you genuinely need batch behavior again, the dedupe gate is at")
    print("_detect_duplicates() in push_to_ebay.py. Copy that into a fresh script.")
    print("=" * 72)
    return 1

    # ----- DEPRECATED main() preserved for reference, never reached -----
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max",   type=int,   default=DEFAULT_MAX,
                    help=f"Cap batch size (default {DEFAULT_MAX}, hard ceiling {HARD_CEILING}).")
    ap.add_argument("--floor", type=float, default=DEFAULT_FLOOR,
                    help=f"Override price floor (default ${DEFAULT_FLOOR:.2f}).")
    ap.add_argument("--duration", default=DEFAULT_DURATION,
                    choices=["GTC", "Days_7", "Days_10", "Days_30"],
                    help="ListingDuration. Default GTC.")
    ap.add_argument("--paid-shipping", dest="paid_shipping", action="store_true",
                    default=True,
                    help="Pass through to push_to_ebay (default ON — Calculated / eBay Standard Envelope).")
    ap.add_argument("--no-paid-shipping", dest="paid_shipping", action="store_false",
                    help="Disable paid shipping flag.")
    ap.add_argument("--dry-run", action="store_true", default=True,
                    help="Dry-run (default). Print plan; do not push.")
    ap.add_argument("--apply",   action="store_true",
                    help="Actually push. Without this, dry-run only.")
    args = ap.parse_args()

    if args.max > HARD_CEILING:
        print(f"--max {args.max} exceeds hard ceiling {HARD_CEILING}. Refusing.")
        return 2
    if args.max <= 0:
        print("--max must be positive.")
        return 2
    if args.floor < 0:
        print("--floor must be non-negative.")
        return 2

    total_unlisted = len(linkage_db.list_unlisted_collx_ids())
    passing, skipped = collect_candidates(args.floor)
    print_skip_summary(total_unlisted, skipped, len(passing))

    batch = passing[: args.max]
    if not batch:
        print()
        print("No candidates passed all safety filters. Nothing to do.")
        return 0

    print_batch_plan(batch, args.floor, args.max)

    free_shipping = not args.paid_shipping

    if not args.apply:
        print()
        print("DRY RUN — nothing sent to eBay.")
        print("Re-run with --apply to push live. You will be asked to confirm once.")
        return 0

    if not confirm_apply(len(batch)):
        print("Cancelled.")
        return 1

    if not CONFIG.exists():
        raise SystemExit(f"Missing {CONFIG} — needed for OAuth credentials.")
    cfg = json.loads(CONFIG.read_text())

    print()
    print("Fetching write-scoped OAuth token...")
    token = p1.get_write_token(cfg)

    print(f"Pushing {len(batch)} listings...")
    print("-" * 72)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    results: list[dict] = []
    success_n = ack_fail_n = exception_n = 0
    revenue_at_risk = 0.0
    for i, cand in enumerate(batch, 1):
        title_short = cand["title"][:48]
        print(f"  [{i:>3}/{len(batch)}] ${cand['price']:>6.2f}  {cand['collx_id']}  {title_short}")
        res = push_one(cand, cfg, token, args.duration, free_shipping)
        results.append(res)
        if res["status"].startswith("success"):
            success_n += 1
            revenue_at_risk += res["price"]
            tag = "OK"
            print(f"           -> {tag}  ItemID {res['item_id']}  Ack={res['ack']}")
        elif res["status"] == "ack_failure":
            ack_fail_n += 1
            err_codes = ",".join(filter(None, [e.get("code") for e in res["errors"]]))
            print(f"           -> ACK FAIL  Ack={res['ack']}  errors=[{err_codes}]")
        else:
            exception_n += 1
            err = res["errors"][0]["message"] if res["errors"] else "unknown"
            print(f"           -> EXCEPTION  {err[:120]}")

    finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
    append_batch_log({
        "started_at":  started,
        "finished_at": finished,
        "floor":       args.floor,
        "max":         args.max,
        "duration":    args.duration,
        "free_shipping": free_shipping,
        "total_candidates": len(passing),
        "skipped":     skipped,
        "results":     results,
    })

    print("-" * 72)
    print()
    print("=" * 72)
    print("  BATCH SUMMARY")
    print("=" * 72)
    print(f"  Pushed (success):    {success_n}")
    print(f"  Ack failures:        {ack_fail_n}")
    print(f"  Exceptions:          {exception_n}")
    print(f"  Skipped (filtered):  {sum(skipped.values())}")
    print(f"  Revenue at risk:     ${revenue_at_risk:,.2f}  (if every pushed listing sells)")
    print(f"  Log appended to:     {BATCH_LOG}")
    print("=" * 72)

    return 0 if exception_n == 0 and ack_fail_n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
