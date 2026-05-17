"""
cassini_score_agent.py — Per-listing Cassini health score (0-100).

Synthesizes 7 observable Cassini ranking signals (photos, specifics, title,
impressions, CTR, recent sale, offer eligibility) into a single 0-100 score
per active listing so the seller can triage rescue candidates.

Inputs (all under output/, all optional — agent degrades gracefully):
  listing_performance_plan.json, photo_quality_plan.json, specifics_plan.json,
  listings_snapshot.json, ../sold_history.json, cassini_score_snapshot.json.

Rubric (max 100): photos>=8@1600+ (25), specifics>=10 (20), title<=80c clean (15),
  impressions>=median (15), CTR>=0.5% (10), sold<90d (10), best-offer eligible (5).
Buckets: 80+=green, 50-79=yellow, <50=red.

Outputs: output/cassini_score_plan.json, output/cassini_score_snapshot.json,
docs/cassini.html.  Run:  python3 cassini_score_agent.py
"""

from __future__ import annotations

import argparse
import html
import json
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import promote


REPO_ROOT          = Path(__file__).parent
OUTPUT_DIR         = REPO_ROOT / "output"
PERF_PATH          = OUTPUT_DIR / "listing_performance_plan.json"
PHOTO_PATH         = OUTPUT_DIR / "photo_quality_plan.json"
SPECIFICS_PATH     = OUTPUT_DIR / "specifics_plan.json"
SNAPSHOT_PATH      = OUTPUT_DIR / "listings_snapshot.json"
SOLD_PATH          = REPO_ROOT / "sold_history.json"
PRIOR_SNAPSHOT     = OUTPUT_DIR / "cassini_score_snapshot.json"
PLAN_PATH          = OUTPUT_DIR / "cassini_score_plan.json"
REPORT_PATH        = promote.OUTPUT_DIR / "cassini.html"

# === Thresholds (single source of truth) ===
PHOTO_COUNT_MIN    = 8
PHOTO_DIM_MIN      = 1600
SPECIFICS_MIN      = 10
TITLE_CHARS_MAX    = 80
CTR_MIN_PCT        = 0.5
SOLD_LOOKBACK_DAYS = 90

# Score weights — keep aligned with the docstring rubric.
W_PHOTOS           = 25
W_SPECIFICS        = 20
W_TITLE            = 15
W_IMPRESSIONS      = 15
W_CTR              = 10
W_SOLD             = 10
W_BEST_OFFER       = 5

# Bucket thresholds
GREEN_AT           = 80
YELLOW_AT          = 50

# Same fluff regex used in promote.py's title quality scan — kept inline so we
# don't import a private helper.
FLUFF_RE = re.compile(
    r"\b(L@@K|LOOK|Wow|Amazing|Must Have|Must-Have|Rare Find|Sweet|Stunning|"
    r"Beautiful|Gorgeous|Awesome|Buy Now|Don't Miss|Steal|GORGEOUS|AMAZING)\b",
    re.IGNORECASE,
)


# ----------------------------------------------------------------------------
# Loaders — every input is optional. Missing => empty index, score continues.
# ----------------------------------------------------------------------------

def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _index_listings(raw: Any) -> list[dict]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "listings" in raw:
        return raw["listings"]
    return []


def _index_photos(raw: Any) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    return {str(l.get("item_id")): l for l in raw.get("listings", []) if l.get("item_id")}


def _index_specifics(raw: Any) -> dict[str, dict]:
    if not isinstance(raw, dict):
        return {}
    return {str(p.get("item_id")): p for p in raw.get("plans", []) if p.get("item_id")}


def _index_perf(raw: Any) -> dict[str, dict]:
    """Walk every bucket in the perf plan and merge into one item_id index."""
    if not isinstance(raw, dict):
        return {}
    buckets = raw.get("buckets") or {}
    idx: dict[str, dict] = {}
    for key in ("impression_leaders", "ctr_leaders", "needs_help"):
        for r in buckets.get(key, []) or []:
            iid = str(r.get("item_id") or "")
            if not iid:
                continue
            # Merge — later buckets overwrite, which is fine; the same rows
            # show up across buckets with consistent counters.
            idx.setdefault(iid, {}).update({
                "impressions": int(r.get("impressions", 0) or 0),
                "search_impressions": int(r.get("search_impressions", 0) or 0),
                "ctr": float(r.get("ctr", 0.0) or 0.0),
            })
    return idx


