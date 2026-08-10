"""relist_backlog.py — revive the dead-stock backlog in output/pulled_repository.json
at a markdown, since these cards already proved they didn't move at the original
price. _pull_over_60.py blacklists every card it pulls in output/do_not_relist.json
specifically so nothing here gets auto-resurrected verbatim — this script is the
deliberate, human-approved override: same cards, cut price, and it removes them
from do_not_relist.json + pulled_repository.json once relisted so they re-enter
normal tracking (repricing, photo audit, etc.) as live listings again.

Usage:
    python3 relist_backlog.py                # dry run (default)
    python3 relist_backlog.py --apply         # actually call RelistFixedPriceItem
    python3 relist_backlog.py --cut 0.18      # markdown fraction (default 0.18)
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import relist_agent as ra
import promote

REPO_PATH    = Path("output/pulled_repository.json")
DNR_PATH     = Path("output/do_not_relist.json")
HISTORY_PATH = Path("output/relist_backlog_history.json")

MIN_PRICE = 0.99
def load_backlog() -> list[dict]:
    d = json.loads(REPO_PATH.read_text())
    return d.get("items", d) if isinstance(d, dict) else d


def is_giants(title: str) -> bool:
    """Standing hold is on the NY Giants (NFL) only -- must not also catch
    SF Giants (MLB) cards, which share the bare word "giants"."""
    t = title.lower()
    if "san francisco giants" in t or "sf giants" in t:
        return False
    return "giants" in t


def markdown_price(price: float, cut: float) -> float:
    return max(round(price * (1 - cut), 2), MIN_PRICE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="Actually call RelistFixedPriceItem")
    ap.add_argument("--cut", type=float, default=0.18, help="Markdown fraction (default 0.18)")
    ap.add_argument("--limit", type=int, default=None, help="Cap number of items processed (testing)")
    args = ap.parse_args()

    backlog = load_backlog()
    # Only skip items that actually succeeded -- a failed attempt (e.g. the
    # eBay-side payment-terms gate) must stay eligible for retry once that's
    # resolved, otherwise every failure permanently self-excludes and a
    # clean re-run reports "to process: 0" forever.
    already_done = {r["item_id"] for r in json.loads(HISTORY_PATH.read_text()) if r.get("ok")} if HISTORY_PATH.exists() else set()

    skipped_giants = [i for i in backlog if is_giants(i["title"])]
    skipped_done = [i for i in backlog if i["item_id"] in already_done]
    todo = [i for i in backlog
            if not is_giants(i["title"]) and i["item_id"] not in already_done]
    if args.limit:
        todo = todo[:args.limit]

    print(f"Backlog: {len(backlog)} total")
    print(f"  excluded (Giants hold): {len(skipped_giants)}")
    print(f"  excluded (already relisted this pass): {len(skipped_done)}")
    print(f"  to process: {len(todo)}  (markdown {args.cut:.0%}, mode: {'APPLY' if args.apply else 'DRY RUN'})")
    print()

    sample = todo[:5]
    for i in sample:
        print(f"  sample: {i['item_id']}  ${i['price']:.2f} -> ${markdown_price(i['price'], args.cut):.2f}  {i['title'][:55]}")
    print()

    if not args.apply:
        total_before = sum(i["price"] for i in todo)
        total_after = sum(markdown_price(i["price"], args.cut) for i in todo)
        print(f"[dry-run] {len(todo)} would be relisted. "
              f"Aggregate list value ${total_before:,.2f} -> ${total_after:,.2f}")
        print("Re-run with --apply to actually relist.")
        return 0

    cfg = json.loads(Path("configuration.json").read_text())
    token = promote.get_access_token(cfg)

    dnr = set(str(x) for x in json.loads(DNR_PATH.read_text())) if DNR_PATH.exists() else set()
    history = json.loads(HISTORY_PATH.read_text()) if HISTORY_PATH.exists() else []
    still_in_repo = list(backlog)

    ok_count = fail_count = 0
    consecutive_quota_hits = 0
    stopped_early = False
    for n, item in enumerate(todo, 1):
        iid = item["item_id"]
        new_price = markdown_price(item["price"], args.cut)
        result = ra.relist_as_fixed_price(token, iid, cfg, new_price=new_price, dry_run=False)
        error = result.get("error", "")

        # [932] "Auth token is hard expired" -- a long batch (1000+ items,
        # 30-40+ min at this pacing) can outlast the token's ~2hr life.
        # Refresh once and immediately retry this same item rather than
        # letting every remaining item fail for the rest of the run.
        if "[932]" in error:
            token = promote.get_access_token(cfg)
            result = ra.relist_as_fixed_price(token, iid, cfg, new_price=new_price, dry_run=False)
            error = result.get("error", "")

        # [518] "exceeded usage limit on this call" is a real per-day/hour
        # Trading API quota, not a per-item problem -- once hit, every
        # subsequent call fails identically until the window resets, so
        # burning through the rest of `todo` just pollutes history with
        # false failures. Stop after a few in a row and leave the rest
        # untouched in the backlog for a later run.
        if "[518]" in error:
            consecutive_quota_hits += 1
            if consecutive_quota_hits >= 3:
                print(f"  Hit eBay's call-usage quota {consecutive_quota_hits}x in a row -- "
                      f"stopping at {n}/{len(todo)}. Remaining items left untouched in the backlog.")
                stopped_early = True
                break
        else:
            consecutive_quota_hits = 0

        rec = {
            "item_id": iid,
            "title": item["title"],
            "old_price": item["price"],
            "new_price": new_price,
            "new_item_id": result.get("new_item_id", ""),
            "ok": result.get("ok", False),
            "ack": result.get("ack", ""),
            "error": error,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        history.append(rec)
        if rec["ok"]:
            ok_count += 1
            dnr.discard(iid)
            still_in_repo = [i for i in still_in_repo if i["item_id"] != iid]
        else:
            fail_count += 1
        if n % 25 == 0 or n == len(todo):
            print(f"  {n}/{len(todo)}  ok={ok_count} fail={fail_count}")
            HISTORY_PATH.write_text(json.dumps(history, indent=1))
            DNR_PATH.write_text(json.dumps(sorted(dnr), indent=1))
            REPO_PATH.write_text(json.dumps(still_in_repo, indent=1))
        time.sleep(0.3)

    HISTORY_PATH.write_text(json.dumps(history, indent=1))
    DNR_PATH.write_text(json.dumps(sorted(dnr), indent=1))
    REPO_PATH.write_text(json.dumps(still_in_repo, indent=1))

    processed = ok_count + fail_count
    status = "STOPPED EARLY (quota)" if stopped_early else "DONE"
    print(f"\n{status}: {ok_count} relisted, {fail_count} failed, "
          f"{len(still_in_repo)} remain in backlog")
    fails = [r for r in history[-processed:] if not r["ok"]] if processed else []
    if fails:
        from collections import Counter
        err_counts = Counter(r["error"][:60] for r in fails)
        print("Top failure reasons:")
        for err, n in err_counts.most_common(5):
            print(f"  {n:4d}  {err}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
