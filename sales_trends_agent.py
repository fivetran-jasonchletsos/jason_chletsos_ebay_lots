"""
sales_trends_agent.py — analytics page over all completed sales.

Reads sold_history.json and renders docs/sales_trends.html: headline KPIs,
revenue-over-time, what's selling by set/brand, price-band mix, top sales,
day-of-week pattern, and repeat buyers. Admin-only page; wired into the shared
nav via promote._NAV_ITEMS ("Sales Trends").

Usage: python3 sales_trends_agent.py
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import promote

REPO = Path(__file__).parent
SOLD = REPO / "sold_history.json"
OUT  = REPO / "docs" / "sales_trends.html"

# Ordered brand detection — check multi-word / specific tokens before generic.
BRANDS = [
    ("Pokemon", "Pokemon TCG"),
    ("TCG", "Pokemon TCG"),
    ("Signature Class", "Topps Signature Class"),
    ("Topps Chrome", "Topps Chrome"),
    ("Bowman", "Bowman"),
    ("Select", "Panini Select"),
    ("Optic", "Donruss Optic"),
    ("Mosaic", "Panini Mosaic"),
    ("Phoenix", "Panini Phoenix"),
    ("Contenders", "Panini Contenders"),
    ("Absolute", "Panini Absolute"),
    ("Chronicles", "Panini Chronicles"),
    ("Prestige", "Panini Prestige"),
    ("Rookies and Stars", "Panini Rookies & Stars"),
    ("Rookies & Stars", "Panini Rookies & Stars"),
    ("Icon Collection", "Panini Icon Collection"),
    ("Wild Card", "Wild Card"),
    ("Donruss", "Donruss"),
    ("Prizm", "Panini Prizm"),
    ("Score", "Panini Score"),
    ("Fleer", "Fleer"),
    ("Upper Deck", "Upper Deck"),
    ("Topps", "Topps"),
    ("Panini", "Panini (other)"),
]

BANDS = [("$0–2", 0, 2), ("$2–5", 2, 5), ("$5–10", 5, 10),
         ("$10–25", 10, 25), ("$25–50", 25, 50), ("$50+", 50, 1e9)]


def parse_date(s: str):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def brand_of(title: str) -> str:
    for token, label in BRANDS:
        if token.lower() in title.lower():
            return label
    return "Other"


def band_of(p: float) -> str:
    for label, lo, hi in BANDS:
        if lo <= p < hi:
            return label
    return "Other"


def main() -> None:
    data = json.loads(SOLD.read_text())
    sales = []
    for s in data:
        try:
            price = float(s.get("sale_price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        d = parse_date(s.get("sold_date", ""))
        if price <= 0 or d is None:
            continue
        sales.append({"price": price, "date": d, "title": s.get("title", ""),
                      "buyer": s.get("buyer", ""), "url": s.get("url", ""),
                      "brand": brand_of(s.get("title", ""))})
    sales.sort(key=lambda x: x["date"])

    total = sum(s["price"] for s in sales)
    n = len(sales)
    avg = total / n if n else 0
    med = statistics.median(s["price"] for s in sales) if n else 0
    first, last = (sales[0]["date"], sales[-1]["date"]) if n else (None, None)
    span_days = max(1, (last - first).days) if n else 1

    # revenue + count by ISO week (Mon-anchored)
    by_week_rev: dict[str, float] = defaultdict(float)
    by_week_cnt: dict[str, int] = defaultdict(int)
    for s in sales:
        wk = (s["date"] - __import__("datetime").timedelta(days=s["date"].weekday())).strftime("%Y-%m-%d")
        by_week_rev[wk] += s["price"]
        by_week_cnt[wk] += 1
    weeks = sorted(by_week_rev)
    week_labels = [datetime.strptime(w, "%Y-%m-%d").strftime("%b %-d") for w in weeks]

    # by brand
    brand_rev: dict[str, float] = defaultdict(float)
    brand_cnt: dict[str, int] = defaultdict(int)
    for s in sales:
        brand_rev[s["brand"]] += s["price"]
        brand_cnt[s["brand"]] += 1
    brands_sorted = sorted(brand_rev, key=lambda b: brand_rev[b], reverse=True)

    # price bands
    band_cnt = Counter(band_of(s["price"]) for s in sales)
    band_rev: dict[str, float] = defaultdict(float)
    for s in sales:
        band_rev[band_of(s["price"])] += s["price"]
    band_order = [b[0] for b in BANDS]

    # day-of-week
    dow_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    dow_cnt = [0] * 7
    for s in sales:
        dow_cnt[s["date"].weekday()] += 1

    # top sales
    top = sorted(sales, key=lambda x: x["price"], reverse=True)[:15]

    # buyers
    buyer_spend: dict[str, float] = defaultdict(float)
    buyer_cnt: dict[str, int] = defaultdict(int)
    for s in sales:
        if s["buyer"]:
            buyer_spend[s["buyer"]] += s["price"]
            buyer_cnt[s["buyer"]] += 1
    repeat = sorted([(b, buyer_cnt[b], buyer_spend[b]) for b in buyer_cnt if buyer_cnt[b] > 1],
                    key=lambda x: (-x[1], -x[2]))

    best_week_i = max(range(len(weeks)), key=lambda i: by_week_rev[weeks[i]]) if weeks else None

    payload = {
        "weekLabels": week_labels,
        "weekRev": [round(by_week_rev[w], 2) for w in weeks],
        "weekCnt": [by_week_cnt[w] for w in weeks],
        "brandLabels": brands_sorted,
        "brandRev": [round(brand_rev[b], 2) for b in brands_sorted],
        "brandCnt": [brand_cnt[b] for b in brands_sorted],
        "bandLabels": band_order,
        "bandCnt": [band_cnt.get(b, 0) for b in band_order],
        "dowNames": dow_names,
        "dowCnt": dow_cnt,
    }

    def money(x): return f"${x:,.2f}"

    top_rows = "\n".join(
        f'<tr><td class="rank">{i+1}</td><td><a href="{s["url"]}" target="_blank" rel="noopener">{s["title"][:74]}</a></td>'
        f'<td><span class="chip">{s["brand"]}</span></td><td class="num">{money(s["price"])}</td>'
        f'<td class="dt">{s["date"].strftime("%b %-d")}</td></tr>'
        for i, s in enumerate(top))

    brand_rows = "\n".join(
        f'<tr><td>{b}</td><td class="num">{brand_cnt[b]}</td><td class="num">{money(brand_rev[b])}</td>'
        f'<td class="num">{money(brand_rev[b]/brand_cnt[b])}</td>'
        f'<td class="num">{brand_rev[b]/total*100:.0f}%</td></tr>'
        for b in brands_sorted)

    buyer_rows = "\n".join(
        f'<tr><td>{b}</td><td class="num">{c}</td><td class="num">{money(sp)}</td></tr>'
        for b, c, sp in repeat[:12]) or '<tr><td colspan="3" class="muted">No repeat buyers yet</td></tr>'

    best_week_txt = (f'{week_labels[best_week_i]} · {money(by_week_rev[weeks[best_week_i]])}'
                     if best_week_i is not None else "—")

    body = f"""