def _index_sold_recent(raw: Any) -> set[str]:
    """Set of item_ids that had at least one sale in the last 90 days."""
    if not isinstance(raw, list):
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=SOLD_LOOKBACK_DAYS)
    recent: set[str] = set()
    for row in raw:
        iid = str(row.get("item_id") or "")
        if not iid:
            continue
        ts = row.get("sold_date") or row.get("date") or ""
        try:
            # eBay timestamps come back as ISO-8601 with trailing Z.
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if dt >= cutoff:
            recent.add(iid)
    return recent


# ----------------------------------------------------------------------------
# Scoring
# ----------------------------------------------------------------------------

def _filled_specifics_count(spec_row: dict | None) -> int:
    """Count non-empty current_specifics values; ignores generic placeholders."""
    if not spec_row:
        return 0
    current = spec_row.get("current_specifics") or {}
    n = 0
    for v in current.values():
        s = str(v or "").strip()
        if not s:
            continue
        if s.lower() in ("does not apply", "n/a", "unknown", "unbranded"):
            continue
        n += 1
    return n


def _title_is_clean(title: str) -> tuple[bool, str]:
    title = (title or "").strip()
    if not title:
        return False, "empty title"
    if len(title) > TITLE_CHARS_MAX:
        return False, f"{len(title)} chars > {TITLE_CHARS_MAX}"
    hits = FLUFF_RE.findall(title)
    if hits:
        return False, f"fluff: {', '.join(sorted(set(h.lower() for h in hits)))}"
    return True, f"{len(title)} chars, clean"


def _photo_pass(photo_row: dict | None) -> tuple[bool, str]:
    if not photo_row:
        return False, "no photo audit data"
    pc = int(photo_row.get("photo_count", 0) or 0)
    md = int(photo_row.get("max_dimension", 0) or 0)
    if pc >= PHOTO_COUNT_MIN and md >= PHOTO_DIM_MIN:
        return True, f"{pc} pics @ {md}px"
    return False, f"{pc} pics @ {md or '??'}px (need >={PHOTO_COUNT_MIN}/{PHOTO_DIM_MIN})"


def _impressions_median(perf_idx: dict[str, dict]) -> float:
    """Median impressions across the cohort — proxy for 'category median'."""
    nums = [r.get("impressions", 0) for r in perf_idx.values() if r.get("impressions", 0) > 0]
    return float(statistics.median(nums)) if nums else 0.0


