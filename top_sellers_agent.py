"""
top_sellers_agent.py — track the biggest sports-card consignment stores
on eBay (Probstein123, DCSports87, Burbank, Greg Morris, COMC) plus a
few notable Pokemon volume sellers. For each: pull their current cheap
+ no-reserve auctions ending soon, surface deal candidates.

Why: these are the houses that move tens of thousands of cards monthly.
Penny-start auctions from Probstein and COMC are how serious collectors
build cheap. Watching them = the buyer-side edge.

Output:
  output/top_sellers_plan.json
  docs/top_sellers.html
"""
from __future__ import annotations

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT = Path(__file__).parent
PLAN_PATH = REPO_ROOT / "output" / "top_sellers_plan.json"
REPORT    = REPO_ROOT / "docs"   / "top_sellers.html"
BROWSE    = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Curated list of top sports-card + Pokemon volume sellers.
# Rankings + lifetime/active counts from Marketplace Pulse data published
# July 2024 in Sports Collectors Daily — among 37 US sellers in the
# worldwide top 100, 9 are primarily sports-card accounts.
TOP_SELLERS = [
    {"username": "dcsports87",        "name": "DCSports87",        "kind": "consignment",
     "tag": "#6 worldwide eBay seller. Top sports-card account by feedback volume.",
     "url": "https://www.ebay.com/usr/dcsports87",
     "rank_global": 6, "monthly_feedback": 40169, "active_listings": 23000,
     "queries": ["rookie card", "graded card"]},
    {"username": "comc_consignment",  "name": "COMC",              "kind": "consignment",
     "tag": "#7 worldwide. Check Out My Collectibles — 6.1M cross-listed from consignors.",
     "url": "https://www.ebay.com/usr/comc_consignment",
     "rank_global": 7, "monthly_feedback": 38000, "active_listings": 7000000, "lifetime_sales": 6100000,
     "queries": ["single card", "rookie", "pokemon"]},
    {"username": "gregmorriscards",   "name": "Greg Morris Cards", "kind": "vintage",
     "tag": "#12 worldwide. 2.9M lifetime feedback — most of any sports-card seller. 7.5M lifetime sales.",
     "url": "https://www.ebay.com/usr/gregmorriscards",
     "rank_global": 12, "lifetime_feedback": 2900000, "active_listings": 33000, "lifetime_sales": 7500000,
     "queries": ["vintage card", "1970", "1980"]},
    {"username": "burbanksportscards","name": "Burbank Sports Cards","kind": "volume",
     "tag": "#17 worldwide. 6.7M lifetime sales · 2.4M active listings · since 2005.",
     "url": "https://www.ebay.com/usr/burbanksportscards",
     "rank_global": 17, "active_listings": 2400000, "lifetime_sales": 6700000,
     "queries": ["football single", "baseball single", "basketball single"]},
    {"username": "probstein123",      "name": "Probstein123",      "kind": "consignment",
     "tag": "5th largest sports-collectible seller. Famous for penny-start no-reserve auctions.",
     "url": "https://www.ebay.com/usr/probstein123",
     "rank_sports": 5, "active_listings": 15000,
     "queries": ["football card", "basketball card", "baseball card"]},
    {"username": "4sharpcorners",     "name": "4 Sharp Corners",   "kind": "consignment",
     "tag": "#44 worldwide. Modern + vintage consignment.",
     "url": "https://www.ebay.com/usr/4sharpcorners",
     "rank_global": 44, "active_listings": 28000,
     "queries": ["rookie card", "graded"]},
    {"username": "rememberwhensportscards", "name": "Remember When Sports Cards", "kind": "vintage",
     "tag": "#50 worldwide. Vintage specialist.",
     "url": "https://www.ebay.com/usr/rememberwhensportscards",
     "rank_global": 50,
     "queries": ["vintage", "1960", "1970"]},
]


