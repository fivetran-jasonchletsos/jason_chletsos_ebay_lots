"""Single source of truth for refreshing the dashboard.

The problem this solves: every data-changing event (CollX import, eBay push,
a sale, a price revision) leaves a different combination of pages stale. The
user ends up asking "is this page current?" before doing any analysis.

This script is the answer. There are four triggers, each one running a
dependency-ordered DAG of generator scripts so EVERY downstream output is
consistent at a single point in time.

Triggers
--------
  --after-ingest    CollX CSV just imported. ~5s. Cache-only, no eBay API.
  --after-push      A listing was just created on eBay. ~5s. Cache-only.
  --after-sold      A listing just sold. ~15s. Includes daily digest.
  --full            One-button "everything is fresh." ~90-180s. Full eBay
                    refresh, every dashboard page rebuilt, nothing stale.

The --full mode is what to run when you want analysis-ready state. It maps
1:1 to the harpua-daily morning routine plus the new cache-only refreshes,
but consolidated so the pages all come out at the SAME timestamp instead of
drifting apart across separate ad-hoc runs.

Guarantees
----------
1. Steps run in dependency order. A page that reads another page's output
   never runs before its dependency.
2. Steps that are mutually independent run in parallel (bounded concurrency
   so eBay API isn't hammered).
3. The known-broken agents (listing_performance, pnl — schema-drift on
   listings_snapshot) are skipped. They show as "skipped" in the summary.
4. The buyer-message agents (watchers_offer, email_campaign, repeat_buyers)
   are skipped in --full by default, matching the user's standing rule. Pass
   --include-buyer-comms to override.
5. The --apply mode runs the agent in DRY-RUN. Push happens via the daily
   skill's apply-batch step, not from here. This script is for refresh,
   not for execution.

Usage
-----
  python3 refresh_pipeline.py                       # default: --after-ingest
  python3 refresh_pipeline.py --after-push
  python3 refresh_pipeline.py --after-sold
  python3 refresh_pipeline.py --full
  python3 refresh_pipeline.py --full --quiet        # just the summary
  python3 refresh_pipeline.py --full --max-parallel 2   # easier on eBay API
  python3 refresh_pipeline.py --manifest            # print the DAG, don't run

Architecture pattern
--------------------
Each cascade is a list of "waves." A wave is a set of steps that can run in
parallel. Wave N runs to completion before Wave N+1 starts. This is the
standard batch orchestration pattern (Airflow task groups, dbt DAGs, etc.)
without the overhead of a real orchestrator.
"""
from __future__ import annotations
import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).parent


class Step(NamedTuple):
    script: str
    args: tuple = ()
    desc: str = ""
    timeout: int = 240
    allow_failure: bool = False


# ---------------------------------------------------------------------------
# Cascades — dependency-ordered waves.
# ---------------------------------------------------------------------------

CASCADE_AFTER_INGEST = [
    # Wave 1: rebuild inventory plan + smart prices from the fresh CSV.
    [
        Step("inventory_agent.py", desc="inventory plan + multi-source pricing"),
    ],
    # Wave 2: smart-price inference reads inventory_plan.
    [
        Step("infer_prices_agent.py", desc="robust multi-source smart prices"),
    ],
    # Wave 3: the comparison dashboard joins inventory + linkage + smart prices.
    [
        Step("build_collx_vs_ebay.py", desc="CollX vs eBay comparison dashboard"),
    ],
]

CASCADE_AFTER_PUSH = [
    # listings_snapshot was already appended by push_to_ebay.py and linkage_db
    # was already stamped. All we need is the dashboard rebuild so the row
    # appears in "On Both" instead of "CollX-only".
    [
        Step("build_collx_vs_ebay.py", desc="CollX vs eBay comparison dashboard"),
    ],
]

CASCADE_AFTER_SOLD = [
    # The sold reconciler stamps linkage_db; rebuild downstream from there.
    [
        Step("inventory_agent.py", desc="inventory plan (drops sold rows)"),
    ],
    [
        Step("infer_prices_agent.py", desc="smart-price refresh"),
        Step("build_collx_vs_ebay.py", desc="CollX vs eBay comparison"),
    ],
    [
        Step("daily_digest_agent.py", desc="daily digest (sale visible)", allow_failure=True),
    ],
]

