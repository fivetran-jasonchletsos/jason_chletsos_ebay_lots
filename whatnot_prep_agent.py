"""whatnot_prep_agent.py — Live-stream prep for Whatnot (no public API).
Turns current eBay inventory + sold-history comps into a paste-ready show:
rotating descriptions, 60-min lot order (warmups -> main -> closers), and
per-lot opening bid (= median * 0.40) / BIN (= median * 1.10).
Inputs:  output/listings_snapshot.json, sold_history.json
Outputs: output/whatnot_show_plan.json, output/whatnot_lot_order.csv, docs/whatnot.html
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import promote

REPO_ROOT     = Path(__file__).parent
INV_PATH      = REPO_ROOT / "output" / "listings_snapshot.json"
SOLD_PATH     = REPO_ROOT / "sold_history.json"
OUT_PLAN      = REPO_ROOT / "output" / "whatnot_show_plan.json"
OUT_CSV       = REPO_ROOT / "output" / "whatnot_lot_order.csv"
OUT_HTML      = REPO_ROOT / "docs"   / "whatnot.html"

WARMUP_COUNT     = 10        # 8-10 cheap items to open the show
WARMUP_MAX_PRICE = 5.00
CLOSER_COUNT     = 5         # highest-margin items at the end
DEFAULT_DURATION = 60        # minutes per show
OPEN_BID_FACTOR  = 0.40
BIN_FACTOR       = 1.10


def _load_json(path: Path, fallback: Any) -> Any:
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return fallback


def _to_float(val: Any) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

def _tokens(title: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(title or "") if len(t) > 2}


def _year_in(title: str) -> str | None:
    m = re.search(r"\b(19|20)\d{2}\b", title or "")
    return m.group(0) if m else None


def build_price_index(sold: list[dict]) -> list[tuple[set[str], float]]:
    """Return [(tokens, price)] across the sold-history corpus."""
    out: list[tuple[set[str], float]] = []
    for row in sold:
        price = _to_float(row.get("sale_price"))
        if price <= 0:
            continue
        toks = _tokens(row.get("title") or "")
        if toks:
            out.append((toks, price))
    return out


def median_for(title: str, index: list[tuple[set[str], float]],
               min_overlap: int = 3) -> float | None:
    """Find sold-history items with strong token overlap; return median price."""
    if not title:
        return None
    needle = _tokens(title)
    if not needle:
        return None
    year = _year_in(title)
    matches: list[float] = []
    for toks, price in index:
        overlap = len(needle & toks)
        if overlap >= min_overlap:
            # Year-locked bonus: don't match a 2024 to a 1992
            if year:
                other_year = next(iter(t for t in toks if t == year), None)
                if year in toks or other_year:
                    matches.append(price)
                elif overlap >= min_overlap + 2:
                    matches.append(price)
            else:
                matches.append(price)
    if not matches:
        return None
    return float(statistics.median(matches))


def _category_for(title: str) -> str:
    t = (title or "").lower()
    if "pokemon" in t or "pokémon" in t or "charizard" in t or "pikachu" in t:
        return "Pokemon"
    if any(k in t for k in ("nfl", "football", "panini prizm", "donruss")):
        return "Football"
    if any(k in t for k in ("nba", "basketball", "hoops")):
        return "Basketball"
    if any(k in t for k in ("mlb", "baseball", "topps")):
        return "Baseball"
    if "hockey" in t or "nhl" in t:
        return "Hockey"
    return "Mixed"


def build_lot_order(inventory: list[dict],
                    index: list[tuple[set[str], float]]) -> list[dict]:
    """Decorate inventory with pricing intel and order for a Whatnot show."""
    decorated: list[dict] = []
    for item in inventory:
        title = item.get("title") or ""
        listed = _to_float(item.get("price"))
        median = median_for(title, index)
        baseline = median if median else listed
        open_bid = max(1.00, round(baseline * OPEN_BID_FACTOR, 2))
        bin_price = round(baseline * BIN_FACTOR, 2) if baseline else round(listed * 1.10, 2)
        margin = (bin_price - open_bid) if bin_price and open_bid else 0.0
        decorated.append({
            "item_id": item.get("item_id"), "title": title,
            "pic": item.get("pic") or "", "url": item.get("url") or "",
            "listed": listed, "median": round(median, 2) if median else None,
            "open_bid": open_bid, "bin": bin_price,
            "margin": round(margin, 2), "category": _category_for(title),
        })
    warmups = sorted([d for d in decorated if d["listed"] <= WARMUP_MAX_PRICE],
                     key=lambda d: d["listed"])[:WARMUP_COUNT]
    warmup_ids = {d["item_id"] for d in warmups}
    remaining = [d for d in decorated if d["item_id"] not in warmup_ids]
    closers = sorted(remaining, key=lambda d: d["margin"], reverse=True)[:CLOSER_COUNT]
    closer_ids = {d["item_id"] for d in closers}
    middle = sorted([d for d in remaining if d["item_id"] not in closer_ids],
                    key=lambda d: d["listed"])
    interleaved = _interleave_by_category(middle)
    ordered = warmups + interleaved + closers
    for pos, lot in enumerate(ordered, 1):
        lot["position"] = pos
        if pos <= len(warmups):
            lot["segment"] = "warmup"
        elif pos > len(ordered) - len(closers):
            lot["segment"] = "closer"
        else:
            lot["segment"] = "main"
    return ordered


def _interleave_by_category(lots: list[dict]) -> list[dict]:
    """Round-robin across categories so the show doesn't get monotonous."""
    buckets: dict[str, list[dict]] = {}
    for lot in lots:
        buckets.setdefault(lot["category"], []).append(lot)
    out: list[dict] = []
    while any(buckets.values()):
        for cat in list(buckets.keys()):
            if buckets[cat]:
                out.append(buckets[cat].pop(0))
            else:
                buckets.pop(cat, None)
    return out