<main class="st-wrap">
  <header class="st-head">
    <h1>Sales Trends</h1>
    <p class="muted">All completed orders · {first.strftime('%b %-d, %Y') if first else '—'} → {last.strftime('%b %-d, %Y') if last else '—'} ({span_days} days)</p>
  </header>

  <section class="st-kpis">
    <div class="stat-card"><div class="num">{money(total)}</div><div class="lbl">Total revenue</div></div>
    <div class="stat-card"><div class="num">{n}</div><div class="lbl">Cards sold</div></div>
    <div class="stat-card"><div class="num">{money(avg)}</div><div class="lbl">Avg sale</div></div>
    <div class="stat-card"><div class="num">{money(med)}</div><div class="lbl">Median sale</div></div>
    <div class="stat-card"><div class="num">{money(total/span_days*7)}</div><div class="lbl">Rev / week</div></div>
    <div class="stat-card"><div class="num">{best_week_txt}</div><div class="lbl">Best week</div></div>
  </section>

  <section class="panel">
    <h2>Revenue over time <span class="muted">(weekly)</span></h2>
    <canvas id="revChart" height="120"></canvas>
  </section>

  <div class="st-two">
    <section class="panel">
      <h2>What's selling — by set</h2>
      <canvas id="brandChart" height="200"></canvas>
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
      <tbody>{brand_rows}</tbody>
    </table></div>
  </section>

  <div class="st-two">
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
  </div>