def _score_one(listing: dict, photo_idx: dict, spec_idx: dict, perf_idx: dict,
               sold_recent: set[str], imp_median: float) -> dict:
    iid = str(listing.get("item_id") or "")
    title = listing.get("title", "") or ""
    listing_type = (listing.get("listing_type") or "").upper()

    photo_row = photo_idx.get(iid)
    spec_row  = spec_idx.get(iid)
    perf_row  = perf_idx.get(iid) or {}

    signals = []  # ordered list of (label, weight, earned, detail)

    # 1. Photos
    ok, det = _photo_pass(photo_row)
    signals.append(("Photos 8+ @ 1600px", W_PHOTOS, W_PHOTOS if ok else 0, det))

    # 2. Specifics
    n_spec = _filled_specifics_count(spec_row)
    ok = n_spec >= SPECIFICS_MIN
    signals.append(("Specifics 10+", W_SPECIFICS, W_SPECIFICS if ok else 0,
                    f"{n_spec} filled"))

    # 3. Title hygiene
    ok, det = _title_is_clean(title)
    signals.append(("Title clean & <=80c", W_TITLE, W_TITLE if ok else 0, det))

    # 4. Impressions vs cohort median
    imp = int(perf_row.get("impressions", 0) or 0)
    ok = imp_median > 0 and imp >= imp_median
    det = f"{imp} imp (median {imp_median:.0f})" if imp_median else "no traffic data"
    signals.append(("Impressions >= median", W_IMPRESSIONS, W_IMPRESSIONS if ok else 0, det))

    # 5. CTR
    ctr = float(perf_row.get("ctr", 0.0) or 0.0)
    ok = ctr >= CTR_MIN_PCT
    signals.append(("CTR >= 0.5%", W_CTR, W_CTR if ok else 0, f"{ctr:.2f}%"))

    # 6. Sold in last 90d
    ok = iid in sold_recent
    signals.append(("Sold <90d", W_SOLD, W_SOLD if ok else 0,
                    "yes" if ok else "no recent sale"))

    # 7. Best Offer eligible (proxy: fixed-price listings can take offers;
    # Auction listings can't, so they forfeit this signal by design.)
    ok = listing_type and listing_type != "AUCTION"
    signals.append(("Best Offer eligible", W_BEST_OFFER, W_BEST_OFFER if ok else 0,
                    listing_type or "?"))

    total = sum(s[2] for s in signals)
    bucket = "green" if total >= GREEN_AT else ("yellow" if total >= YELLOW_AT else "red")

    try:
        price = float(listing.get("price") or 0.0)
    except (ValueError, TypeError):
        price = 0.0

    return {
        "item_id":      iid,
        "title":        title,
        "url":          listing.get("url", ""),
        "pic":          listing.get("pic", ""),
        "price":        price,
        "listing_type": listing.get("listing_type", ""),
        "score":        total,
        "bucket":       bucket,
        "signals": [
            {"label": s[0], "weight": s[1], "earned": s[2], "detail": s[3]}
            for s in signals
        ],
    }


# ----------------------------------------------------------------------------
# Plan assembly
# ----------------------------------------------------------------------------

def build_plan() -> dict:
    listings = _index_listings(_load_json(SNAPSHOT_PATH, []))
    photo_idx = _index_photos(_load_json(PHOTO_PATH, {}))
    spec_idx  = _index_specifics(_load_json(SPECIFICS_PATH, {}))
    perf_idx  = _index_perf(_load_json(PERF_PATH, {}))
    sold_recent = _index_sold_recent(_load_json(SOLD_PATH, []))
    imp_median = _impressions_median(perf_idx)

    rows = [_score_one(l, photo_idx, spec_idx, perf_idx, sold_recent, imp_median)
            for l in listings if l.get("item_id")]

    # Day-over-day delta vs prior snapshot
    prior = _load_json(PRIOR_SNAPSHOT, {})
    prior_scores: dict[str, int] = {}
    if isinstance(prior, dict):
        for r in prior.get("rows", []):
            prior_scores[str(r.get("item_id"))] = int(r.get("score", 0))

    for r in rows:
        prev = prior_scores.get(r["item_id"])
        r["prev_score"] = prev
        r["delta"]      = (r["score"] - prev) if prev is not None else None

    rows.sort(key=lambda r: (r["score"], -r["price"]))

    counts = {"green": 0, "yellow": 0, "red": 0}
    for r in rows:
        counts[r["bucket"]] += 1

    avg = round(statistics.mean(r["score"] for r in rows), 1) if rows else 0.0
    movers = [r for r in rows if r["delta"] is not None]
    movers.sort(key=lambda r: abs(r["delta"]), reverse=True)
    biggest_mover = movers[0] if movers else None

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total":          len(rows),
            "green":          counts["green"],
            "yellow":         counts["yellow"],
            "red":            counts["red"],
            "avg_score":      avg,
            "impressions_median": imp_median,
            "biggest_mover":  {
                "item_id": biggest_mover["item_id"],
                "title":   biggest_mover["title"],
                "delta":   biggest_mover["delta"],
                "score":   biggest_mover["score"],
            } if biggest_mover else None,
        },
        "rows": rows,
    }


def write_snapshot(plan: dict) -> None:
    """Trimmed copy used as the baseline for the next run's delta."""
    trimmed = {
        "generated_at": plan["generated_at"],
        "rows": [{"item_id": r["item_id"], "score": r["score"], "bucket": r["bucket"]}
                 for r in plan["rows"]],
    }
    PRIOR_SNAPSHOT.parent.mkdir(exist_ok=True)
    PRIOR_SNAPSHOT.write_text(json.dumps(trimmed, indent=2))


