"""dashboard_agent.py — JC's personal Harpua2001 dashboard.

Replaces the old buyer-facing storefront (never used — zero customer
traffic) and the old seller.html / admin report fleet (torn down 2026-08-06)
with one page answering two questions: what's been selling, and what should
I buy next. Admin-gated, dark theme, wired into promote.html_shell for
visual consistency with the rest of the site.

Reads:
    output/sales_trends.json       (sales_trends_agent.py — run first)
    output/resale_flips_plan.json  (resale_flips_agent.py — refresh by hand;
                                     hits live eBay Browse API so it isn't
                                     re-run on every promote.py cycle)
    output/listings_snapshot.json  (current active inventory, for restock signal)

Writes:
    docs/dashboard.html

Usage:
    python3 dashboard_agent.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import promote
import sales_trends_agent

REPO       = Path(__file__).parent
OUTPUT_DIR = REPO / "output"
TRENDS_PATH = OUTPUT_DIR / "sales_trends.json"
FLIPS_PATH  = OUTPUT_DIR / "resale_flips_plan.json"
SNAPSHOT_PATH = OUTPUT_DIR / "listings_snapshot.json"
OUT = REPO / "docs" / "dashboard.html"

# Quick-buy rule thresholds (JC's rule of thumb, carried over from the old
# seller.html Buy Radar).
MIN_NET_PROFIT = 15.0
MIN_VELOCITY_30D = 10
RESTOCK_SOLD_MIN = 5      # a set needs at least this many sales to count as "proven"
RESTOCK_ACTIVE_MAX = 3    # ...and this few active listings to flag as low stock


def _load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return default


def _money(x) -> str:
    return f"${x:,.2f}"


def _esc(s) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _load_active_listings() -> list[dict]:
    raw = _load_json(SNAPSHOT_PATH, [])
    if isinstance(raw, dict):
        return raw.get("listings", [])
    return raw if isinstance(raw, list) else []


def _restock_signals(trends: dict, listings: list[dict]) -> list[dict]:
    """Sets that sell well but are running low in active inventory."""
    active_by_set: dict[str, int] = {}
    for l in listings:
        set_name = sales_trends_agent.brand_of(l.get("title", "") or "")
        active_by_set[set_name] = active_by_set.get(set_name, 0) + 1

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
    return f"""
    <section class="dash-kpis">
      <div class="stat-card"><div class="num">{_money(t.get('total_revenue', 0))}</div><div class="lbl">Total revenue</div></div>
      <div class="stat-card"><div class="num">{t.get('cards_sold', 0)}</div><div class="lbl">Cards sold</div></div>
      <div class="stat-card"><div class="num">{_money(t.get('avg_sale', 0))}</div><div class="lbl">Avg sale</div></div>
      <div class="stat-card"><div class="num">{_money(t.get('median_sale', 0))}</div><div class="lbl">Median sale</div></div>
      <div class="stat-card"><div class="num">{_money(t.get('revenue_per_week', 0))}</div><div class="lbl">Rev / week</div></div>
      <div class="stat-card"><div class="num">{_esc(t.get('best_week', '—'))}</div><div class="lbl">Best week</div></div>
    </section>"""


def _selling_section_html(t: dict) -> str:
    top_rows = "\n".join(
        f'<tr><td class="rank">{i+1}</td>'
        f'<td><a href="{_esc(s["url"])}" target="_blank" rel="noopener">{_esc(s["title"][:74])}</a></td>'
        f'<td><span class="chip">{_esc(s["set"])}</span></td>'
        f'<td class="num">{_money(s["price"])}</td>'
        f'<td class="dt">{datetime.fromisoformat(s["date"]).strftime("%b %-d")}</td></tr>'
        for i, s in enumerate(t.get("top_sales", []))
    ) or '<tr><td colspan="5" class="muted">No sales yet</td></tr>'

    set_rows = "\n".join(
        f'<tr><td>{_esc(r["set"])}</td><td class="num">{r["sold"]}</td>'
        f'<td class="num">{_money(r["revenue"])}</td><td class="num">{_money(r["avg"])}</td>'
        f'<td class="num">{r["pct_of_revenue"]:.0f}%</td></tr>'
        for r in t.get("by_set", [])
    ) or '<tr><td colspan="5" class="muted">No sales yet</td></tr>'

    buyer_rows = "\n".join(
        f'<tr><td>{_esc(b["buyer"])}</td><td class="num">{b["orders"]}</td><td class="num">{_money(b["spend"])}</td></tr>'
        for b in t.get("repeat_buyers", [])
    ) or '<tr><td colspan="3" class="muted">No repeat buyers yet</td></tr>'

    span = f'{t.get("span_days", 0)} days' if t.get("span_days") else "—"
    return f"""
    <section class="panel">
      <h2>Revenue over time <span class="muted">(weekly &middot; {span})</span></h2>
      <canvas id="revChart" height="120"></canvas>
    </section>
    <div class="dash-two">
      <section class="panel">
        <h2>What's selling &mdash; by set</h2>
        <canvas id="setChart" height="200"></canvas>
      </section>
      <section class="panel">
        <h2>Price-band mix</h2>
        <canvas id="bandChart" height="200"></canvas>
      </section>
    </div>
    <section class="panel">
      <h2>Sales by set</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>Set</th><th class="num">Sold</th><th class="num">Revenue</th><th class="num">Avg</th><th class="num">% rev</th></tr></thead>
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
        <h2 style="margin-top:22px">When buyers buy</h2>
        <canvas id="dowChart" height="120"></canvas>
      </section>
    </div>"""


def _buy_section_html(flips_plan: dict | None, restock: list[dict]) -> str:
    flips_generated = ""
    flip_rows = ""
    if flips_plan:
        flips_generated = flips_plan.get("generated_at", "")
        candidates = flips_plan.get("flips", [])
        for f in candidates[:40]:
            meets_rule = (f.get("net_profit", 0) >= MIN_NET_PROFIT
                          and f.get("velocity_30d", 0) >= MIN_VELOCITY_30D
                          and not f.get("warnings"))
            warn_html = "".join(f'<span class="tag tag-warn">{_esc(w)}</span>' for w in f.get("warnings", []))
            flip_rows += (
                f'<tr class="{"buy-yes" if meets_rule else ""}">'
                f'<td><a href="{_esc(f.get("url",""))}" target="_blank" rel="noopener">{_esc((f.get("title") or "")[:70])}</a></td>'
                f'<td class="num">{_money(f.get("asking", 0))}</td>'
                f'<td class="num">{_money(f.get("resale", 0))}</td>'
                f'<td class="num {"good" if f.get("net_profit",0) > 0 else "bad"}">{_money(f.get("net_profit", 0))}</td>'
                f'<td class="num">{f.get("velocity_30d", 0)}/mo</td>'
                f'<td>{warn_html or "&mdash;"}</td>'
                f'<td>{"<span class=\'tag tag-gold\'>BUY</span>" if meets_rule else ""}</td>'
                f'</tr>'
            )
    flip_rows = flip_rows or '<tr><td colspan="7" class="muted">No cached flip data — run <code>python3 resale_flips_agent.py</code> to refresh.</td></tr>'

    restock_rows = "\n".join(
        f'<tr><td>{_esc(r["set"])}</td><td class="num">{r["sold_90d_or_alltime"]}</td>'
        f'<td class="num">{_money(r["revenue"])}</td><td class="num">{_money(r["avg_sale"])}</td>'
        f'<td class="num">{r["active_now"]}</td></tr>'
        for r in restock
    ) or '<tr><td colspan="5" class="muted">Nothing flagged — inventory keeping pace with sales.</td></tr>'

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
        <span class="muted">{f"cached {_esc(flips_generated)}" if flips_generated else "no data yet"}</span>
      </div>
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
.dash-head h1 { font-family: 'Fraunces', serif; font-size: 34px; margin: 0 0 2px; }
.dash-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin: 18px 0 24px; }
.dash-kpis .stat-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }
.dash-kpis .num { font-family: 'JetBrains Mono', monospace; font-size: 19px; font-weight: 700; color: var(--gold); }
.dash-kpis .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-dim); margin-top: 4px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 18px; }
.panel h2 { font-size: 16px; margin: 0 0 14px; }
.section-header { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.dash-two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th.num, td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
td.rank { color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
td.dt { color: var(--text-dim); white-space: nowrap; }
.chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.muted { color: var(--text-dim); }
.good { color: var(--success, #7fc77a); }
.bad { color: var(--danger, #e07b6f); }
.tag { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); margin-right:4px; }
.tag-gold { background: rgba(201,165,66,.15); color: var(--gold); font-weight:700; }
.tag-warn { background: rgba(224,123,111,.12); color: var(--danger, #e07b6f); }
tr.buy-yes { background: rgba(201,165,66,.05); }
.son-rules { margin: 0 0 14px; }
.son-rules summary { cursor: pointer; font-size: 13px; color: var(--text-dim); }
.son-rules-body { font-size: 13px; margin-top: 8px; color: var(--text-muted); }
.son-rules-body .skip { color: var(--danger, #e07b6f); }
@media (max-width: 820px) { .dash-kpis { grid-template-columns: repeat(2, 1fr); } .dash-two { grid-template-columns: 1fr; } }
</style>"""