SHOW_TEMPLATES: list[str] = [
    ("Live tonight: {lot_count} cards, openings start at $1. Tonight's headline hits: {teasers}. "
     "Bid early — first 10 lots are $5-and-under giveaways. Free shipping over $50."),
    ("{lot_count}-lot blowout starting now. We're going hard on {top_cats}. Featured pulls: {teasers}. "
     "Stick around — closing 5 lots are our highest-margin bombs. "
     "Giveaway: one free pack to a random bidder in the first 15 minutes."),
    ("Auction night! Everything opens at 40% of market comp. {lot_count} lots over {duration} minutes. "
     "Looking for: {top_cats}? You're in the right place. Tonight's chase: {teasers}. "
     "Buy 3 lots, get free combined shipping."),
    ("Doors open. {lot_count} cards on the block tonight. Warmup round is $1-$5 lots — perfect for new viewers. "
     "Big closers: {teasers}. Use code FIRSTBID at checkout for $5 off your first win."),
]


def render_descriptions(lots: list[dict], duration: int) -> list[str]:
    cats = [lot["category"] for lot in lots if lot["category"] != "Mixed"]
    top_cats = ", ".join(c for c, _ in statistics_counter(cats)[:3]) or "Mixed cards"
    closers = [lot for lot in lots if lot["segment"] == "closer"]
    teasers = " · ".join(_short_title(l["title"]) for l in closers[:3]) or "surprise hits"
    ctx = {"lot_count": len(lots), "duration": duration, "top_cats": top_cats, "teasers": teasers}
    return [tpl.format(**ctx) for tpl in SHOW_TEMPLATES]


def statistics_counter(items: Iterable[str]) -> list[tuple[str, int]]:
    counts: dict[str, int] = {}
    for it in items:
        counts[it] = counts.get(it, 0) + 1
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)


def _short_title(title: str, max_len: int = 48) -> str:
    return title if len(title) <= max_len else title[: max_len - 1].rstrip() + "…"


def write_csv(lots: list[dict], out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "position", "segment", "title", "category",
            "opening_bid", "buy_it_now", "comp_median", "image_url", "ebay_url",
        ])
        for lot in lots:
            writer.writerow([
                lot["position"], lot["segment"], lot["title"], lot["category"],
                f"{lot['open_bid']:.2f}", f"{lot['bin']:.2f}",
                f"{lot['median']:.2f}" if lot["median"] else "",
                lot["pic"], lot["url"],
            ])


