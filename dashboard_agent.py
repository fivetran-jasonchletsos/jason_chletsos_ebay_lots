"""dashboard_agent.py — JC's personal Harpua2001 dashboard.

Replaces the old buyer-facing storefront (never used — zero customer
traffic) and the old seller.html / admin report fleet (torn down 2026-08-06)
with one page answering two questions: what's been selling, and what should
I buy next. Admin-gated, light data-tool theme, wired into promote.html_shell
for the OAuth gate + PWA boilerplate.

Charts are inline SVG via chart_helpers.py (Tufte redesign, 2026-08-09):
no chart-JS dependency, no legends/tooltips to hover for a number you
should just be able to read, no pie/doughnut (angle judgment is worse than
length judgment), a sparkline per set showing its trend instead of one big
combined line. High data-ink ratio: hairline rules, no card shadows, no
decoration that isn't carrying a value.

Reads (falls back to disk when the caller doesn't already have these in
memory — see build()'s optional params):
    output/sales_trends.json       (sales_trends_agent.py)
    output/resale_flips_plan.json  (resale_flips_agent.py — refresh by hand;
                                     hits live eBay Browse API so it isn't
                                     re-run on every promote.py cycle)
    output/listings_snapshot.json  (current active inventory, for restock signal)
    decisions_log.json             (editorial conclusions from a specific
                                     analysis session, e.g. a multi-agent
                                     panel's recommendation -- hand-edited,
                                     not recomputed; see _load_decisions())

The "Insights" section (2026-08-11) surfaces both: auto-computed
observations that re-derive fresh from the data on every build
(_compute_insights -- revenue trend, concentration risk, dead stock,
restock signal, stale Buy Radar data, best sales day), and the decisions
log's dated conclusions, so JC gets told things instead of having to
read every chart and infer them himself.

Writes:
    docs/dashboard.html

Usage:
    python3 dashboard_agent.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import chart_helpers
import promote
import sales_trends_agent
import snapshot_store

REPO       = Path(__file__).parent
OUTPUT_DIR = REPO / "output"
TRENDS_PATH = OUTPUT_DIR / "sales_trends.json"
FLIPS_PATH  = OUTPUT_DIR / "resale_flips_plan.json"
<<<<<<< Updated upstream
DECISIONS_PATH = REPO / "decisions_log.json"
=======
>>>>>>> Stashed changes
OUT = REPO / "docs" / "dashboard.html"

# Insight thresholds -- tuned to flag things worth JC's attention, not fire
# on every minor wiggle in the data.
REV_TREND_PCT = 15         # week-over-week revenue swing worth calling out
CONCENTRATION_PCT = 25     # a set carrying this much of total revenue is a concentration risk
DEAD_STOCK_MIN_ACTIVE = 20 # active listings in a set before "few sales" becomes a real signal
DEAD_STOCK_MAX_SOLD = 1    # sales in-window at/below this count as "not moving"

# Quick-buy rule thresholds (JC's rule of thumb, carried over from the old
# seller.html Buy Radar).
MIN_NET_PROFIT = 15.0
MIN_VELOCITY_30D = 10
RESTOCK_SOLD_MIN = 5      # a set needs at least this many sales to count as "proven"
RESTOCK_ACTIVE_MAX = 3    # ...and this few active listings to flag as low stock

_BUY_BADGE = '<span class="tag tag-gold">BUY</span>'

# Sequential indigo scale for the price-band bar — Tufte tolerates an ordered
# scale (it encodes the $0-2 -> $50+ ordering); it's categorical rainbow
# coloring he objected to.
_BAND_SCALE = ["#e0e7ff", "#c7d2fe", "#a5b4fc", "#818cf8", "#6366f1", "#4338ca"]


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _money(x) -> str:
    return f"${x:,.2f}"


def _esc(s) -> str:
    # Escapes quotes too (not just &/</>) because this is used inside
    # double-quoted HTML attributes (href="{_esc(url)}") as well as text
    # nodes — an unescaped `"` in an attribute value lets attacker-influenced
    # data (eBay listing/query text) break out and inject markup.
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;").replace("'", "&#39;"))


def _rows_or(rows_html: str, colspan: int, empty_msg: str) -> str:
    return rows_html or f'<tr><td colspan="{colspan}" class="muted">{empty_msg}</td></tr>'


def _active_by_set(listings: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for l in listings:
        set_name = sales_trends_agent.brand_of(l.get("title", "") or "")
        counts[set_name] = counts.get(set_name, 0) + 1
    return counts


def _restock_signals(trends: dict, active_by_set: dict[str, int]) -> list[dict]:
    """Sets that sell well but are running low in active inventory."""
    signals = []
    for row in trends.get("by_set", []):
        set_name = row["set"]
        if row["sold"] < RESTOCK_SOLD_MIN:
            continue
        active = active_by_set.get(set_name, 0)
        if active <= RESTOCK_ACTIVE_MAX:
            signals.append({
                "set": set_name,
                "sold_90d_or_alltime": row["sold"],
                "revenue": row["revenue"],
                "avg_sale": row["avg"],
                "active_now": active,
            })
    signals.sort(key=lambda r: -r["sold_90d_or_alltime"])
    return signals


def _kpi_html(t: dict) -> str:
    """A dense row of labeled numbers — no cards, no gradients, no icons.
    Tufte: the numbers themselves are the graphic."""
    stats = [
        (_money(t.get("total_revenue", 0)), "Total revenue"),
        (str(t.get("cards_sold", 0)), "Cards sold"),
        (_money(t.get("avg_sale", 0)), "Avg sale"),
        (_money(t.get("median_sale", 0)), "Median sale"),
        (_money(t.get("revenue_per_week", 0)), "Rev / week"),
        (_esc(t.get("best_week", "—")), "Best week"),
    ]
    cells = "".join(
        f'<div class="kpi"><div class="kpi-num">{val}</div><div class="kpi-lbl">{lbl}</div></div>'
        for val, lbl in stats
    )
    return f'<section class="kpi-row">{cells}</section>'
<<<<<<< Updated upstream


def _load_decisions() -> list[dict]:
    """Dated, editorial conclusions from a specific analysis session (e.g. a
    multi-agent panel's recommendation) -- distinct from the auto-computed
    insights below, which just re-read whatever the data says on every
    build. A decision persists until JC (or a future analysis) revisits it;
    it isn't silently recalculated. Newest first."""
    raw = _load_json(DECISIONS_PATH, [])
    return raw if isinstance(raw, list) else []


def _compute_insights(trends: dict, active_by_set: dict[str, int],
                       restock: list[dict], flips_age_days: int | None) -> list[dict]:
    """Deterministic, data-driven observations computed fresh every build --
    the dashboard should tell JC things, not just hand him charts to
    interpret himself. Each rule only fires when its threshold is actually
    crossed, so this stays a short list of things worth reading, not noise."""
    insights: list[dict] = []
    by_set = trends.get("by_set", [])

    # Skip the current, still-in-progress week (its Monday anchor is within
    # the last 7 days) -- comparing a partial week against a full one always
    # looks like a crash regardless of actual trend.
    week_rev = trends.get("weekRev", [])
    week_starts = trends.get("weekStarts", [])
    if week_starts and week_rev and len(week_starts) == len(week_rev):
        try:
            current_monday = datetime.now(timezone.utc) - timedelta(
                days=datetime.now(timezone.utc).weekday())
            if datetime.fromisoformat(week_starts[-1]).replace(tzinfo=timezone.utc) >= current_monday.replace(
                    hour=0, minute=0, second=0, microsecond=0):
                week_rev = week_rev[:-1]
        except ValueError:
            pass
    if len(week_rev) >= 2 and week_rev[-2] > 0:
        pct = (week_rev[-1] - week_rev[-2]) / week_rev[-2] * 100
        if abs(pct) >= REV_TREND_PCT:
            direction = "up" if pct > 0 else "down"
            insights.append({"kind": "trend" if pct > 0 else "warning",
                "text": f"Revenue is {direction} {abs(pct):.0f}% week-over-week (last two complete weeks) "
                        f"({_money(week_rev[-2])} → {_money(week_rev[-1])})."})

    if by_set and by_set[0]["pct_of_revenue"] >= CONCENTRATION_PCT:
        top = by_set[0]
        insights.append({"kind": "concentration",
            "text": f"{_esc(top['set'])} is your single biggest set at {top['pct_of_revenue']:.0f}% "
                    f"of revenue ({_money(top['revenue'])}) — a slowdown there would hit hard."})

    sold_by_set = {r["set"]: r["sold"] for r in by_set}
    dead = sorted(
        ((sn, cnt, sold_by_set.get(sn, 0)) for sn, cnt in active_by_set.items()
         if cnt >= DEAD_STOCK_MIN_ACTIVE and sold_by_set.get(sn, 0) <= DEAD_STOCK_MAX_SOLD),
        key=lambda x: -x[1],
    )
    if dead:
        sn, cnt, sold_cnt = dead[0]
        insights.append({"kind": "dead-stock",
            "text": f"{_esc(sn)} has {cnt} active listings but only {sold_cnt} sale(s) in this "
                     "window — worth a markdown pass or bundling into a lot."})

    if restock:
        r = restock[0]
        insights.append({"kind": "restock",
            "text": f"{len(restock)} set(s) are selling well but low on stock — "
                    f"{_esc(r['set'])} sold {r['sold_90d_or_alltime']}x with only "
                    f"{r['active_now']} active listing(s) right now."})

    if flips_age_days is not None and flips_age_days > STALE_FLIPS_DAYS:
        insights.append({"kind": "stale-data",
            "text": f"Buy Radar listing data is {flips_age_days} days old — refresh with "
                     "<code>python3 resale_flips_agent.py</code> once the Browse API quota resets."})

    dow_names, dow_cnt = trends.get("dowNames", []), trends.get("dowCnt", [])
    if dow_names and dow_cnt and sum(dow_cnt) > 0:
        i = max(range(len(dow_cnt)), key=lambda i: dow_cnt[i])
        insights.append({"kind": "timing",
            "text": f"{dow_names[i]} is your best day for sales historically ({dow_cnt[i]} orders) "
                     "— worth timing new listings or relists around it."})

    return insights


def _insights_html(insights: list[dict], decisions: list[dict]) -> str:
    decision_html = "".join(
        f'<div class="insight insight-decision"><span class="insight-tag">DECISION · {_esc(d.get("date",""))}</span>'
        f'{_esc(d.get("text",""))}</div>'
        for d in decisions[:2]
    )
    auto_html = "".join(
        f'<div class="insight">{i["text"]}</div>'  # text is built from _esc()'d/internal values above
        for i in insights
    )
    body = decision_html + auto_html
    if not body:
        body = '<div class="insight muted">Nothing crossed a threshold this build — that\'s a quiet week, not missing data.</div>'
    return f"""
    <section class="panel insights-panel">
      <h2>Insights</h2>
      {body}
    </section>"""
=======
>>>>>>> Stashed changes


def _selling_section_html(t: dict) -> str:
    top_rows = _rows_or("\n".join(
        f'<tr><td class="rank">{i+1}</td>'
        f'<td><a href="{_esc(s["url"])}" target="_blank" rel="noopener">{_esc(s["title"][:74])}</a></td>'
        f'<td><span class="chip">{_esc(s["set"])}</span></td>'
        f'<td class="num">{_money(s["price"])}</td>'
        f'<td class="dt">{datetime.fromisoformat(s["date"]).strftime("%b %-d")}</td></tr>'
        for i, s in enumerate(t.get("top_sales", []))
    ), 5, "No sales yet")

    set_rows = _rows_or("\n".join(
        f'<tr><td>{_esc(r["set"])}</td><td class="num">{r["sold"]}</td>'
        f'<td class="num">{_money(r["revenue"])}</td><td class="num">{_money(r["avg"])}</td>'
        f'<td class="num">{r["pct_of_revenue"]:.0f}%</td>'
        f'<td class="spark">{chart_helpers.sparkline(r["trend"], width=110, height=28)}</td></tr>'
        for r in t.get("by_set", [])
    ), 6, "No sales yet")

    buyer_rows = _rows_or("\n".join(
        f'<tr><td>{_esc(b["buyer"])}</td><td class="num">{b["orders"]}</td><td class="num">{_money(b["spend"])}</td></tr>'
        for b in t.get("repeat_buyers", [])
    ), 3, "No repeat buyers yet")

    span = f'{t.get("span_days", 0)} days' if t.get("span_days") else "—"

    revenue_chart = chart_helpers.card_wrapper(
        "Revenue over time", f"weekly · {span}",
        chart_helpers.bar_chart_vertical(
            list(zip(t.get("weekLabels", []), t.get("weekRev", []))),
            height=200, y_label="revenue",
        ),
    )
    by_set_chart = chart_helpers.card_wrapper(
        "What's selling", "by set, ranked",
        chart_helpers.bar_chart_horizontal(
            [(label, rev, None) for label, rev in zip(t.get("brandLabels", []), t.get("brandRev", []))],
            value_fmt=_money,
        ),
    )
    band_segments = [
        (label, cnt, _BAND_SCALE[i % len(_BAND_SCALE)])
        for i, (label, cnt) in enumerate(zip(t.get("bandLabels", []), t.get("bandCnt", [])))
    ]
    band_chart = chart_helpers.card_wrapper(
        "Price-band mix", "share of cards sold",
        chart_helpers.stacked_proportion_bar(band_segments),
    )
    dow_chart = chart_helpers.card_wrapper(
        "When buyers buy", "orders by day of week",
        chart_helpers.bar_chart_vertical(
            list(zip(t.get("dowNames", []), t.get("dowCnt", []))),
            height=160, value_fmt=lambda v: str(int(v)), y_label="orders",
        ),
    )

    return f"""
    {revenue_chart}
    <div class="dash-two">
      {by_set_chart}
      {band_chart}
    </div>
    <section class="panel">
      <h2>Sales by set</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Set</th><th class="num">Sold</th><th class="num">Revenue</th><th class="num">Avg</th><th class="num">% rev</th><th>Trend</th></tr></thead>
        <tbody>{set_rows}</tbody>
      </table></div>
    </section>
    <div class="dash-two">
      <section class="panel">
        <h2>Top 15 sales</h2>
        <div class="table-wrap"><table>
          <thead><tr><th>#</th><th>Card</th><th>Set</th><th class="num">Price</th><th>Date</th></tr></thead>
          <tbody>{top_rows}</tbody>
        </table></div>
      </section>
      <section class="panel">
        <h2>Repeat buyers</h2>
        <div class="table-wrap"><table>
          <thead><tr><th>Buyer</th><th class="num">Orders</th><th class="num">Spend</th></tr></thead>
          <tbody>{buyer_rows}</tbody>
        </table></div>
      </section>
    </div>
    {dow_chart}"""
<<<<<<< Updated upstream


STALE_FLIPS_DAYS = 3  # Browse API listing data older than this: prices/availability may be wrong


def _flips_staleness(flips_plan: dict) -> tuple[str, int | None]:
    """(source_generated_at, age_in_days). age is None if we can't tell."""
    # source_generated_at is the listing DATA's age (added 2026-08-10); older
    # cached plans only have generated_at, which is when the script last ran
    # -- not necessarily when the underlying listings were fetched.
    ts = flips_plan.get("source_generated_at") or flips_plan.get("generated_at", "")
    if not ts:
        return "", None
    try:
        parsed = datetime.fromisoformat(ts)
        if parsed.tzinfo is None:
<<<<<<< Updated upstream
            # Defensive: a naive timestamp (e.g. a hand-edited or legacy
            # cache file) would otherwise raise TypeError subtracting from
            # an aware "now" and crash the whole dashboard build.
=======
            # Defensive: a naive timestamp (e.g. a hand-edited or legacy cache
            # file) would otherwise raise TypeError subtracting from an
            # aware "now" and crash the whole dashboard build.
>>>>>>> Stashed changes
            parsed = parsed.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - parsed).days
    except (ValueError, TypeError):
        return ts, None
    return ts, age