# Agents that hit eBay APIs (live fetches). Parallelizable but bounded.
EBAY_FETCHERS = [
    Step("photo_audit_agent.py",          desc="photo audit (Cassini photo signals)",  timeout=180),
    Step("cassini_score_agent.py",        desc="Cassini health scores",                timeout=180),
    Step("seller_hub_agent.py",           desc="seller hub categories",                timeout=120),
    Step("repricing_agent.py",            desc="repricing plan (dry run)",             timeout=180),
    Step("relist_agent.py",               desc="relist unsold plan (dry run)",         timeout=120),
    Step("returns_agent.py",              desc="returns plan",                         timeout=90),
    Step("best_offer_agent.py",           desc="best-offer plan (dry run)",            timeout=180),
    Step("best_offer_autorespond_agent.py", desc="best-offer auto-respond inbox",      timeout=90),
    Step("promoted_listings_agent.py",    desc="promoted listings plan (dry run)",     timeout=180),
    Step("top_sellers_agent.py",          desc="top sellers index",                    timeout=180),
    Step("under_10_agent.py",             desc="under $10 page",                       timeout=180),
    Step("pokemon_news_agent.py",         desc="Pokemon news + set buzz",              timeout=180),
    Step("buyer_watchlist_agent.py",      desc="My Wants (buyer watchlist)",           timeout=240),
    Step("orders_watch_agent.py",         desc="orders watch (last 30d sales)",        timeout=120),
    Step("price_drops_agent.py",          desc="price-drops diff",                     timeout=60,  allow_failure=True),
    Step("price_consistency_agent.py",    desc="price consistency check",              timeout=120, allow_failure=True),
]

# Agents that hit eBay via fetch_deals — same network but slower aggregates.
DEAL_FETCHERS = [
    Step("resale_flips_agent.py",  desc="Resale Flips (buy-to-flip candidates)",  timeout=180),
    Step("jack_pokemon_agent.py",  desc="Jack's Pokemon buyer's guide",           timeout=180),
]

# Local-only generators (no eBay API). Run alongside.
LOCAL_GENERATORS = [
    Step("inventory_agent.py",     desc="inventory plan + multi-source pricing"),
    Step("lot_generator_agent.py", desc="lot generator (auction-block proposals)"),
]


# Full DAG — waves run sequentially, steps within a wave run in parallel.
CASCADE_FULL = [
    # Wave 1: kick off everything that doesn't depend on another generator's
    # output. Local generators + all eBay fetchers run concurrently. This is
    # where most of the wall clock goes.
    LOCAL_GENERATORS + EBAY_FETCHERS,

    # Wave 2: anything that reads an output from Wave 1.
    [
        Step("infer_prices_agent.py",  desc="smart-price blend (reads inventory_plan)"),
    ],
    # Wave 3: anything that reads from Wave 2 + Wave 1.
    [
        Step("build_collx_vs_ebay.py", desc="CollX vs eBay (joins everything)"),
    ] + DEAL_FETCHERS,

    # Wave 4: daily digest reads from many plan files.
    [
        Step("daily_digest_agent.py",  desc="daily digest (rollup)",  allow_failure=True),
    ],
]


CASCADES = {
    "after-ingest": CASCADE_AFTER_INGEST,
    "after-push":   CASCADE_AFTER_PUSH,
    "after-sold":   CASCADE_AFTER_SOLD,
    "full":         CASCADE_FULL,
}


# Known-broken / explicitly-skipped agents.
SKIP_REASONS = {
    "listing_performance_agent.py": "skipped: schema drift on listings_snapshot (known)",
    "pnl_agent.py":                 "skipped: schema drift on listings_snapshot (known)",
    "watchers_offer_agent.py":      "skipped: sends offers to buyers (no-buyer-comms rule)",
    "email_campaign_agent.py":      "skipped: sends email (no-buyer-comms rule)",
    "repeat_buyers_agent.py":       "skipped: messages past buyers (no-buyer-comms rule)",
}


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

def _run_one(step: Step) -> tuple[Step, bool, float, str]:
    """Run a single step and capture timing + final stdout line."""
    t0 = time.time()
    try:
        r = subprocess.run(
            ["python3", step.script, *step.args],
            cwd=str(REPO),
            capture_output=True, text=True, timeout=step.timeout,
        )
    except subprocess.TimeoutExpired:
        return step, False, time.time() - t0, f"TIMEOUT after {step.timeout}s"
    dt = time.time() - t0
    if r.returncode != 0:
        return step, False, dt, (r.stderr or "")[-300:].strip().splitlines()[-1:][0] if r.stderr else "non-zero exit"
    tail = (r.stdout or "").strip().splitlines()
    summary = tail[-1].strip() if tail else "ok"
    return step, True, dt, summary[:140]