def _search_by_seller(token: str, seller: str, q: str,
                      max_price: float = 100) -> list[dict]:
    params = {
        "q": q,
        "limit": "50",
        "filter": (
            f"sellers:{{{seller}}},"
            f"buyingOptions:{{FIXED_PRICE|AUCTION}},"
            f"itemLocationCountry:US,"
            f"price:[1..{max_price}],"
            f"priceCurrency:USD"
        ),
        "sort": "price",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        r = requests.get(BROWSE, params=params, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Browse failed for seller={seller} q={q!r}: {exc}")
        return []
    items = r.json().get("itemSummaries", []) or []
    out: list[dict] = []
    for it in items:
        try:
            price = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append({
            "item_id":   (it.get("itemId") or "").split("|")[-1],
            "title":     it.get("title") or "",
            "price":     price,
            "url":       promote._epn_wrap(it.get("itemWebUrl") or ""),
            "image":     ((it.get("image") or {}).get("imageUrl")) or "",
            "buying":    it.get("buyingOptions", []) or [],
            "condition": it.get("condition") or "",
        })
    return out


def build_plan() -> dict:
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    token = promote.get_app_token(cfg)
    sellers_out = []
    for s in TOP_SELLERS:
        print(f"  -> {s['name']}")
        items: list[dict] = []
        seen: set[str] = set()
        for q in s["queries"]:
            for it in _search_by_seller(token, s["username"], q):
                if it["item_id"] in seen: continue
                seen.add(it["item_id"])
                items.append(it)
        items.sort(key=lambda x: x["price"])  # cheapest first
        sellers_out.append({**s, "items": items[:24], "n": len(items),
                            "cheapest": items[0]["price"] if items else None})
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sellers":      sellers_out,
    }


def save_plan(plan: dict) -> Path:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    sellers = plan["sellers"]
    total_items = sum(s["n"] for s in sellers)

    sections = []
    for s in sellers:
        cards = []
        for it in s["items"]:
            buying = " · ".join(
                "BIN" if x == "FIXED_PRICE" else
                "Auction" if x == "AUCTION" else
                "Best Offer" if x == "BEST_OFFER" else _esc(x)
                for x in it["buying"]
            )
            cards.append(f"""
            <a class="ts-card" href="{_esc(it['url'])}" target="_blank" rel="noopener">
              <div class="ts-img" style="background-image:url('{_esc(it['image'])}');"></div>
              <div class="ts-meta">
                <div class="ts-price">${it['price']:.2f}</div>
                <div class="ts-title">{_esc(it['title'][:80])}</div>
                <div class="ts-buying">{buying}</div>
              </div>
            </a>""")
        cheapest = f"${s['cheapest']:.2f}" if s.get("cheapest") else "—"
        # Marketplace-Pulse-style rank badge
        rank_html = ""
        if s.get("rank_global"):
            rank_html = f'<span class="ts-rank">#{s["rank_global"]} GLOBAL</span>'
        elif s.get("rank_sports"):
            rank_html = f'<span class="ts-rank ts-rank-sports">#{s["rank_sports"]} SPORTS</span>'

        # Stats blocks (only render the metrics we have)
        stat_tiles = []
        if s.get("active_listings"):
            v = s["active_listings"]
            disp = f"{v/1_000_000:.1f}M" if v >= 1_000_000 else (f"{v/1000:.0f}K" if v >= 1000 else str(v))
            stat_tiles.append(f'<div class="ts-stat"><div class="ts-n">{disp}</div><div class="ts-l">Active listings</div></div>')
        if s.get("lifetime_sales"):
            v = s["lifetime_sales"]
            disp = f"{v/1_000_000:.1f}M"
            stat_tiles.append(f'<div class="ts-stat"><div class="ts-n">{disp}</div><div class="ts-l">Lifetime sales</div></div>')
        if s.get("monthly_feedback"):
            v = s["monthly_feedback"]
            disp = f"{v/1000:.0f}K"
            stat_tiles.append(f'<div class="ts-stat"><div class="ts-n">{disp}</div><div class="ts-l">Monthly feedback</div></div>')
        stat_tiles.append(f'<div class="ts-stat"><div class="ts-n">{s["n"]}</div><div class="ts-l">Indexed today</div></div>')
        stat_tiles.append(f'<div class="ts-stat"><div class="ts-n">{cheapest}</div><div class="ts-l">Cheapest now</div></div>')

        sections.append(f"""
        <section class="ts-section">
          <div class="ts-head">
            <div>
              <h2><a href="{_esc(s['url'])}" target="_blank" rel="noopener">{_esc(s['name'])}</a>
                <span class="ts-kind ts-kind-{s['kind']}">{_esc(s['kind'].upper())}</span>
                {rank_html}</h2>
              <p class="ts-tag">{_esc(s['tag'])}</p>
            </div>
            <div class="ts-stats">{''.join(stat_tiles)}</div>
          </div>
          <div class="ts-grid">{''.join(cards) or '<div class="ts-empty">No live listings matched the search filter.</div>'}</div>
        </section>""")

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">Hobby giants · the houses that move volume</div>
        <h1 class="section-title">Top <span class="accent">Sellers</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Probstein, DCSports, Burbank, Greg Morris, COMC — the consignment + volume
        houses where serious collectors hunt. Penny-start auctions, combined shipping,
        massive turnover. Every link below carries our EPN affiliate ID so the site
        earns commission on clicks that convert.
      </div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(sellers)}</div><div class="lbl">Sellers tracked</div></div>
      <div class="stat-card"><div class="num">{total_items}</div><div class="lbl">Live listings indexed</div></div>
    </div>

    {''.join(sections)}
    """

    extra_css = """