# ----------------------------------------------------------------------------
# Report
# ----------------------------------------------------------------------------

def _delta_html(delta: int | None) -> str:
    if delta is None:
        return '<span class="cas-delta cas-delta-new">new</span>'
    if delta > 0:
        return f'<span class="cas-delta cas-delta-up">&#9650; +{delta}</span>'
    if delta < 0:
        return f'<span class="cas-delta cas-delta-down">&#9660; {delta}</span>'
    return '<span class="cas-delta cas-delta-flat">&#8210; 0</span>'


def _bucket_chip(bucket: str, score: int) -> str:
    return f'<span class="cas-chip cas-chip-{bucket}">{score}</span>'


def _signal_pills(signals: list[dict]) -> str:
    pills = []
    for s in signals:
        cls = "on" if s["earned"] else "off"
        pills.append(
            f'<span class="cas-pill cas-pill-{cls}" title="{html.escape(s["detail"])}">'
            f'{html.escape(s["label"])}</span>'
        )
    return "".join(pills)


def _row_html(r: dict) -> str:
    iid = html.escape(r["item_id"])
    title = html.escape(r["title"])
    pic = html.escape(r.get("pic") or "")
    url = html.escape(r.get("url") or "#")
    thumb = (f'<img src="{pic}" alt="" loading="lazy">'
             if pic else '<div class="cas-thumb-empty"></div>')
    fix_links = (f'<a href="photo_upload.html" class="cas-fix">photos</a> '
                 f'<a href="{url}" target="_blank" rel="noopener" class="cas-fix">listing</a>')
    return (
        f'<tr class="cas-row cas-row-{r["bucket"]}" '
        f'data-score="{r["score"]}" data-price="{r["price"]:.2f}" data-delta="{r["delta"] or 0}">'
        f'<td class="cas-thumb">{thumb}</td>'
        f'<td class="cas-item"><a href="{url}" target="_blank" rel="noopener">'
        f'<span class="cas-title">{title}</span></a>'
        f'<span class="cas-iid">{iid} · ${r["price"]:.2f}</span></td>'
        f'<td class="cas-score-cell">{_bucket_chip(r["bucket"], r["score"])}</td>'
        f'<td class="cas-delta-cell">{_delta_html(r["delta"])}</td>'
        f'<td class="cas-signals">{_signal_pills(r["signals"])}</td>'
        f'<td class="cas-actions">{fix_links}</td>'
        f'</tr>'
    )


def _kpi(cls: str, n: str, label: str, foot: str) -> str:
    return (f'<div class="sh-kpi cas-kpi-{cls}"><div class="sh-kpi-n">{n}</div>'
            f'<div class="sh-kpi-l">{label}</div>'
            f'<div class="sh-kpi-foot">{foot}</div></div>')