def write_plan(lots: list[dict], descriptions: list[str],
               duration: int, kpis: dict, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "duration_min": duration,
        "kpis":         kpis,
        "descriptions": descriptions,
        "lots":         lots,
    }
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def render_html(lots: list[dict], descriptions: list[str],
                duration: int, kpis: dict) -> str:
    desc_cards = []
    for idx, d in enumerate(descriptions, 1):
        desc_cards.append(
            f'<div class="wn-desc"><div class="wn-desc-head">'
            f'<span class="wn-desc-tag">Template {idx}</span>'
            f'<button class="wn-copy" onclick="wnCopy(this)" '
            f'data-text="{html.escape(d, quote=True)}">Copy</button></div>'
            f'<p>{html.escape(d)}</p></div>'
        )

    rows = []
    for lot in lots:
        seg = lot["segment"]
        seg_class = {"warmup": "wn-warmup", "closer": "wn-closer"}.get(seg, "wn-main")
        median_txt = f"${lot['median']:.2f}" if lot["median"] else "—"
        img = (f'<img src="{html.escape(lot["pic"])}" loading="lazy" '
               f'alt="" width="40" height="40">') if lot["pic"] else ""
        rows.append(
            f'<tr class="{seg_class}">'
            f'<td>{lot["position"]}</td>'
            f'<td>{img}</td>'
            f'<td><a href="{html.escape(lot["url"])}" target="_blank" rel="noopener">'
            f'{html.escape(_short_title(lot["title"], 60))}</a>'
            f'<div class="wn-cat">{html.escape(lot["category"])} · {seg}</div></td>'
            f'<td class="wn-num">${lot["open_bid"]:.2f}</td>'
            f'<td class="wn-num">${lot["bin"]:.2f}</td>'
            f'<td class="wn-num">{median_txt}</td>'
            f'</tr>'
        )

    kpi_html = (
        f'<div class="kpi"><div class="kpi-label">Lots</div><div class="kpi-val">{kpis["lot_count"]}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Est. GMV</div><div class="kpi-val">${kpis["est_gmv"]:,.0f}</div></div>'
        f'<div class="kpi"><div class="kpi-label">Show Length</div><div class="kpi-val">{duration} min</div></div>'
        f'<div class="kpi"><div class="kpi-label">Take Rate (proj.)</div><div class="kpi-val">{kpis["take_rate_pct"]:.0f}%</div></div>'
    )
    body = (
        '<main class="container" style="max-width:1180px;">'
        '<section class="hero"><h1 class="page-title">Whatnot Live-Stream Prep</h1>'
        '<p class="page-sub">Ready-to-paste show plan generated from current inventory + sold-history comps.</p></section>'
        f'<section class="kpi-row">{kpi_html}</section>'
        '<section class="card"><h2>Show Descriptions</h2>'
        '<p class="muted">Pick one — they rotate every refresh so each show feels fresh.</p>'
        f'<div class="wn-desc-grid">{"".join(desc_cards)}</div></section>'
        '<section class="card"><div class="wn-toolbar">'
        f'<h2 style="margin:0;">Lot Order — {len(lots)} Cards</h2>'
        '<a class="wn-dl" href="../output/whatnot_lot_order.csv" download>Download Whatnot CSV</a></div>'
        f'<p class="muted">Yellow rows = warmup ($1-$5 to draw viewers). Green rows = closers (highest margin). '
        f'Opening bid = comp median × {OPEN_BID_FACTOR:.0%}. BIN = comp median × {BIN_FACTOR:.0%}.</p>'
        '<div class="wn-table-wrap"><table class="wn-table">'
        '<thead><tr><th>#</th><th>Img</th><th>Title</th>'
        '<th class="wn-num">Open</th><th class="wn-num">BIN</th><th class="wn-num">Median Sold</th></tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div></section>'
        '<section class="card"><h2>Live-Stream Tips</h2><ul class="wn-tips">'
        '<li><strong>0:00-10:00</strong> — run the warmup ladder. Cheap lots build viewer count and trust.</li>'
        '<li><strong>10:00-15:00</strong> — drop the first giveaway. Free pack to a random bidder in the warmup band.</li>'
        f'<li><strong>15:00-{duration - 10}:00</strong> — main block. Alternate categories every 3-4 lots; call out the comp every time.</li>'
        f'<li><strong>Last 10 min</strong> — closers. Tease them at the top of the show ("stick around for the {len(lots)}th lot…").</li>'
        '<li>If a lot stalls under the opening bid for 15 seconds, hammer it. Whatnot rewards pace.</li>'
        '<li>Always say the BIN out loud — viewers don\'t read overlays.</li></ul></section></main>'
        '<script>function wnCopy(b){const t=b.getAttribute("data-text");'
        'navigator.clipboard.writeText(t).then(()=>{const o=b.textContent;b.textContent="Copied!";'
        'setTimeout(()=>{b.textContent=o;},1500);});}</script>'
    )
    extra_css = (
        '<style>'
        '.wn-desc-grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));}'
        '.wn-desc{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px;}'
        '.wn-desc-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}'
        '.wn-desc-tag{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--gold);}'
        '.wn-desc p{margin:0;color:var(--text);font-size:14px;line-height:1.55;}'
        '.wn-copy{background:var(--gold);color:#111;border:none;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;font-weight:600;}'
        '.wn-toolbar{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px;}'
        '.wn-dl{background:var(--success,#7fc77a);color:#0a0a0a;text-decoration:none;padding:10px 16px;border-radius:8px;font-weight:700;font-size:14px;}'
        '.wn-table-wrap{overflow-x:auto;margin-top:12px;}'
        '.wn-table{width:100%;border-collapse:collapse;font-size:13px;}'
        '.wn-table th,.wn-table td{padding:8px 10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:middle;}'
        '.wn-table th{background:var(--surface-2);font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);}'
        '.wn-table img{border-radius:4px;display:block;}'
        '.wn-num{text-align:right;font-variant-numeric:tabular-nums;}'
        '.wn-cat{font-size:11px;color:var(--text-muted);margin-top:2px;}'
        '.wn-warmup{background:rgba(212,175,55,.08);}'
        '.wn-closer{background:rgba(127,199,122,.10);}'
        '.wn-tips{line-height:1.7;color:var(--text);padding-left:18px;}'
        '.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0 24px;}'
        '.kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:14px;}'
        '.kpi-label{font-size:11px;letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px;}'
        '.kpi-val{font-family:"Bebas Neue",sans-serif;font-size:32px;color:var(--gold);line-height:1;}'
        '</style>'
    )
    return promote.html_shell("Whatnot Prep", body,
                              extra_head=extra_css,
                              active_page="whatnot.html")