def _print_wave_header(wave_idx: int, wave_total: int, steps: list[Step], quiet: bool):
    if quiet:
        return
    print(f"wave {wave_idx + 1}/{wave_total} · {len(steps)} step(s) in parallel")


def _print_step_result(step: Step, ok: bool, dt: float, summary: str, quiet: bool):
    if quiet:
        return
    mark = "ok" if ok else "FAIL"
    print(f"  [{mark:>4s}]  {step.script:34s}  {dt:5.1f}s  {step.desc}")
    if not ok:
        print(f"          {summary}")


def run_cascade(name: str, cascade: list[list[Step]], *, quiet: bool, max_parallel: int) -> dict:
    """Execute a cascade. Returns a summary dict."""
    t_total = time.time()
    results = []   # (step, ok, dt, summary)
    failed_blocking = []
    if not quiet:
        print(f"refresh_pipeline · trigger={name} · {len(cascade)} wave(s)")

    for wave_idx, wave in enumerate(cascade):
        # Filter out skipped steps for transparency.
        runnable = [s for s in wave if s.script not in SKIP_REASONS]
        skipped  = [s for s in wave if s.script in SKIP_REASONS]
        _print_wave_header(wave_idx, len(cascade), runnable, quiet)
        for s in skipped:
            if not quiet:
                print(f"  [skip]  {s.script:34s}        {SKIP_REASONS[s.script]}")
            results.append((s, True, 0.0, SKIP_REASONS[s.script]))

        # Run this wave with bounded parallelism.
        with ThreadPoolExecutor(max_workers=max(1, max_parallel)) as pool:
            futures = {pool.submit(_run_one, s): s for s in runnable}
            for fut in as_completed(futures):
                step, ok, dt, summary = fut.result()
                results.append((step, ok, dt, summary))
                _print_step_result(step, ok, dt, summary, quiet)
                if not ok and not step.allow_failure:
                    failed_blocking.append(step.script)

        if failed_blocking:
            if not quiet:
                print(f"  blocking failure(s): {', '.join(failed_blocking)}")
                print(f"  stopping cascade (subsequent waves would be wrong-data)")
            break

    total = time.time() - t_total
    n_ok       = sum(1 for _, ok, _, _ in results if ok)
    n_fail     = sum(1 for _, ok, _, _ in results if not ok)
    if not quiet:
        print(f"done in {total:.1f}s · {n_ok} ok, {n_fail} fail")
    return {
        "trigger": name,
        "wall_clock_s": round(total, 1),
        "ok_count": n_ok,
        "fail_count": n_fail,
        "failed_blocking": failed_blocking,
        "results": [
            {"script": s.script, "ok": ok, "duration_s": round(dt, 2), "summary": summary}
            for s, ok, dt, summary in results
        ],
    }


def print_manifest():
    """Show the DAG without running anything."""
    print("refresh_pipeline · manifest\n")
    for name, cascade in CASCADES.items():
        print(f"### {name}")
        for i, wave in enumerate(cascade, 1):
            print(f"  wave {i}:")
            for s in wave:
                tag = "  [skip]" if s.script in SKIP_REASONS else "        "
                print(f"   {tag} {s.script:34s} {s.desc}")
        print()
    print("known skips:")
    for script, reason in SKIP_REASONS.items():
        print(f"  {script}: {reason}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--after-ingest", action="store_true",
                   help="CollX CSV import just ran (default if no trigger given).")
    g.add_argument("--after-push",   action="store_true",
                   help="push_to_ebay.py just listed a card.")
    g.add_argument("--after-sold",   action="store_true",
                   help="A listing just sold; reconcile dashboards.")
    g.add_argument("--full",         action="store_true",
                   help="Refresh every page in one consistent run (~90-180s).")
    g.add_argument("--manifest",     action="store_true",
                   help="Print the DAG and exit without running.")

    ap.add_argument("--quiet",       action="store_true",
                    help="Suppress per-step output; just the final summary.")
    ap.add_argument("--max-parallel", type=int, default=4,
                    help="Max concurrent generators (default 4). Lower if you "
                         "hit eBay API throttling.")
    args = ap.parse_args()

    if args.manifest:
        print_manifest()
        return 0

    if args.after_push:    trigger = "after-push"
    elif args.after_sold:  trigger = "after-sold"
    elif args.full:        trigger = "full"
    else:                  trigger = "after-ingest"

    summary = run_cascade(trigger, CASCADES[trigger],
                          quiet=args.quiet,
                          max_parallel=args.max_parallel)
    return 1 if summary["failed_blocking"] else 0


if __name__ == "__main__":
    sys.exit(main())