<style>
  .ts-section { margin: 28px 0; padding-bottom: 22px; border-bottom: 1px solid var(--border); }
  .ts-head { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end; margin-bottom: 14px; }
  .ts-head h2 { margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 30px; letter-spacing: .02em; }
  .ts-head h2 a { color: var(--text); text-decoration: none; }
  .ts-head h2 a:hover { color: var(--gold); }
  .ts-kind { font-size: 10px; padding: 3px 9px; border-radius: 999px; margin-left: 10px; letter-spacing: .12em; font-weight: 700; }
  .ts-kind-consignment { color: #d4af37; background: rgba(212,175,55,.12); border: 1px solid rgba(212,175,55,.4); }
  .ts-kind-volume      { color: #6cb0ff; background: rgba(108,176,255,.12); border: 1px solid rgba(108,176,255,.35); }
  .ts-kind-vintage     { color: #c98a4d; background: rgba(201,138,77,.12); border: 1px solid rgba(201,138,77,.35); }
  .ts-kind-pokemon     { color: #ffcc00; background: rgba(255,204,0,.1);   border: 1px solid rgba(255,204,0,.3); }
  .ts-rank { display: inline-block; font-size: 10px; color: #fff; background: linear-gradient(135deg, #d4af37, #b8860b); padding: 3px 9px; border-radius: 999px; margin-left: 8px; letter-spacing: .12em; font-weight: 800; }
  .ts-rank-sports { background: linear-gradient(135deg, #6cb0ff, #4a8fd6); }
  .ts-stats { display: flex; gap: 14px; flex-wrap: wrap; }
  .ts-tag { color: var(--text-muted); font-size: 13px; margin: 4px 0 0; }
  .ts-stats { display: grid; grid-template-columns: repeat(2, auto); gap: 18px; }
  .ts-stat { text-align: center; }
  .ts-n { font-family: 'Bebas Neue', sans-serif; font-size: 24px; color: var(--gold); line-height: 1; }
  .ts-l { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }
  .ts-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }
  .ts-card { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s, border-color .15s; }
  .ts-card:hover { transform: translateY(-2px); border-color: var(--gold); }
  .ts-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }
  .ts-meta { padding: 8px 10px; }
  .ts-price { font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: var(--gold); }
  .ts-title { font-size: 11px; line-height: 1.35; color: var(--text); min-height: 28px; margin-top: 4px; }
  .ts-buying { font-size: 10px; color: var(--text-muted); margin-top: 4px; letter-spacing: .04em; }
  .ts-empty { padding: 16px; color: var(--text-muted); font-size: 13px; }
  @media (max-width: 640px) {
    .ts-head { grid-template-columns: 1fr; }
    .ts-grid { grid-template-columns: repeat(auto-fill, minmax(130px, 1fr)); }
  }
</style>
"""
    html_doc = promote.html_shell("Top Sellers · Hobby Giants", body,
                                  extra_head=extra_css,
                                  active_page="top_sellers.html")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(html_doc, encoding="utf-8")
    return REPORT


def ensure_nav_entry() -> None:
    entry = ("top_sellers.html", "Top Sellers", True, "For Us")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "under_10.html":
            items.insert(idx + 1, entry); break
    else:
        items.append(entry)
    promote._NAV_ITEMS = items
    promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.parse_args()
    ensure_nav_entry()
    plan = build_plan()
    save_plan(plan)
    out = render_report(plan)
    n = sum(s["n"] for s in plan["sellers"])
    print(f"  Sellers: {len(plan['sellers'])}  ·  Listings indexed: {n}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Report: {out}")


if __name__ == "__main__":
    main()