def build_report(plan: dict) -> Path:
    s = plan["summary"]
    rows = plan["rows"]
    run_ts = plan["generated_at"]

    mover = s.get("biggest_mover")
    mover_n = (f'{mover["delta"]:+d}' if mover and mover["delta"] is not None else "—")
    mover_foot = (html.escape(mover["title"][:60]) if mover else "no prior snapshot yet")

    kpis = (
        _kpi("green",  str(s["green"]),  "Green",  f"&ge;{GREEN_AT} · ranking strong")
        + _kpi("yellow", str(s["yellow"]), "Yellow", f"{YELLOW_AT}-{GREEN_AT - 1} · optimizable")
        + _kpi("red",    str(s["red"]),    "Red",    f"&lt;{YELLOW_AT} · rescue")
        + _kpi("avg",    f'{s["avg_score"]}',         "Avg score", f"{s['total']} listings scored")
        + _kpi("mover",  mover_n, "Biggest mover", mover_foot)
    )

    red_rows = [r for r in rows if r["bucket"] == "red"]
    # Top 5 RED listings by price (highest-margin rescue candidates).
    red_rescue = sorted(red_rows, key=lambda r: r["price"], reverse=True)[:5]
    rescue_html = "".join(_row_html(r) for r in red_rescue) or (
        '<tr><td colspan="6" class="cas-empty">No RED listings — every active listing scored '
        f'{YELLOW_AT}+.</td></tr>')

    body_rows = "".join(_row_html(r) for r in rows) or (
        '<tr><td colspan="6" class="cas-empty">No active listings scored. '
        'Run promote.py to refresh output/listings_snapshot.json.</td></tr>')

    table_head = (
        '<thead><tr><th></th><th>Listing</th>'
        '<th class="cas-sortable" data-sort="score">Score</th>'
        '<th class="cas-sortable" data-sort="delta">Delta</th>'
        '<th>Signals</th><th>Fix</th></tr></thead>')

    body = (
        f'<section class="hero"><h1>Cassini Health Score</h1>'
        f'<p class="sub">Last run: <code>{html.escape(run_ts)}</code> · '
        f'synthesized from 7 ranking signals across <strong>{s["total"]}</strong> active listings.</p>'
        f'<div class="sh-kpis">{kpis}</div>'
        f'<p class="sh-hint">No public "Cassini score" exists — this is a synthesis of '
        f'photos, item-specifics, title hygiene, impressions, CTR, recent sales, and '
        f'offer eligibility. Move RED &rarr; YELLOW first; YELLOW &rarr; GREEN compounds.</p></section>'
        f'<section class="sh-section"><div class="sh-section-head">'
        f'<h2>Worst rescue candidates</h2><span class="sh-count">top 5 RED by price</span></div>'
        f'<p class="sh-hint">Highest-margin RED listings — fix these first. '
        f'Each $1 of impressions lift here outweighs 10x on a low-margin card.</p>'
        f'<div class="cas-tbl-wrap"><table class="sh-tbl">{table_head}'
        f'<tbody>{rescue_html}</tbody></table></div></section>'
        f'<section class="sh-section"><div class="sh-section-head">'
        f'<h2>All listings</h2><span class="sh-count">{len(rows)} scored, lowest first</span></div>'
        f'<div class="cas-tbl-wrap"><table class="sh-tbl" id="cas-all">{table_head}'
        f'<tbody>{body_rows}</tbody></table></div></section>'
    )

    extra_css = "<style>" + (
        ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
        ".sh-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:22px 0 28px}"
        ".sh-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}"
        ".sh-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}"
        ".sh-kpi-n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1}"
        ".sh-kpi-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}"
        ".sh-kpi-foot{color:var(--text-dim);font-size:11px;margin-top:8px;border-top:1px dashed var(--border);padding-top:8px}"
        ".cas-kpi-green::before{background:var(--success)}.cas-kpi-green .sh-kpi-n{color:var(--success)}"
        ".cas-kpi-yellow::before{background:var(--warning)}.cas-kpi-yellow .sh-kpi-n{color:var(--warning)}"
        ".cas-kpi-red::before{background:var(--danger)}.cas-kpi-red .sh-kpi-n{color:var(--danger)}"
        ".sh-section{margin:36px 0}.sh-section-head{display:flex;align-items:baseline;gap:14px;flex-wrap:wrap;margin-bottom:14px}"
        ".sh-section-head h2{margin:0;font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.02em}"
        ".sh-count{color:var(--text-muted);font-weight:400;font-size:18px;margin-left:6px}.sh-hint{color:var(--text-muted);font-size:13px}"
        ".cas-tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border)}"
        ".sh-tbl{width:100%;border-collapse:collapse;font-size:13px;background:var(--surface)}"
        ".sh-tbl th,.sh-tbl td{padding:10px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:middle}"
        ".sh-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
        ".sh-tbl tr:last-child td{border-bottom:none}.sh-tbl tr:hover td{background:var(--surface-2)}"
        ".cas-sortable{cursor:pointer;user-select:none}.cas-sortable:hover{color:var(--gold)}"
        ".cas-thumb img{width:48px;height:48px;object-fit:cover;border-radius:4px;display:block}.cas-thumb-empty{width:48px;height:48px;background:var(--surface-2);border-radius:4px}"
        ".cas-item a{text-decoration:none;color:var(--text)}.cas-item a:hover .cas-title{color:var(--gold)}.cas-title{display:block}"
        ".cas-iid{display:block;color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px}"
        ".cas-chip{display:inline-block;padding:5px 10px;border-radius:4px;font-weight:700;font-family:'JetBrains Mono',monospace;font-size:13px;min-width:36px;text-align:center}"
        ".cas-chip-green{background:var(--success);color:#fff}.cas-chip-yellow{background:var(--warning);color:#1a1a1a}.cas-chip-red{background:var(--danger);color:#fff}"
        ".cas-row-red td{background:linear-gradient(to right,rgba(220,60,60,.06),transparent)}.cas-row-yellow td{background:linear-gradient(to right,rgba(220,170,60,.04),transparent)}"
        ".cas-delta{font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700}.cas-delta-up{color:var(--success)}.cas-delta-down{color:var(--danger)}"
        ".cas-delta-flat{color:var(--text-dim)}.cas-delta-new{color:var(--text-muted);font-style:italic;font-weight:400}"
        ".cas-pill{display:inline-block;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:.04em;margin:1px 2px 1px 0;border:1px solid var(--border)}"
        ".cas-pill-on{background:rgba(60,180,90,.12);color:var(--success);border-color:rgba(60,180,90,.3)}.cas-pill-off{background:transparent;color:var(--text-dim);opacity:.55}"
        ".cas-actions{white-space:nowrap}.cas-fix{display:inline-block;padding:3px 8px;margin-right:4px;border:1px solid var(--border);border-radius:4px;color:var(--gold);text-decoration:none;font-size:11px}"
        ".cas-fix:hover{background:var(--gold);color:#1a1a1a}.cas-empty{color:var(--text-muted);padding:20px;text-align:center}"
    ) + "</style>"

    sort_js = (
        "<script>(function(){var t=document.getElementById('cas-all');if(!t)return;"
        "var b=t.querySelector('tbody');t.querySelectorAll('.cas-sortable').forEach(function(th){"
        "var k=th.dataset.sort,a=true;th.addEventListener('click',function(){"
        "var r=Array.prototype.slice.call(b.querySelectorAll('tr'));"
        "r.sort(function(x,y){var xv=parseFloat(x.dataset[k]||0),yv=parseFloat(y.dataset[k]||0);"
        "return a?xv-yv:yv-xv;});a=!a;r.forEach(function(z){b.appendChild(z);});});});})();</script>"
    )

    html_doc = promote.html_shell(
        f"Cassini Health Score · {promote.SELLER_NAME}",
        body,
        extra_head=extra_css + sort_js,
        active_page="cassini.html",
    )
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html_doc, encoding="utf-8")
    return REPORT_PATH


