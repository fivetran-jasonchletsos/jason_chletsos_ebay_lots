#!/usr/bin/env python3
"""P&L Agent — REAL margin tracker. For each sold order:
net = sale - FVF - ad_spend - ship - acquired_cost. Renders docs/pnl.html.
Reuses promote._ebay_net / promote.html_shell read-only."""

from __future__ import annotations

import csv, json, re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote  # reuse _ebay_net, html_shell, constants, paths

ROOT          = Path(__file__).parent
DOCS_DIR      = ROOT / "docs"
OUTPUT_DIR    = ROOT / "output"
SOLD_FILE     = ROOT / "sold_history.json"
LISTINGS_FILE = OUTPUT_DIR / "listings_snapshot.json"
INVENTORY_CSV = ROOT / "inventory.csv"
PROMOTED_FILE = OUTPUT_DIR / "promoted_listings_plan.json"
OUTPUT_HTML   = DOCS_DIR / "pnl.html"

DEFAULT_SHIP_COST = getattr(promote, "DEFAULT_SHIP_COST_LOW", 1.30)


# ----------------------------- helpers ------------------------------------- #

_STOPWORDS = {
    "the", "a", "an", "of", "and", "for", "with", "card", "cards",
    "rc", "nfl", "nba", "mlb", "nhl", "rookie", "lot",
}


def _tokens(text: str) -> set[str]:
    """Tokenize a card title into lowercase alphanumeric tokens, minus stopwords."""
    if not text:
        return set()
    raw = re.findall(r"[A-Za-z0-9]+", text.lower())
    return {t for t in raw if t and t not in _STOPWORDS and len(t) > 1}


