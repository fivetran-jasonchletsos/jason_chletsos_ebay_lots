"""Cascade refresh: when something upstream changes (CollX import, eBay push,
sold reconcile), re-run only the agents whose outputs depend on that input.

The problem this solves: after every CollX import, the dashboard pages and
smart-price caches stay stale until someone manually re-runs the right four
or five scripts in the right order. We waste analysis time fixing data
freshness instead of looking at numbers.

This script wires the dependencies. Call it explicitly OR have collx_ingest.py
call it automatically at the end of an import.

Usage:
  python3 refresh_pipeline.py                    # do everything that's likely stale
  python3 refresh_pipeline.py --after-ingest     # CollX import just ran
  python3 refresh_pipeline.py --after-push       # push_to_ebay just landed a listing
  python3 refresh_pipeline.py --after-sold       # a listing just sold
  python3 refresh_pipeline.py --quiet            # suppress per-step banner output

The cascades are conservative: they re-run anything whose output references
the changed input, and skip anything API-dependent that would slow the loop.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).parent

# Map of trigger -> ordered list of scripts to run.
# Each entry: (script, args, description, allow_failure)
CASCADES = {
    "after-ingest": [
        ("inventory_agent.py",     [], "inventory plan + multi-source pricing",  False),
        ("infer_prices_agent.py",  [], "smart-price inference (robust blend)",   False),
        ("build_collx_vs_ebay.py", [], "CollX vs eBay dashboard",                False),
    ],
    "after-push": [
        # push_to_ebay already stamps linkage_db and appends to listings_snapshot
        # (see the small append helper added there). All we need is to refresh
        # the comparison view so the new listing shows up in "On Both" not
        # "CollX-only".
        ("build_collx_vs_ebay.py", [], "CollX vs eBay dashboard",                False),
    ],
    "after-sold": [
        # linkage_db already marked sold; surface it on the dashboards.
        ("inventory_agent.py",     [], "inventory plan (drops sold rows)",       False),
        ("build_collx_vs_ebay.py", [], "CollX vs eBay dashboard",                False),
        ("daily_digest_agent.py",  [], "daily digest (sale visible)",            True),
    ],
    "all": [
        ("inventory_agent.py",     [], "inventory plan + multi-source pricing",  False),
        ("infer_prices_agent.py",  [], "smart-price inference (robust blend)",   False),
        ("build_collx_vs_ebay.py", [], "CollX vs eBay dashboard",                False),
        ("daily_digest_agent.py",  [], "daily digest",                           True),
    ],
}


def run_step(script: str, args: list[str], desc: str, quiet: bool, allow_failure: bool) -> tuple[bool, float]:
    label = f"  {script:32s}  {desc}"
    if not quiet:
        print(label, flush=True)
    t0 = time.time()
    try:
        r = subprocess.run(
            ["python3", script, *args],
            cwd=str(REPO),
            capture_output=True, text=True, timeout=600,
        )
        dt = time.time() - t0
    except subprocess.TimeoutExpired:
        if not quiet:
            print(f"    TIMEOUT after 600s")
        return False, time.time() - t0
    if r.returncode != 0:
        if not quiet:
            print(f"    FAILED ({dt:.1f}s)")
            print(f"    stderr: {r.stderr[:300]}")
        return False, dt
    if not quiet:
        # Show the last interesting line of output so the user sees the result.
        tail = (r.stdout or "").strip().splitlines()
        if tail:
            print(f"    ok  ({dt:.1f}s) — {tail[-1][:120]}")
        else:
            print(f"    ok  ({dt:.1f}s)")
    return True, dt


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--after-ingest", action="store_true",
                   help="CollX CSV import just ran (default if no trigger given).")
    g.add_argument("--after-push",   action="store_true",
                   help="push_to_ebay.py just listed a card.")
    g.add_argument("--after-sold",   action="store_true",
                   help="A listing just sold; reconcile dashboards.")
    g.add_argument("--all",          action="store_true",
                   help="Run every downstream refresh.")
    ap.add_argument("--quiet",       action="store_true", help="Suppress per-step output.")
    args = ap.parse_args()

    if args.after_push:    trigger = "after-push"
    elif args.after_sold:  trigger = "after-sold"
    elif args.all:         trigger = "all"
    else:                  trigger = "after-ingest"

    steps = CASCADES[trigger]
    if not args.quiet:
        print(f"refresh_pipeline · trigger={trigger} · {len(steps)} step(s)")
    t0 = time.time()
    failed = []
    for script, sargs, desc, allow_failure in steps:
        ok, _ = run_step(script, sargs, desc, args.quiet, allow_failure)
        if not ok and not allow_failure:
            failed.append(script)
            break
        if not ok and allow_failure:
            failed.append(f"{script} (non-blocking)")
    total = time.time() - t0
    if not args.quiet:
        print(f"done in {total:.1f}s" + (f"  ({len(failed)} failure(s): {', '.join(failed)})" if failed else ""))
    return 1 if any("non-blocking" not in f for f in failed) else 0


if __name__ == "__main__":
    sys.exit(main())