# ----------------------------------------------------------------------------
# Entry point
# ----------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="Synthesize a per-listing Cassini health score.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild docs/cassini.html from output/cassini_score_plan.json.")
    args = ap.parse_args()

    if args.report_only and PLAN_PATH.exists():
        plan = json.loads(PLAN_PATH.read_text())
        path = build_report(plan)
        print(f"  Report: {path}")
        return 0

    plan = build_plan()
    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2))
    write_snapshot(plan)

    s = plan["summary"]
    print(f"\n  Cassini score: green={s['green']}  yellow={s['yellow']}  "
          f"red={s['red']}  avg={s['avg_score']}  (n={s['total']})")
    if s.get("biggest_mover"):
        m = s["biggest_mover"]
        print(f"  Biggest mover: {m['delta']:+d} -> {m['score']} · "
              f"{m['item_id']} {m['title'][:60]}")
    else:
        print("  Biggest mover: (no prior snapshot — baseline established)")

    red_rescue = sorted([r for r in plan["rows"] if r["bucket"] == "red"],
                        key=lambda r: r["price"], reverse=True)[:3]
    if red_rescue:
        print("\n  Top 3 RED rescue candidates (by price):")
        for r in red_rescue:
            print(f"    ${r['price']:>6.2f}  score={r['score']:>2}  "
                  f"{r['item_id']}  {r['title'][:55]}")

    path = build_report(plan)
    print(f"\n  Report: {path}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Snap:   {PRIOR_SNAPSHOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