def _to_float(x: Any, default: float = 0.0) -> float:
    if x is None or x == "":
        return default
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _parse_dt(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _safe(s: str | None) -> str:
    """Minimal HTML-escape."""
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


# ----------------------------- data loaders -------------------------------- #

def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8")) or fallback
    except Exception:
        return fallback


def load_sold_history(path: Path = SOLD_FILE) -> list[dict]:
    return _read_json(path, [])


def load_listings(path: Path = LISTINGS_FILE) -> list[dict]:
    return _read_json(path, [])


def load_inventory(path: Path = INVENTORY_CSV) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_promoted_plan(path: Path = PROMOTED_FILE) -> dict[str, float]:
    """Return {item_id: ad_rate} for items in the current promoted plan."""
    plan = _read_json(path, {})
    out: dict[str, float] = {}
    for dec in plan.get("decisions", []) or []:
        iid = str(dec.get("item_id") or "")
        if iid:
            out[iid] = _to_float(dec.get("rate"), 0.0)
    return out


# ----------------------------- inventory match ----------------------------- #

def _inventory_index(inv: list[dict]) -> list[tuple[set[str], float, str, dict]]:
    """
    Pre-compute per-row token sets + acquired price.
    Each entry: (tokens, acquired_price, ebay_item_id_or_empty, raw_row)
    """
    idx: list[tuple[set[str], float, str, dict]] = []
    for row in inv:
        title_parts = [
            row.get("name", ""),
            row.get("player", ""),
            row.get("set", ""),
            row.get("year", ""),
            row.get("card_number", ""),
            row.get("parallel", ""),
        ]
        toks = _tokens(" ".join(p for p in title_parts if p))
        price = _to_float(row.get("acquired_price"), 0.0)
        ebay_id = str(row.get("ebay_item_id") or "").strip()
        idx.append((toks, price, ebay_id, row))
    return idx


def match_acquired_cost(
    order: dict, inv_index: list[tuple[set[str], float, str, dict]]
) -> tuple[float, bool]:
    """
    Returns (acquired_cost, matched).
    Priority: exact ebay_item_id, then strongest token overlap (min 3 shared, >=40% jaccard).
    """
    item_id = str(order.get("item_id") or "")
    if item_id:
        for toks, price, eid, _row in inv_index:
            if eid and eid == item_id:
                return (price, True)

    title_toks = _tokens(order.get("title", ""))
    if not title_toks:
        return (0.0, False)

    best_score = 0.0
    best_price = 0.0
    best_match = False
    for toks, price, _eid, _row in inv_index:
        if not toks:
            continue
        shared = title_toks & toks
        if len(shared) < 3:
            continue
        jacc = len(shared) / max(1, len(title_toks | toks))
        if jacc >= 0.40 and jacc > best_score:
            best_score = jacc
            best_price = price
            best_match = True
    return (best_price, best_match) if best_match else (0.0, False)


# ----------------------------- category lookup ----------------------------- #

def _category_index(listings: list[dict]) -> dict[str, str]:
    out: dict[str, str] = {}
    for l in listings:
        iid = str(l.get("item_id") or "")
        cat = (l.get("category") or "").strip()
        if iid:
            out[iid] = cat or _guess_category(l.get("title", ""))
    return out


def _guess_category(title: str) -> str:
    t = (title or "").lower()
    if "pokemon" in t or "pokémon" in t:
        return "Pokemon"
    if any(k in t for k in ("panini", "topps", "donruss", "prizm", "bowman", "select")):
        return "Sports Cards"
    if "lot" in t:
        return "Lots"
    return "Other"


# ----------------------------- core P&L ------------------------------------ #

def compute_pnl(
    sold_orders: list[dict],
    listings: list[dict],
    inventory: list[dict],
    promoted_plan: dict[str, float],
    ship_cost_default: float = DEFAULT_SHIP_COST,
) -> list[dict]:
    """Compute per-order P&L. Returns one row per order (deduped by `uniq`)."""
    inv_idx = _inventory_index(inventory)
    cat_idx = _category_index(listings)
    listing_by_id = {str(l.get("item_id")): l for l in listings}
    seen: set[str] = set()
    rows: list[dict] = []
    for o in sold_orders:
        uniq = str(o.get("uniq") or o.get("order_id") or "")
        if uniq and uniq in seen:
            continue
        seen.add(uniq)
        sale = _to_float(o.get("sale_price"), 0.0)
        if sale <= 0:
            continue
        item_id = str(o.get("item_id") or "")
        ship = _to_float(o.get("ship_cost"), ship_cost_default) or ship_cost_default
        fee_math = promote._ebay_net(sale, ship_cost=ship)
        fvf = _to_float(fee_math.get("fvf"), 0.0) + _to_float(fee_math.get("fixed"), 0.0)
        ad_rate = promoted_plan.get(item_id, 0.0)
        ad_spend = round(sale * ad_rate, 2) if ad_rate else 0.0
        acquired, matched = match_acquired_cost(o, inv_idx)
        net_profit = round(sale - fvf - ad_spend - ship - acquired, 2)
        margin_pct = round((net_profit / sale) * 100.0, 2) if sale else 0.0
        category = cat_idx.get(item_id) or _guess_category(o.get("title", ""))
        listing = listing_by_id.get(item_id) or {}
        pic = o.get("pic") or listing.get("pic") or ""
        url = o.get("url") or listing.get("url") or (
            f"https://www.ebay.com/itm/{item_id}" if item_id else "")
        rows.append({
            "order_id": str(o.get("order_id") or uniq), "item_id": item_id,
            "uniq": uniq, "sold_at": str(o.get("sold_date") or ""),
            "title": o.get("title") or "", "buyer": o.get("buyer") or "",
            "sale_price": round(sale, 2), "fvf": round(fvf, 2),
            "ad_rate": ad_rate, "ad_spend": ad_spend,
            "ship_cost": round(ship, 2), "acquired_cost": round(acquired, 2),
            "acquired_matched": matched, "net_profit": net_profit,
            "margin_pct": margin_pct, "category": category,
            "pic": pic, "url": url,
        })
    rows.sort(key=lambda r: r["sold_at"], reverse=True)
    return rows


# ----------------------------- rollups ------------------------------------- #

def _rollup(rows: list[dict], key_fn) -> list[dict]:
    bucket: dict[str, dict] = defaultdict(lambda: {
        "revenue": 0.0, "fvf": 0.0, "ad_spend": 0.0,
        "ship_cost": 0.0, "acquired_cost": 0.0,
        "net_profit": 0.0, "orders": 0,
    })
    for r in rows:
        k = key_fn(r)
        if k is None:
            continue
        b = bucket[k]
        b["revenue"]       += r["sale_price"]
        b["fvf"]           += r["fvf"]
        b["ad_spend"]      += r["ad_spend"]
        b["ship_cost"]     += r["ship_cost"]
        b["acquired_cost"] += r["acquired_cost"]
        b["net_profit"]    += r["net_profit"]
        b["orders"]        += 1
    out = []
    for k, b in bucket.items():
        rev = b["revenue"] or 0.0
        out.append({
            "key":           k,
            "orders":        b["orders"],
            "revenue":       round(rev, 2),
            "fvf":           round(b["fvf"], 2),
            "ad_spend":      round(b["ad_spend"], 2),
            "ship_cost":     round(b["ship_cost"], 2),
            "acquired_cost": round(b["acquired_cost"], 2),
            "net_profit":    round(b["net_profit"], 2),
            "margin_pct":    round((b["net_profit"] / rev) * 100.0, 2) if rev else 0.0,
        })
    return out


def rollup_by_category(rows: list[dict]) -> list[dict]:
    out = _rollup(rows, lambda r: r.get("category") or "Other")
    out.sort(key=lambda b: b["net_profit"], reverse=True)
    return out


def rollup_by_month(rows: list[dict]) -> list[dict]:
    def keyer(r: dict) -> str | None:
        dt = _parse_dt(r["sold_at"])
        return dt.strftime("%Y-%m") if dt else None
    out = _rollup(rows, keyer)
    out.sort(key=lambda b: b["key"])
    return out


def identify_winners_losers(rows: list[dict], top_n: int = 5
                            ) -> tuple[list[dict], list[dict]]:
    sorted_rows = sorted(rows, key=lambda r: r["net_profit"], reverse=True)
    winners = sorted_rows[:top_n]
    losers  = sorted(
        [r for r in rows if r["net_profit"] < 0 or r["margin_pct"] < 10],
        key=lambda r: r["net_profit"],
    )[:top_n]
    return winners, losers


# ----------------------------- HTML render --------------------------------- #

def _fmt_money(x: float) -> str:
    sign = "-" if x < 0 else ""
    return f"{sign}${abs(x):,.2f}"


def _kpi_card(label: str, value: str, tone: str = "") -> str:
    klass = "kpi-card" + (f" kpi-{tone}" if tone else "")
    return (f'<div class="{klass}"><div class="kpi-label">{_safe(label)}</div>'
            f'<div class="kpi-value">{_safe(value)}</div></div>')


def _monthly_chart(months: list[dict]) -> str:
    months = months[-12:]
    if not months:
        return "<div class='muted'>No monthly data yet.</div>"
    max_rev = max((m["revenue"] for m in months), default=1.0) or 1.0
    bars = []
    for m in months:
        costs = m["fvf"] + m["ad_spend"] + m["ship_cost"] + m["acquired_cost"]
        rh = max(2, int(220 * m["revenue"] / max_rev))
        ch = max(2, int(220 * costs / max_rev))
        ph = max(2, int(220 * abs(m["net_profit"]) / max_rev))
        pc = "bar-profit" if m["net_profit"] >= 0 else "bar-loss"
        bars.append(
            f'<div class="month-col"><div class="bars">'
            f'<div class="bar bar-rev" style="height:{rh}px" title="Revenue {_fmt_money(m["revenue"])}"></div>'
            f'<div class="bar bar-cost" style="height:{ch}px" title="Costs {_fmt_money(costs)}"></div>'
            f'<div class="bar {pc}" style="height:{ph}px" title="Net {_fmt_money(m["net_profit"])}"></div>'
            f'</div><div class="month-label">{_safe(m["key"])}</div>'
            f'<div class="month-net">{_fmt_money(m["net_profit"])}</div></div>'
        )
    legend = ('<div class="legend"><span class="lg-dot bar-rev"></span>Revenue'
              '<span class="lg-dot bar-cost"></span>Costs'
              '<span class="lg-dot bar-profit"></span>Profit</div>')
    return f'<div class="chart-wrap"><div class="month-row">{"".join(bars)}</div>{legend}</div>'


def _category_chart(cats: list[dict]) -> str:
    if not cats:
        return "<div class='muted'>No category data yet.</div>"
    max_rev = max((c["revenue"] for c in cats), default=1.0) or 1.0
    rows_html = []
    for c in cats:
        rw = int(100 * c["revenue"] / max_rev)
        pw = int(100 * max(0, c["net_profit"]) / max_rev)
        cls = "pos" if c["net_profit"] >= 0 else "neg"
        rows_html.append(
            f'<div class="cat-row"><div class="cat-name">{_safe(c["key"])}</div>'
            f'<div class="cat-bars"><div class="cat-bar cat-bar-rev" style="width:{rw}%"></div>'
            f'<div class="cat-bar cat-bar-prof" style="width:{pw}%"></div></div>'
            f'<div class="cat-nums"><span>{c["orders"]} orders</span>'
            f'<span>Rev {_fmt_money(c["revenue"])}</span>'
            f'<span class="{cls}">Net {_fmt_money(c["net_profit"])} ({c["margin_pct"]}%)</span>'
            f'</div></div>'
        )
    return f"<div class='cat-chart'>{''.join(rows_html)}</div>"


def _orders_table(rows: list[dict], limit: int = 30) -> str:
    if not rows:
        return "<div class='muted'>No orders yet.</div>"
    body = []
    for r in rows[:limit]:
        pc = "pos" if r["net_profit"] >= 0 else "neg"
        sold_at = (r["sold_at"] or "")[:10]
        miss = "" if r["acquired_matched"] else " *"
        body.append(
            f'<tr><td>{_safe(sold_at)}</td>'
            f'<td><a href="{_safe(r["url"])}" target="_blank" rel="noopener">{_safe(r["title"][:80])}</a></td>'
            f'<td>{_safe(r["category"])}</td><td>{_fmt_money(r["sale_price"])}</td>'
            f'<td>{_fmt_money(r["fvf"])}</td><td>{_fmt_money(r["ad_spend"])}</td>'
            f'<td>{_fmt_money(r["ship_cost"])}</td>'
            f'<td>{_fmt_money(r["acquired_cost"])}{miss}</td>'
            f'<td class="{pc}"><b>{_fmt_money(r["net_profit"])}</b></td>'
            f'<td class="{pc}">{r["margin_pct"]}%</td></tr>'
        )
    head = ('<thead><tr><th>Date</th><th>Title</th><th>Category</th><th>Sale</th>'
            '<th>FVF</th><th>Ad</th><th>Ship</th><th>Cost</th><th>Net</th><th>Margin</th></tr></thead>')
    return (f'<div class="table-wrap"><table class="pnl-table">{head}'
            f'<tbody>{"".join(body)}</tbody></table></div>'
            f'<p class="muted small">* acquired cost not in inventory.csv — using $0.00</p>')


def _leader_cards(rows: list[dict], tone: str) -> str:
    if not rows:
        return "<div class='muted'>None.</div>"
    cards = []
    for r in rows:
        cls = "pos" if tone == "win" else "neg"
        pic = _safe(r["pic"]) or ""
        img = (f"<img loading='lazy' src='{pic}' alt=''>" if pic
               else "<div class='no-pic'>no pic</div>")
        cards.append(
            f'<a class="leader" href="{_safe(r["url"])}" target="_blank" rel="noopener">'
            f'<div class="leader-pic">{img}</div><div class="leader-meta">'
            f'<div class="leader-title">{_safe(r["title"][:70])}</div>'
            f'<div class="leader-line"><span>{_fmt_money(r["sale_price"])}</span>'
            f'<span class="{cls}"><b>{_fmt_money(r["net_profit"])}</b> · {r["margin_pct"]}%</span>'
            f'</div></div></a>'
        )
    return f"<div class='leaders-grid'>{''.join(cards)}</div>"


def render_html(
    rows: list[dict],
    months: list[dict],
    cats: list[dict],
    winners: list[dict],
    losers: list[dict],
) -> str:
    rev_total  = round(sum(r["sale_price"]    for r in rows), 2)
    fees_total = round(sum(r["fvf"] + r["ad_spend"] for r in rows), 2)
    ship_total = round(sum(r["ship_cost"]     for r in rows), 2)
    cost_total = round(sum(r["acquired_cost"] for r in rows), 2)
    prof_total = round(sum(r["net_profit"]    for r in rows), 2)
    avg_margin = round((prof_total / rev_total) * 100.0, 2) if rev_total else 0.0
    missing    = [r for r in rows if not r["acquired_matched"]]

    kpis = "".join([
        _kpi_card("Lifetime Revenue",  _fmt_money(rev_total)),
        _kpi_card("Fees + Ads",        _fmt_money(fees_total), "warn"),
        _kpi_card("Shipping",          _fmt_money(ship_total), "warn"),
        _kpi_card("Acquired Cost",     _fmt_money(cost_total), "warn"),
        _kpi_card("Net Profit",        _fmt_money(prof_total),
                  "pos" if prof_total >= 0 else "neg"),
        _kpi_card("Avg Margin",        f"{avg_margin}%",
                  "pos" if avg_margin >= 0 else "neg"),
        _kpi_card("Orders",            str(len(rows))),
    ])

    extra_css = (
      ".kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0 28px}"
      ".kpi-card{background:var(--card,#141414);border:1px solid var(--border,#262626);border-radius:14px;padding:14px 16px}"
      ".kpi-label{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted,#888)}"
      ".kpi-value{font-size:22px;font-weight:700;margin-top:4px}"
      ".kpi-pos .kpi-value{color:#34d399}.kpi-neg .kpi-value{color:#f87171}.kpi-warn .kpi-value{color:#fbbf24}"
      ".pnl-section{margin:30px 0}.pnl-section h2{margin-bottom:10px;font-size:18px;letter-spacing:.04em;text-transform:uppercase}"
      ".chart-wrap{background:var(--card,#141414);border:1px solid var(--border,#262626);border-radius:14px;padding:16px}"
      ".month-row{display:flex;gap:6px;align-items:flex-end;overflow-x:auto;padding-bottom:6px}"
      ".month-col{flex:1;min-width:60px;text-align:center}"
      ".bars{display:flex;gap:2px;align-items:flex-end;height:220px;justify-content:center}"
      ".bar{width:10px;border-radius:3px 3px 0 0}"
      ".bar-rev{background:#60a5fa}.bar-cost{background:#fbbf24}.bar-profit{background:#34d399}.bar-loss{background:#f87171}"
      ".month-label{font-size:10px;color:var(--muted,#888);margin-top:6px}"
      ".month-net{font-size:11px;font-weight:600;margin-top:2px}"
      ".legend{margin-top:10px;font-size:12px;color:var(--muted,#888);display:flex;gap:14px;align-items:center}"
      ".lg-dot{display:inline-block;width:10px;height:10px;border-radius:3px;margin-right:4px;vertical-align:middle}"
      ".cat-chart{display:flex;flex-direction:column;gap:8px}"
      ".cat-row{background:var(--card,#141414);border:1px solid var(--border,#262626);border-radius:10px;padding:10px 14px}"
      ".cat-name{font-weight:700;margin-bottom:6px}"
      ".cat-bars{position:relative;height:14px;background:#1f1f1f;border-radius:6px;overflow:hidden;margin-bottom:6px}"
      ".cat-bar{position:absolute;top:0;left:0;height:100%}"
      ".cat-bar-rev{background:#60a5fa;opacity:.45}.cat-bar-prof{background:#34d399}"
      ".cat-nums{display:flex;gap:14px;font-size:12px;color:var(--muted,#888);flex-wrap:wrap}"
      ".table-wrap{overflow-x:auto;background:var(--card,#141414);border:1px solid var(--border,#262626);border-radius:14px;padding:8px}"
      ".pnl-table{width:100%;border-collapse:collapse;font-size:13px}"
      ".pnl-table th,.pnl-table td{padding:8px 10px;border-bottom:1px solid #222;text-align:left;white-space:nowrap}"
      ".pnl-table th{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted,#888)}"
      ".pnl-table a{color:inherit;text-decoration:none}"
      ".pos{color:#34d399}.neg{color:#f87171}"
      ".leaders-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:12px}"
      ".leader{display:flex;gap:10px;background:var(--card,#141414);border:1px solid var(--border,#262626);border-radius:12px;padding:10px;text-decoration:none;color:inherit}"
      ".leader-pic{width:64px;height:64px;flex:0 0 64px;border-radius:8px;overflow:hidden;background:#0a0a0a;display:flex;align-items:center;justify-content:center}"
      ".leader-pic img{width:100%;height:100%;object-fit:cover}"
      ".no-pic{font-size:10px;color:#555}.leader-meta{flex:1;min-width:0}"
      ".leader-title{font-size:12px;line-height:1.3;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}"
      ".leader-line{margin-top:6px;display:flex;justify-content:space-between;font-size:12px;gap:6px}"
      ".muted{color:var(--muted,#888)}.small{font-size:12px}"
      ".footer-note{margin-top:30px;padding:14px;border-radius:12px;background:#1c1500;border:1px solid #5a4400;color:#fbbf24;font-size:13px}"
    )

    note = (
      f"<b>{len(missing)} orders missing acquired_cost.</b> Add their rows to "
      "<code>inventory.csv</code> (set <code>ebay_item_id</code> + "
      "<code>acquired_price</code>) to make these margins truthful — until then "
      "they assume $0 cost basis and overstate profit."
    )
    body = (
      '<main class="container">'
      '<h1>P&amp;L Tracker</h1>'
      '<p class="muted">Real take-home per order — sale minus FVF, ads, shipping, '
      'and acquired cost. Margins update each build.</p>'
      f'<div class="kpi-row">{kpis}</div>'
      f'<div class="pnl-section"><h2>Monthly P&amp;L (last 12)</h2>{_monthly_chart(months)}</div>'
      f'<div class="pnl-section"><h2>By Category</h2>{_category_chart(cats)}</div>'
      f'<div class="pnl-section"><h2>Profit Leaders</h2>{_leader_cards(winners, "win")}</div>'
      f'<div class="pnl-section"><h2>Loss Leaders &amp; Thin Margins</h2>{_leader_cards(losers, "loss")}</div>'
      f'<div class="pnl-section"><h2>Recent 30 Orders</h2>{_orders_table(rows, 30)}</div>'
      f'<div class="footer-note">{note}</div>'
      '</main>'
    )

    return promote.html_shell(
        f"P&L · {promote.SELLER_NAME}",
        body,
        extra_head=f"<style>{extra_css}</style>",
        active_page="pnl.html",
    )


# ----------------------------- entrypoint ---------------------------------- #

def run() -> dict:
    sold     = load_sold_history()
    listings = load_listings()
    inv      = load_inventory()
    promo    = load_promoted_plan()

    rows    = compute_pnl(sold, listings, inv, promo)
    months  = rollup_by_month(rows)
    cats    = rollup_by_category(rows)
    winners, losers = identify_winners_losers(rows, top_n=5)

    DOCS_DIR.mkdir(exist_ok=True)
    OUTPUT_HTML.write_text(
        render_html(rows, months, cats, winners, losers), encoding="utf-8"
    )

    rev   = round(sum(r["sale_price"] for r in rows), 2)
    prof  = round(sum(r["net_profit"]  for r in rows), 2)
    miss  = sum(1 for r in rows if not r["acquired_matched"])
    def _brief(r: dict) -> dict:
        return {"title": r["title"], "net_profit": r["net_profit"],
                "margin_pct": r["margin_pct"]}
    return {
        "orders": len(rows), "revenue": rev, "net_profit": prof,
        "avg_margin_pct": round((prof / rev) * 100.0, 2) if rev else 0.0,
        "missing_acquired": miss,
        "winners": [_brief(w) for w in winners[:3]],
        "losers":  [_brief(l) for l in losers[:3]],
        "output": str(OUTPUT_HTML),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


if __name__ == "__main__":
    s = run()
    print(json.dumps(s, indent=2, default=str))