=======
>>>>>>> Stashed changes


def _buy_section_html(flips_plan: dict | None, restock: list[dict]) -> str:
    flips_plan = flips_plan or {}
<<<<<<< Updated upstream
    flips_generated, flips_age_days = _flips_staleness(flips_plan)
    is_stale = flips_age_days is not None and flips_age_days > STALE_FLIPS_DAYS

    def _flip_row(f: dict) -> str:
        meets_rule = (not is_stale
                      and f.get("net_profit", 0) >= MIN_NET_PROFIT
=======
    flips_generated = flips_plan.get("generated_at", "")

    def _flip_row(f: dict) -> str:
        meets_rule = (f.get("net_profit", 0) >= MIN_NET_PROFIT
>>>>>>> Stashed changes
                      and f.get("velocity_30d", 0) >= MIN_VELOCITY_30D
                      and not f.get("warnings"))
        warn_html = "".join(f'<span class="tag tag-warn">{_esc(w)}</span>' for w in f.get("warnings", []))
        return (
            f'<tr class="{"buy-yes" if meets_rule else ""}">'
            f'<td><a href="{_esc(f.get("url",""))}" target="_blank" rel="noopener">{_esc((f.get("title") or "")[:70])}</a></td>'
            f'<td class="num">{_money(f.get("asking", 0))}</td>'
            f'<td class="num">{_money(f.get("resale", 0))}</td>'
            f'<td class="num {"good" if f.get("net_profit", 0) > 0 else "bad"}">{_money(f.get("net_profit", 0))}</td>'
            f'<td class="num">{f.get("velocity_30d", 0)}/mo</td>'
            f'<td>{warn_html or "&mdash;"}</td>'
            f'<td>{_BUY_BADGE if meets_rule else ""}</td>'
            f'</tr>'
        )

    flip_rows = _rows_or(
        "\n".join(_flip_row(f) for f in flips_plan.get("flips", [])[:40]),
        7, 'No cached flip data — run <code>python3 resale_flips_agent.py</code> to refresh.',
    )

<<<<<<< Updated upstream
    stale_banner = ""
    if is_stale:
        stale_banner = (
            f'<div class="stale-warn">Listing data is <strong>{flips_age_days} days old</strong> '
            f'(source: {_esc(flips_generated)}) &mdash; the eBay Browse API fetch failed or was '
            f'rate-limited, so this ran on a stale cache. Specific listings below may be sold or '
            f'ended already; treat prices as reference only, not a live buy signal, until you run '
            f'<code>python3 resale_flips_agent.py</code> again successfully.</div>'
        )

=======
>>>>>>> Stashed changes
    restock_rows = _rows_or("\n".join(
        f'<tr><td>{_esc(r["set"])}</td><td class="num">{r["sold_90d_or_alltime"]}</td>'
        f'<td class="num">{_money(r["revenue"])}</td><td class="num">{_money(r["avg_sale"])}</td>'
        f'<td class="num">{r["active_now"]}</td></tr>'
        for r in restock
    ), 5, "Nothing flagged — inventory keeping pace with sales.")

    return f"""
    <section class="panel">
      <div class="section-header">
        <h2>Restock signal</h2>
        <span class="muted">sets that sell but you're low on</span>
      </div>
      <p class="muted" style="margin:0 0 12px">Sets with {RESTOCK_SOLD_MIN}+ sales but {RESTOCK_ACTIVE_MAX} or fewer active listings right now &mdash; go find more of these.</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Set</th><th class="num">Sold</th><th class="num">Revenue</th><th class="num">Avg sale</th><th class="num">Active now</th></tr></thead>
        <tbody>{restock_rows}</tbody>
      </table></div>
    </section>
    <section class="panel">
      <div class="section-header">
        <h2>Buy Radar &mdash; resale flips</h2>
        <span class="muted">{"" if is_stale else (f"fetched {_esc(flips_generated)}" if flips_generated else "no data yet")}</span>
      </div>
      {stale_banner}
      <details class="son-rules" open>
        <summary>Quick-buy rule</summary>
        <div class="son-rules-body">
          <strong>Buy if ALL three:</strong> Net profit ${MIN_NET_PROFIT:.0f}+, sold {MIN_VELOCITY_30D}+ times last 30 days, no warning badges.<br>
          <span class="skip">Skip if any warning badge is showing.</span>
        </div>
      </details>
      <div class="table-wrap"><table>
        <thead><tr><th>Listing</th><th class="num">Asking</th><th class="num">Resale</th><th class="num">Net profit</th><th class="num">Velocity</th><th>Warnings</th><th></th></tr></thead>
        <tbody>{flip_rows}</tbody>
      </table></div>
    </section>"""


_CSS = """
<style>
.dash-wrap { max-width: 1100px; margin: 0 auto; }
.dash-head h1 { font-family: 'Familjen Grotesk', -apple-system, sans-serif; font-weight: 800; font-size: 28px; margin: 0 0 2px; letter-spacing: -0.01em; }
.kpi-row { display: grid; grid-template-columns: repeat(6, 1fr); margin: 18px 0 26px; border-top: 1px solid var(--border); border-bottom: 1px solid var(--border); }
.kpi { padding: 14px 16px; border-left: 1px solid var(--border); }
.kpi:first-child { border-left: none; }
.kpi-num { font-family: 'JetBrains Mono', monospace; font-size: 19px; font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.kpi-lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-dim); margin-top: 3px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 18px 20px; margin-bottom: 16px; }
.panel h2 { font-size: 15px; font-weight: 700; margin: 0 0 12px; }
<<<<<<< Updated upstream
.insights-panel { border-color: var(--border-mid); }
.insight { font-size: 13.5px; line-height: 1.5; padding: 8px 0; border-bottom: 1px solid var(--border); }
.insight:last-child { border-bottom: none; padding-bottom: 0; }
.insight:first-child { padding-top: 0; }
.insight code { font-family: 'JetBrains Mono', monospace; font-size: 12px; background: var(--surface-2); padding: 1px 5px; border-radius: 3px; }
.insight-decision { background: rgba(79,70,229,.04); margin: 0 -20px; padding: 10px 20px; border-bottom: 1px solid var(--border); }
.insight-tag { display: block; font-size: 10px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--gold); margin-bottom: 3px; }
.section-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.dash-two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
/* Grid items default to min-width:auto, so a nested table's min-width:600px
   (promote.py's shared .table-wrap table rule) blows out the track instead of
   being clamped + internally scrolled -- confirmed via headless render: the
   "Top 15 sales"/"Repeat buyers" pair pushed the whole page 274px past a
   375px viewport. min-width:0 lets the grid track win so table-wrap's own
   overflow-x:auto can do its job. */
.dash-two > * { min-width: 0; }
=======
.section-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.dash-two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
>>>>>>> Stashed changes
.ch-card { margin-bottom: 16px !important; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 8px 10px; text-align: left; border-bottom: 1px solid var(--border); }
th { font-weight: 600; color: var(--text-dim); font-size: 11px; text-transform: uppercase; letter-spacing: .03em; }
th.num, td.num { text-align: right; font-family: 'JetBrains Mono', monospace; font-variant-numeric: tabular-nums; }
td.rank { color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
td.dt { color: var(--text-dim); white-space: nowrap; }
td.spark { width: 120px; }
.chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.muted { color: var(--text-dim); }
.good { color: var(--success); }
.bad { color: var(--danger); }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); margin-right:4px; }
.tag-gold { background: rgba(79,70,229,.12); color: var(--gold); font-weight:700; }
.tag-warn { background: rgba(220,38,38,.10); color: var(--danger); }
tr.buy-yes { background: rgba(79,70,229,.05); }
.son-rules { margin: 0 0 14px; }
.son-rules summary { cursor: pointer; font-size: 13px; color: var(--text-dim); }
.son-rules-body { font-size: 13px; margin-top: 8px; color: var(--text-muted); }
.son-rules-body .skip { color: var(--danger); }
<<<<<<< Updated upstream
.stale-warn { background: rgba(220,38,38,.06); border: 1px solid rgba(220,38,38,.25); border-radius: 4px; padding: 10px 14px; font-size: 13px; color: var(--text); margin-bottom: 14px; }
.stale-warn code { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
=======
>>>>>>> Stashed changes
@media (max-width: 820px) { .kpi-row { grid-template-columns: repeat(2, 1fr); } .dash-two { grid-template-columns: 1fr; } }
</style>"""


def build(trends: dict | None = None, listings: list[dict] | None = None) -> Path:
    """Renders docs/dashboard.html.

    trends/listings let a caller that already has this data in memory
    (promote.py, right after fetching/computing it) pass it straight
    through instead of writing-then-re-reading a JSON round trip. Standalone
    use (python3 dashboard_agent.py) leaves both None and loads from disk.
    """
    if trends is None:
        trends = _load_json(TRENDS_PATH, {})
    flips_plan = _load_json(FLIPS_PATH, None)
<<<<<<< Updated upstream
    if listings is None:
        listings = snapshot_store.load()
    active_by_set = _active_by_set(listings)
    restock = _restock_signals(trends, active_by_set)
    _, flips_age_days = _flips_staleness(flips_plan or {})
=======
    if not listings:
        listings = snapshot_store.load()
    restock = _restock_signals(trends, listings)
>>>>>>> Stashed changes

    now = datetime.now(timezone.utc)
    hero = f"""
    <header class="dash-head">
      <h1>Dashboard</h1>
      <p class="muted">Updated {now.strftime('%b %-d, %Y &middot; %H:%M UTC')}</p>
    </header>"""

    insights = _compute_insights(trends, active_by_set, restock, flips_age_days) if trends else []
    decisions = _load_decisions()

    body = (
        '<main class="dash-wrap">' + hero
        + _insights_html(insights, decisions)
        + (_kpi_html(trends) if trends else '<p class="muted">No sales_trends.json yet — run <code>python3 sales_trends_agent.py</code>.</p>')
        + (_selling_section_html(trends) if trends else "")
        + _buy_section_html(flips_plan, restock)
        + "</main>"
    )

    html = promote.html_shell(
        f"Dashboard · {promote.SELLER_NAME}",
        body, extra_head=_CSS, active_page="dashboard.html",
    )
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


def main() -> int:
    sales_trends_agent.main()
    out = build()
    print(f"  Dashboard: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