def compute_kpis(lots: list[dict], sold_count: int) -> dict:
    est_gmv = sum(lot["open_bid"] * 1.5 for lot in lots)
    # Project take rate: assume past Whatnot streams sell ~70% but cap by sold/listed ratio
    listed = max(1, len(lots))
    take_rate = min(70.0, (sold_count / max(listed, 1)) * 100.0)
    take_rate = max(take_rate, 50.0)  # whatnot floor
    return {
        "lot_count":      len(lots),
        "est_gmv":        round(est_gmv, 2),
        "take_rate_pct":  round(take_rate, 1),
    }


def suggested_duration(lot_count: int) -> int:
    """~30 seconds per lot + 10 min of patter/giveaways, rounded to 15 min."""
    raw = (lot_count * 0.5) + 10
    return max(60, int(round(raw / 15.0) * 15))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=None,
                        help="Seed for description rotation (reproducible runs).")
    args = parser.parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    inventory = _load_json(INV_PATH, [])
    sold      = _load_json(SOLD_PATH, [])
    if not inventory:
        print(f"No inventory at {INV_PATH}; aborting.")
        return

    index = build_price_index(sold)
    lots = build_lot_order(inventory, index)
    duration = suggested_duration(len(lots))
    descriptions = render_descriptions(lots, duration)
    # Rotate so the most-recently-generated template is first.
    rotated = descriptions[datetime.now().day % len(descriptions):] + \
              descriptions[: datetime.now().day % len(descriptions)]
    kpis = compute_kpis(lots, len(sold))

    write_plan(lots, rotated, duration, kpis, OUT_PLAN)
    write_csv(lots, OUT_CSV)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(render_html(lots, rotated, duration, kpis),
                        encoding="utf-8")

    print(f"Wrote {OUT_PLAN.relative_to(REPO_ROOT)}")
    print(f"Wrote {OUT_CSV.relative_to(REPO_ROOT)}")
    print(f"Wrote {OUT_HTML.relative_to(REPO_ROOT)}")
    print(f"Lots: {len(lots)}  duration: {duration} min  "
          f"est GMV: ${kpis['est_gmv']:,.2f}")


if __name__ == "__main__":
    main()