</main>
<script>window.__SALES = {json.dumps(payload)};</script>
<script>{_PAGE_JS}</script>
""".strip()

    html = promote.html_shell(
        f"Sales Trends · {getattr(promote, 'SELLER_NAME', 'harpua2001')}",
        body, extra_head=f"<style>{_PAGE_CSS}</style>", active_page="sales_trends.html")
    OUT.write_text(html, encoding="utf-8")
    print(f"  Sales Trends: {n} sales · {money(total)} total · {len(brands_sorted)} sets")
    print(f"  Wrote {OUT}")


_PAGE_CSS = """
.st-wrap { max-width: 1100px; margin: 0 auto; }
.st-head h1 { font-family: 'Fraunces', serif; font-size: 34px; margin: 0 0 2px; }
.st-kpis { display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin: 18px 0 24px; }
.st-kpis .stat-card { background: var(--surface-2); border: 1px solid var(--border); border-radius: 14px; padding: 16px; }
.st-kpis .num { font-family: 'JetBrains Mono', monospace; font-size: 19px; font-weight: 700; color: var(--gold); }
.st-kpis .lbl { font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: var(--text-dim); margin-top: 4px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px; margin-bottom: 18px; }
.panel h2 { font-size: 16px; margin: 0 0 14px; }
.st-two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th, td { padding: 9px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th.num, td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
td.rank { color: var(--text-dim); font-family: 'JetBrains Mono', monospace; }
td.dt { color: var(--text-dim); white-space: nowrap; }
.chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--surface-2); color: var(--text-dim); }
.muted { color: var(--text-dim); }
@media (max-width: 820px) { .st-kpis { grid-template-columns: repeat(2, 1fr); } .st-two { grid-template-columns: 1fr; } }
"""

_PAGE_JS = """
(function(){
  const S = window.__SALES; if(!S || !window.Chart) return;
  const css = getComputedStyle(document.documentElement);
  const gold = css.getPropertyValue('--gold').trim() || '#d4af37';
  const dim  = css.getPropertyValue('--text-dim').trim() || '#9aa';
  const grid = 'rgba(255,255,255,.06)';
  Chart.defaults.color = dim; Chart.defaults.font.family = "'Familjen Grotesk', sans-serif";
  const money = v => '$' + Number(v).toLocaleString(undefined,{maximumFractionDigits:0});

  new Chart(document.getElementById('revChart'), {
    data: { labels: S.weekLabels, datasets: [
      { type:'bar', label:'Revenue', data:S.weekRev, backgroundColor:gold, borderRadius:4, yAxisID:'y', order:2 },
      { type:'line', label:'Cards sold', data:S.weekCnt, borderColor:'#7db7ff', backgroundColor:'#7db7ff',
        tension:.3, yAxisID:'y1', order:1, pointRadius:2 } ] },
    options: { responsive:true, maintainAspectRatio:false, interaction:{mode:'index',intersect:false},
      plugins:{ legend:{labels:{boxWidth:12}}, tooltip:{ callbacks:{ label:c=> c.dataset.yAxisID==='y' ? ' '+money(c.parsed.y) : ' '+c.parsed.y+' cards' } } },
      scales:{ y:{position:'left',grid:{color:grid},ticks:{callback:money}}, y1:{position:'right',grid:{display:false}}, x:{grid:{display:false}} } }
  });

  new Chart(document.getElementById('brandChart'), {
    type:'bar', data:{ labels:S.brandLabels, datasets:[{ label:'Revenue', data:S.brandRev, backgroundColor:gold, borderRadius:4 }] },
    options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>' '+money(c.parsed.x)+' · '+S.brandCnt[c.dataIndex]+' sold'}}},
      scales:{ x:{grid:{color:grid},ticks:{callback:money}}, y:{grid:{display:false}} } }
  });

  const palette = ['#5b8def','#49b675','#e0b13a','#e0773a','#d4553a','#a05ad4'];
  new Chart(document.getElementById('bandChart'), {
    type:'doughnut', data:{ labels:S.bandLabels, datasets:[{ data:S.bandCnt, backgroundColor:palette, borderWidth:0 }] },
    options:{ responsive:true, maintainAspectRatio:false, cutout:'58%', plugins:{ legend:{position:'right',labels:{boxWidth:12}} } }
  });

  new Chart(document.getElementById('dowChart'), {
    type:'bar', data:{ labels:S.dowNames, datasets:[{ data:S.dowCnt, backgroundColor:'#5b8def', borderRadius:4 }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
      scales:{ y:{grid:{color:grid}}, x:{grid:{display:false}} } }
  });
})();
"""

if __name__ == "__main__":
    main()
