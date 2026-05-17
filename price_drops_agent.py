#!/usr/bin/env python3
"""price_drops_agent.py

Daily price-drop diff agent. Ingests every existing plan JSON that contains
live eBay listings (Pikachu deal scan, upcoming-set scan, buyer watchlist,
and any pokemon_<character>_plan.json files Agent B is writing in parallel),
snapshots the current item-id -> price map, diffs it against the prior
snapshot from the last run, and emits:

  output/price_drops_snapshot.json   <- current state (overwrites prior)
  output/price_drops_plan.json       <- {drops, new_today, gone_today}
  docs/price_drops.html              <- dopamine page

CLI:
  python3 price_drops_agent.py            run snapshot + diff + render
  python3 price_drops_agent.py --reset    clear the prior snapshot first
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

ROOT = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(ROOT, "output")
DOCS_DIR = os.path.join(ROOT, "docs")

SNAPSHOT_PATH = os.path.join(OUTPUT_DIR, "price_drops_snapshot.json")
PLAN_PATH = os.path.join(OUTPUT_DIR, "price_drops_plan.json")
HTML_PATH = os.path.join(DOCS_DIR, "price_drops.html")

# Drop sensitivity: flag if price fell by >=5% AND >=$1.00 (whichever is larger).
DROP_PCT_MIN = 5.0
DROP_DOLLAR_MIN = 1.00


# ---------------------------------------------------------------------------
# Plan ingestion
# ---------------------------------------------------------------------------

def _plan_sources() -> List[str]:
    """Glob every plan JSON we want to track. De-dup, stable order."""
    seen: List[str] = []
    patterns = [
        os.path.join(OUTPUT_DIR, "pokemon_*_plan.json"),  # pikachu, news, and Agent B files
        os.path.join(OUTPUT_DIR, "buyer_watchlist_plan.json"),
    ]
    for pat in patterns:
        for p in sorted(glob.glob(pat)):
            if p not in seen:
                seen.append(p)
    return seen


def _walk_items(node: Any, source: str, context: Optional[str] = None) -> Iterable[Dict[str, Any]]:
    """Recursively yield every dict that looks like a listing item.

    A listing item is a dict with an `item_id` AND a numeric `price` AND a `url`.
    We capture an inherited `context` label (bucket name / player name / set name)
    if we can find one on the way down.
    """
    if isinstance(node, dict):
        # Update inherited context from common keys.
        local_ctx = context
        for key in ("label", "name", "q", "slug"):
            v = node.get(key)
            if isinstance(v, str) and v.strip():
                local_ctx = v.strip()
                break

        if (
            "item_id" in node
            and isinstance(node.get("price"), (int, float))
            and isinstance(node.get("url"), str)
        ):
            yield {
                "source": source,
                "context": context or local_ctx or "",
                "item_id": str(node.get("item_id") or ""),
                "title": str(node.get("title") or "").strip(),
                "price": float(node["price"]),
                "url": node.get("url"),
                "image": node.get("image") or "",
                "seller": node.get("seller") or "",
                "condition": node.get("condition") or "",
                "discount_pct": node.get("discount_pct"),
            }
            return  # don't recurse into the item itself

        for v in node.values():
            yield from _walk_items(v, source, local_ctx)

    elif isinstance(node, list):
        for v in node:
            yield from _walk_items(v, source, context)


def collect_current() -> Dict[str, Dict[str, Any]]:
    """Build today's snapshot: { item_id: {...listing...} }.

    Items with item_id == "0" or "" are skipped (they are eBay placeholder rows
    that recur every scan and would generate noisy "new"/"gone" churn).
    When the same item_id appears in multiple plans, the lowest price wins
    (this is the price the buyer would actually see).
    """
    current: Dict[str, Dict[str, Any]] = {}
    for path in _plan_sources():
        source = os.path.basename(path)
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"[skip] {source}: {exc}", file=sys.stderr)
            continue

        for item in _walk_items(data, source=source):
            iid = item["item_id"]
            if not iid or iid == "0":
                continue
            prev = current.get(iid)
            if prev is None or item["price"] < prev["price"]:
                current[iid] = item

    return current


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------

def load_prior() -> Optional[Dict[str, Dict[str, Any]]]:
    if not os.path.exists(SNAPSHOT_PATH):
        return None
    try:
        with open(SNAPSHOT_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, dict) else None


def save_snapshot(items: Dict[str, Dict[str, Any]]) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n": len(items),
        "items": items,
    }
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)


def diff(
    prior: Dict[str, Dict[str, Any]],
    current: Dict[str, Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    drops: List[Dict[str, Any]] = []
    new_today: List[Dict[str, Any]] = []
    gone_today: List[Dict[str, Any]] = []

    for iid, today in current.items():
        if iid not in prior:
            new_today.append(today)
            continue
        yesterday = prior[iid]
        old_price = float(yesterday.get("price") or 0.0)
        new_price = float(today.get("price") or 0.0)
        delta = old_price - new_price
        if old_price <= 0 or delta <= 0:
            continue
        pct = (delta / old_price) * 100.0
        # Trigger: >=5% AND >=$1 (the user said "5% OR $1, whichever is larger"
        # i.e. require the bigger of the two thresholds — so AND in practice).
        if pct >= DROP_PCT_MIN and delta >= DROP_DOLLAR_MIN:
            drops.append({
                **today,
                "old_price": round(old_price, 2),
                "new_price": round(new_price, 2),
                "delta": round(delta, 2),
                "drop_pct": round(pct, 2),
            })

    for iid, yesterday in prior.items():
        if iid not in current:
            gone_today.append(yesterday)

    drops.sort(key=lambda r: r["delta"], reverse=True)
    new_today.sort(key=lambda r: r.get("price") or 0.0)
    gone_today.sort(key=lambda r: r.get("price") or 0.0, reverse=True)
    return drops, new_today, gone_today


def write_plan(
    drops: List[Dict[str, Any]],
    new_today: List[Dict[str, Any]],
    gone_today: List[Dict[str, Any]],
    first_run: bool,
) -> Dict[str, Any]:
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "first_run": first_run,
        "drop_thresholds": {"pct_min": DROP_PCT_MIN, "dollar_min": DROP_DOLLAR_MIN},
        "counts": {
            "drops": len(drops),
            "new_today": len(new_today),
            "gone_today": len(gone_today),
        },
        "drops": drops,
        "new_today": new_today,
        "gone_today": gone_today,
    }
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(PLAN_PATH, "w", encoding="utf-8") as fh:
        json.dump(plan, fh, indent=2)
    return plan


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def _money(v: Any) -> str:
    try:
        return f"${float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _card_drop(row: Dict[str, Any]) -> str:
    img = _esc(row.get("image") or "")
    title = _esc(row.get("title") or "Untitled listing")
    url = _esc(row.get("url") or "#")
    ctx = _esc(row.get("context") or "")
    old = _money(row.get("old_price"))
    new = _money(row.get("new_price"))
    delta = _money(row.get("delta"))
    pct = row.get("drop_pct") or 0
    return f"""
    <a class="pd-card pd-card-drop" href="{url}" target="_blank" rel="noopener">
      <div class="pd-img" style="background-image:url('{img}')"></div>
      <div class="pd-meta">
        <div class="pd-ctx">{ctx}</div>
        <div class="pd-title">{title}</div>
        <div class="pd-price-row">
          <span class="pd-price-old">{old}</span>
          <span class="pd-arrow">&rarr;</span>
          <span class="pd-price-new">{new}</span>
        </div>
        <div class="pd-delta">▼ {delta} ({pct:.1f}%)</div>
        <div class="pd-cta">Buy now &rarr;</div>
      </div>
    </a>
    """


def _card_basic(row: Dict[str, Any], variant: str) -> str:
    img = _esc(row.get("image") or "")
    title = _esc(row.get("title") or "Untitled listing")
    url = _esc(row.get("url") or "#")
    ctx = _esc(row.get("context") or "")
    price = _money(row.get("price"))
    badge = "NEW" if variant == "new" else "GONE"
    return f"""
    <a class="pd-card pd-card-{variant}" href="{url}" target="_blank" rel="noopener">
      <div class="pd-img" style="background-image:url('{img}')">
        <span class="pd-badge pd-badge-{variant}">{badge}</span>
      </div>
      <div class="pd-meta">
        <div class="pd-ctx">{ctx}</div>
        <div class="pd-title">{title}</div>
        <div class="pd-price-row"><span class="pd-price-new">{price}</span></div>
      </div>
    </a>
    """


def _section(title: str, blurb: str, cards_html: str, empty_msg: str) -> str:
    if not cards_html.strip():
        body = f'<div class="pd-empty">{_esc(empty_msg)}</div>'
    else:
        body = f'<div class="pd-grid">{cards_html}</div>'
    return f"""
    <section class="pd-section">
      <div class="pd-section-head">
        <h2>{_esc(title)}</h2>
        <p>{_esc(blurb)}</p>
      </div>
      {body}
    </section>
    """


_CSS = """
:root{--bg:#0a0a0a;--surface:#141414;--surface-2:#1a1a1a;--border:rgba(212,175,55,.1);--border-mid:rgba(212,175,55,.22);--gold:#d4af37;--gold-bright:#f4ce5d;--text:#f1efe9;--text-muted:#9a9388;--success:#3ad08a;--danger:#ff6b6b;--info:#7dc4ff;--r-md:10px}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font-family:'Inter',system-ui,sans-serif;font-size:14px;line-height:1.5}
main{max-width:1200px;margin:0 auto;padding:28px 18px 80px}
h1{font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em;margin:0 0 6px;color:var(--gold-bright)}
.pd-sub{color:var(--text-muted);font-size:13px;margin:0 0 22px}
.pd-sub b{color:var(--text)}
.pk-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:22px 0}
.pk-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:16px 18px;border-left:3px solid var(--gold)}
.pk-kpi.kpi-drop{border-left-color:var(--success)}
.pk-kpi.kpi-new{border-left-color:var(--info)}
.pk-kpi.kpi-gone{border-left-color:var(--danger)}
.pk-n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold-bright);line-height:1}
.kpi-drop .pk-n{color:var(--success)}
.kpi-new .pk-n{color:var(--info)}
.kpi-gone .pk-n{color:var(--danger)}
.pk-l{color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.1em;margin-top:6px}
.pd-section{margin:36px 0}
.pd-section-head{border-bottom:1px solid var(--border);padding-bottom:10px;margin-bottom:16px}
.pd-section-head h2{margin:0;font-family:'Bebas Neue',sans-serif;font-size:36px;letter-spacing:.02em;color:var(--gold)}
.pd-section-head p{margin:4px 0 0;color:var(--text-muted);font-size:13px}
.pd-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:14px}
.pd-card{display:block;text-decoration:none;color:inherit;background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);overflow:hidden;transition:transform .15s ease,border-color .15s ease,box-shadow .15s ease}
.pd-card:hover{transform:translateY(-3px);border-color:var(--border-mid);box-shadow:0 10px 30px rgba(0,0,0,.45)}
.pd-card-drop{border-color:rgba(58,208,138,.28)}
.pd-card-drop:hover{border-color:var(--success);box-shadow:0 12px 32px rgba(58,208,138,.18)}
.pd-card-gone{opacity:.72}
.pd-img{position:relative;aspect-ratio:1/1;background-size:cover;background-position:center;background-color:var(--surface-2)}
.pd-badge{position:absolute;top:8px;left:8px;font-size:10px;font-weight:900;letter-spacing:.15em;padding:4px 9px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.4)}
.pd-badge-new{background:var(--info);color:#002238}
.pd-badge-gone{background:#2a2a2a;color:var(--danger);border:1px solid var(--danger)}
.pd-meta{padding:10px 12px 14px}
.pd-ctx{font-size:10px;letter-spacing:.14em;text-transform:uppercase;color:var(--text-muted);margin-bottom:4px;min-height:12px}
.pd-title{font-size:12px;line-height:1.35;color:var(--text);margin-bottom:8px;min-height:32px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.pd-price-row{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.pd-price-old{font-family:'Bebas Neue',sans-serif;font-size:20px;color:var(--text-muted);text-decoration:line-through}
.pd-arrow{color:var(--text-muted)}
.pd-price-new{font-family:'Bebas Neue',sans-serif;font-size:26px;color:var(--gold-bright)}
.pd-card-drop .pd-price-new{color:var(--success)}
.pd-delta{margin-top:6px;font-size:12px;font-weight:700;color:var(--success)}
.pd-cta{margin-top:8px;font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold-bright);font-weight:700}
.pd-empty{background:var(--surface);border:1px dashed var(--border-mid);border-radius:var(--r-md);padding:28px;text-align:center;color:var(--text-muted);font-size:13px}
@media (max-width:600px){h1{font-size:42px}.pd-section-head h2{font-size:28px}.pd-grid{grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:10px}}
"""


def render_html(plan: Dict[str, Any], first_run: bool) -> None:
    drops = plan.get("drops", [])
    new_today = plan.get("new_today", [])
    gone_today = plan.get("gone_today", [])
    generated_at = plan.get("generated_at", "")

    if first_run:
        hero_note = (
            "First snapshot just captured — there is nothing to compare against yet. "
            "Run this again tomorrow (or after the next scan) and prices that fell "
            "will pop up here."
        )
    else:
        hero_note = (
            "Diff between today's scan and the prior run. "
            f"Drops trigger at &ge;{DROP_PCT_MIN:.0f}% AND &ge;${DROP_DOLLAR_MIN:.2f}."
        )

    drops_html = "\n".join(_card_drop(r) for r in drops[:60])
    new_html = "\n".join(_card_basic(r, "new") for r in new_today[:60])
    gone_html = "\n".join(_card_basic(r, "gone") for r in gone_today[:60])

    os.makedirs(DOCS_DIR, exist_ok=True)
    page = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
  <meta name="theme-color" content="#0a0a0a">
  <title>Price Drops · Daily Watch</title>
  <link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>{_CSS}</style>
</head>
<body>
  <main>
    <h1>Price Drops</h1>
    <p class="pd-sub">Daily diff against the last scan · generated <b>{_esc(generated_at)}</b><br>{hero_note}</p>

    <div class="pk-kpis">
      <div class="pk-kpi kpi-drop">
        <div class="pk-n">{len(drops)}</div>
        <div class="pk-l">Price drops</div>
      </div>
      <div class="pk-kpi kpi-new">
        <div class="pk-n">{len(new_today)}</div>
        <div class="pk-l">New today</div>
      </div>
      <div class="pk-kpi kpi-gone">
        <div class="pk-n">{len(gone_today)}</div>
        <div class="pk-l">Gone today</div>
      </div>
      <div class="pk-kpi">
        <div class="pk-n">{len(drops) + len(new_today)}</div>
        <div class="pk-l">Total actionable</div>
      </div>
    </div>

    {_section(
        "Biggest drops",
        "Listings whose price fell since the last run. Sorted by dollars saved.",
        drops_html,
        "No price drops since the prior run. Check back after the next scan.",
    )}

    {_section(
        "New today",
        "Listings that didn't exist in the last snapshot. Fresh inventory the agents found.",
        new_html,
        "No new listings since the prior run.",
    )}

    {_section(
        "Gone today",
        "Listings that disappeared since the prior run — sold, ended, or delisted.",
        gone_html,
        "Nothing has dropped off since the prior run.",
    )}
  </main>
</body>
</html>
"""
    with open(HTML_PATH, "w", encoding="utf-8") as fh:
        fh.write(page)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Daily price-drop diff agent.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the prior snapshot before running (next run becomes first-run).",
    )
    args = parser.parse_args(argv)

    if args.reset and os.path.exists(SNAPSHOT_PATH):
        os.remove(SNAPSHOT_PATH)
        print(f"[reset] removed {SNAPSHOT_PATH}")

    prior = load_prior()
    current = collect_current()
    print(f"[snapshot] {len(current)} tracked listings across {len(_plan_sources())} plan files")

    if prior is None:
        save_snapshot(current)
        plan = write_plan([], [], [], first_run=True)
        render_html(plan, first_run=True)
        print("[first-run] no prior snapshot — wrote baseline, nothing to diff.")
        print(f"[wrote] {SNAPSHOT_PATH}")
        print(f"[wrote] {PLAN_PATH}")
        print(f"[wrote] {HTML_PATH}")
        return 0

    drops, new_today, gone_today = diff(prior, current)
    save_snapshot(current)
    plan = write_plan(drops, new_today, gone_today, first_run=False)
    render_html(plan, first_run=False)

    print(
        f"[diff] drops={len(drops)} new={len(new_today)} gone={len(gone_today)} "
        f"(prior={len(prior)}, current={len(current)})"
    )
    if drops:
        top = drops[0]
        print(
            f"[top drop] {top.get('title','')[:60]!r} "
            f"{_money(top.get('old_price'))} -> {_money(top.get('new_price'))} "
            f"({top.get('drop_pct')}%)"
        )
    print(f"[wrote] {SNAPSHOT_PATH}")
    print(f"[wrote] {PLAN_PATH}")
    print(f"[wrote] {HTML_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