def _js(payload: dict) -> str:
    return f"""
<script>window.__DASH = {json.dumps(payload)};</script>
<script>
(function(){{
  const S = window.__DASH; if(!S || !window.Chart) return;
  const css = getComputedStyle(document.documentElement);
  const gold = css.getPropertyValue('--gold').trim() || '#d4af37';
  const dim  = css.getPropertyValue('--text-dim').trim() || '#9aa';
  const grid = 'rgba(255,255,255,.06)';
  Chart.defaults.color = dim; Chart.defaults.font.family = "'Familjen Grotesk', sans-serif";
  const money = v => '$' + Number(v).toLocaleString(undefined,{{maximumFractionDigits:0}});

  new Chart(document.getElementById('revChart'), {{
    data: {{ labels: S.weekLabels, datasets: [
      {{ type:'bar', label:'Revenue', data:S.weekRev, backgroundColor:gold, borderRadius:4, yAxisID:'y', order:2 }},
      {{ type:'line', label:'Cards sold', data:S.weekCnt, borderColor:'#7db7ff', backgroundColor:'#7db7ff',
        tension:.3, yAxisID:'y1', order:1, pointRadius:2 }} ] }},
    options: {{ responsive:true, maintainAspectRatio:false, interaction:{{mode:'index',intersect:false}},
      plugins:{{ legend:{{labels:{{boxWidth:12}}}}, tooltip:{{ callbacks:{{ label:c=> c.dataset.yAxisID==='y' ? ' '+money(c.parsed.y) : ' '+c.parsed.y+' cards' }} }} }},
      scales:{{ y:{{position:'left',grid:{{color:grid}},ticks:{{callback:money}}}}, y1:{{position:'right',grid:{{display:false}}}}, x:{{grid:{{display:false}}}} }} }}
  }});

  new Chart(document.getElementById('setChart'), {{
    type:'bar', data:{{ labels:S.brandLabels, datasets:[{{ label:'Revenue', data:S.brandRev, backgroundColor:gold, borderRadius:4 }}] }},
    options:{{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}},
      tooltip:{{callbacks:{{label:c=>' '+money(c.parsed.x)+' &middot; '+S.brandCnt[c.dataIndex]+' sold'}}}}}},
      scales:{{ x:{{grid:{{color:grid}},ticks:{{callback:money}}}}, y:{{grid:{{display:false}}}} }} }}
  }});

  const palette = ['#5b8def','#49b675','#e0b13a','#e0773a','#d4553a','#a05ad4'];
  new Chart(document.getElementById('bandChart'), {{
    type:'doughnut', data:{{ labels:S.bandLabels, datasets:[{{ data:S.bandCnt, backgroundColor:palette, borderWidth:0 }}] }},
    options:{{ responsive:true, maintainAspectRatio:false, cutout:'58%', plugins:{{ legend:{{position:'right',labels:{{boxWidth:12}}}} }} }}
  }});

  new Chart(document.getElementById('dowChart'), {{
    type:'bar', data:{{ labels:S.dowNames, datasets:[{{ data:S.dowCnt, backgroundColor:'#5b8def', borderRadius:4 }}] }},
    options:{{ responsive:true, maintainAspectRatio:false, plugins:{{legend:{{display:false}}}},
      scales:{{ y:{{grid:{{color:grid}}}}, x:{{grid:{{display:false}}}} }} }}
  }});
}})();
</script>"""


def build() -> Path:
    trends = _load_json(TRENDS_PATH, {})
    flips_plan = _load_json(FLIPS_PATH, None)
    listings = _load_active_listings()
    restock = _restock_signals(trends, listings) if trends else []

    now = datetime.now(timezone.utc)
    hero = f"""
    <header class="dash-head">
      <h1>Dashboard</h1>
      <p class="muted">Updated {now.strftime('%b %-d, %Y &middot; %H:%M UTC')}</p>
    </header>"""

    body = (
        '<main class="dash-wrap">' + hero
        + (_kpi_html(trends) if trends else '<p class="muted">No sales_trends.json yet — run <code>python3 sales_trends_agent.py</code>.</p>')
        + (_selling_section_html(trends) if trends else "")
        + _buy_section_html(flips_plan, restock)
        + "</main>"
        + _js(trends if trends else {})
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
