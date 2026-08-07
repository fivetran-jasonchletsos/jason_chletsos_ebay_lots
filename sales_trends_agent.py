"""
sales_trends_agent.py — analytics over all completed sales.

Reads sold_history.json and computes headline KPIs, revenue-over-time,
what's selling by set/brand, price-band mix, top sales, day-of-week pattern,
and repeat buyers. Writes output/sales_trends.json for the personal dashboard
to consume (docs/sales_trends.html was retired along with the old admin site).

Usage: python3 sales_trends_agent.py
"""
from __future__ import annotations

import json
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).parent
SOLD = REPO / "sold_history.json"
OUT  = REPO / "output" / "sales_trends.json"

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

    best_week_txt = (f'{week_labels[best_week_i]} · {money(by_week_rev[weeks[best_week_i]])}'
                     if best_week_i is not None else "—")

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "first_sale": first.isoformat() if first else None,
        "last_sale": last.isoformat() if last else None,
        "span_days": span_days,
        "total_revenue": round(total, 2),
        "cards_sold": n,
        "avg_sale": round(avg, 2),
        "median_sale": round(med, 2),
        "revenue_per_week": round(total / span_days * 7, 2),
        "best_week": best_week_txt,
        **payload,
        "by_set": [
            {"set": b, "sold": brand_cnt[b], "revenue": round(brand_rev[b], 2),
             "avg": round(brand_rev[b] / brand_cnt[b], 2), "pct_of_revenue": round(brand_rev[b] / total * 100, 1) if total else 0}
            for b in brands_sorted
        ],
        "top_sales": [
            {"title": s["title"], "set": s["brand"], "price": s["price"],
             "date": s["date"].isoformat(), "url": s["url"]}
            for s in top
        ],
        "repeat_buyers": [
            {"buyer": b, "orders": c, "spend": round(sp, 2)} for b, c, sp in repeat[:12]
        ],
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"  Sales Trends: {n} sales · {money(total)} total · {len(brands_sorted)} sets")
    print(f"  Wrote {OUT}")


if __name__ == "__main__":
    main()
