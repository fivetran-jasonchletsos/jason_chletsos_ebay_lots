"""
buyer_watchlist_agent.py — collector watchlist for the BUY side.

Different from watchers_offer_agent.py (which surfaces people watching MY
listings). This agent tracks PLAYERS I want to collect, runs live eBay
Browse searches per player + grade combo, flags deals priced below the
median, and renders docs/collect.html — a buyer-facing filter page.

Config in buyer_watchlist.json:
  players: [
    {name, team, queries: [{q, grade, min, max}]}
  ]

Browse API endpoint is the same as fetch_deals() in promote.py. Uses the
app token (client_credentials) — no user OAuth scope required.

Output:
  output/buyer_watchlist_plan.json     structured plan
  docs/collect.html                    buyer page w/ filter UI

CLI:
  python3 buyer_watchlist_agent.py
  python3 buyer_watchlist_agent.py --player "Jaxson Dart"   # narrow
"""
from __future__ import annotations

import argparse
import html
import json
import re
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT   = Path(__file__).parent
WATCHLIST   = REPO_ROOT / "buyer_watchlist.json"
PLAN_PATH   = REPO_ROOT / "output" / "buyer_watchlist_plan.json"
REPORT_PATH = REPO_ROOT / "docs" / "collect.html"
BROWSE_URL  = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# --------------------------------------------------------------------------- #
# Search                                                                       #
# --------------------------------------------------------------------------- #

def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-") or "x"


def _search(token: str, q: str, min_price: float, max_price: float,
            own_seller: str) -> list[dict]:
    rng = f"{min_price}.." + (str(max_price) if max_price else "")
    params = {
        "q": q,
        "limit": "100",
        "filter": (
            f"buyingOptions:{{FIXED_PRICE|AUCTION}},"
            f"itemLocationCountry:US,"
            f"price:[{rng}],"
            f"priceCurrency:USD"
        ),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        r = requests.get(BROWSE_URL, params=params, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Browse failed for '{q}': {exc}")
        return []
    items = r.json().get("itemSummaries", []) or []
    out = []
    for it in items:
        seller = ((it.get("seller") or {}).get("username") or "").lower()
        if seller == own_seller.lower():
            continue
        title = it.get("title") or ""
        try:
            price = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        out.append({
            "item_id":   it.get("itemId", "").split("|")[-1],
            "title":     title,
            "price":     price,
            "url":       it.get("itemWebUrl") or "",
            "image":     ((it.get("image") or {}).get("imageUrl")) or "",
            "buying":    it.get("buyingOptions", []) or [],
            "seller":    seller,
            "condition": it.get("condition") or "",
        })
    return out


def _grade_match(title: str, grade: str) -> bool:
    """For grade=='PSA 10' require literal "psa 10" in title.
       For grade=='raw' reject any psa/bgs/sgc mention."""
    t = title.lower()
    g = (grade or "").lower().strip()
    if g in ("psa 10", "psa10"):
        return "psa 10" in t or "psa10" in t
    if g == "raw":
        return not any(x in t for x in ("psa ", "bgs ", "sgc ", "cgc ", "graded"))
    if g:  # other grade strings — substring match
        return g in t
    return True


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

def build_plan(only_player: str | None = None) -> dict:
    cfg_full = json.loads(WATCHLIST.read_text())
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    own = (cfg.get("seller_username") or "harpua2001")
    token = promote.get_app_token(cfg)

    threshold = float(cfg_full.get("deal_threshold_pct", 25))
    min_comps = int(cfg_full.get("min_comps_for_median", 8))

    players_out = []
    for p in cfg_full.get("players", []):
        if only_player and p["name"].lower() != only_player.lower():
            continue
        print(f"  → {p['name']} ({p.get('team','')})")
        buckets = []
        for q in p.get("queries", []):
            items = _search(token, q["q"], q.get("min", 5), q.get("max", 0), own)
            grade = q.get("grade", "")
            items = [i for i in items if _grade_match(i["title"], grade)]
            if not items:
                buckets.append({**q, "items": [], "median": None,
                                "n": 0, "deals_below_pct": threshold})
                continue
            prices = sorted(i["price"] for i in items)
            med = statistics.median(prices)
            for it in items:
                disc = (1 - it["price"] / med) * 100 if med else 0
                it["discount_pct"] = round(disc, 1)
                it["is_deal"]      = disc >= threshold and len(items) >= min_comps
            items.sort(key=lambda x: x["price"])
            buckets.append({
                **q,
                "items":   items,
                "median":  round(med, 2),
                "min":     prices[0],
                "max":     prices[-1],
                "n":       len(items),
                "n_deals": sum(1 for i in items if i["is_deal"]),
            })
        players_out.append({**p, "buckets": buckets})

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold_pct": threshold,
        "min_comps":    min_comps,
        "players":      players_out,
    }


def save_plan(plan: dict) -> Path:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    threshold = plan["threshold_pct"]
    players = plan["players"]
    total_deals = sum(b["n_deals"] for p in players for b in p["buckets"]
                      if isinstance(b.get("n_deals"), int))
    total_listings = sum(b["n"] for p in players for b in p["buckets"])

    # KPI strip
    kpis = f"""
    <div class="wl-kpis">
      <div class="wl-kpi">
        <div class="wl-kpi-n">{len(players)}</div>
        <div class="wl-kpi-l">Players watched</div>
      </div>
      <div class="wl-kpi">
        <div class="wl-kpi-n">{total_listings}</div>
        <div class="wl-kpi-l">Live listings scanned</div>
      </div>
      <div class="wl-kpi">
        <div class="wl-kpi-n">{total_deals}</div>
        <div class="wl-kpi-l">Deals ≥ {threshold:.0f}% below median</div>
      </div>
      <div class="wl-kpi">
        <div class="wl-kpi-n">{datetime.now().strftime('%H:%M')}</div>
        <div class="wl-kpi-l">Last refreshed (UTC)</div>
      </div>
    </div>
    """

    # Filter bar (client-side)
    filter_bar = """
    <div class="wl-filters">
      <input type="search" id="wl-q" placeholder="Filter cards by keyword (set, parallel, year…)" class="search-input" autocomplete="off" style="flex:1 1 260px;min-width:0;">
      <select id="wl-grade">
        <option value="all">All grades</option>
        <option value="psa">PSA 10 only</option>
        <option value="raw">Raw only</option>
      </select>
      <select id="wl-sort">
        <option value="discount">Biggest discount first</option>
        <option value="price-asc">Lowest price first</option>
        <option value="price-desc">Highest price first</option>
      </select>
      <label class="wl-chk"><input type="checkbox" id="wl-deals-only"> Deals only</label>
      <span id="wl-count" class="wl-count"></span>
    </div>
    """

    # Per-player sections
    player_sections = []
    for p in players:
        slug = _slugify(p["name"])
        bucket_blocks = []
        for b in p["buckets"]:
            if not b.get("items"):
                bucket_blocks.append(f"""
                <div class="wl-bucket wl-empty">
                  <div class="wl-bucket-head">
                    <h4>{_esc(b['q'])} <span class="wl-grade">{_esc(b.get('grade',''))}</span></h4>
                    <span class="wl-hint">No live listings in ${b.get('min',0):.0f}–${b.get('max',0):.0f} range.</span>
                  </div>
                </div>""")
                continue
            cards = []
            for it in b["items"]:
                deal_class = " is-deal" if it["is_deal"] else ""
                buy_chips = " · ".join(
                    "🔨 Auction" if x == "AUCTION" else
                    "💰 BIN"     if x == "FIXED_PRICE" else
                    "🤝 Best Offer" if x == "BEST_OFFER" else
                    _esc(x)
                    for x in it["buying"]
                )
                disc_badge = (f'<span class="wl-disc">-{it["discount_pct"]:.0f}%</span>'
                              if it["discount_pct"] > 0 else "")
                cards.append(f"""
                <a class="wl-card{deal_class}"
                   href="{_esc(it['url'])}" target="_blank" rel="noopener"
                   data-price="{it['price']:.2f}"
                   data-discount="{it['discount_pct']:.2f}"
                   data-deal="{1 if it['is_deal'] else 0}"
                   data-grade="{'psa' if 'psa 10' in it['title'].lower() else 'raw'}"
                   data-search="{_esc(it['title'].lower())}">
                  <div class="wl-img" style="background-image:url('{_esc(it['image'])}');"></div>
                  <div class="wl-meta">
                    <div class="wl-price-row">
                      <span class="wl-price">${it['price']:.2f}</span>
                      {disc_badge}
                    </div>
                    <div class="wl-title">{_esc(it['title'][:80])}</div>
                    <div class="wl-buying">{buy_chips}</div>
                  </div>
                </a>""")
            med_str = f"${b['median']:.2f}" if b.get("median") else "—"
            bucket_blocks.append(f"""
            <div class="wl-bucket">
              <div class="wl-bucket-head">
                <h4>{_esc(b['q'])} <span class="wl-grade">{_esc(b.get('grade',''))}</span></h4>
                <span class="wl-stats">
                  median {med_str} · range ${b.get('min',0):.2f}–${b.get('max',0):.2f} ·
                  <b>{b['n_deals']}</b> deals / {b['n']} listings
                </span>
              </div>
              <div class="wl-grid">{''.join(cards)}</div>
            </div>""")

        player_sections.append(f"""
        <section class="wl-section" id="player-{slug}" data-player="{_esc(p['name'])}">
          <div class="wl-section-head">
            <h2>{_esc(p['name'])}
              <span class="wl-team">{_esc(p.get('team',''))} · {_esc(p.get('position',''))} · '{p.get('rookie_year',0)%100:02d} RC</span>
            </h2>
            <p class="wl-notes">{_esc(p.get('notes',''))}</p>
          </div>
          {''.join(bucket_blocks)}
        </section>""")

    # JS — client-side filter
    script = """
    <script>
      (function () {
        const q       = document.getElementById('wl-q');
        const grade   = document.getElementById('wl-grade');
        const sort    = document.getElementById('wl-sort');
        const dealsCB = document.getElementById('wl-deals-only');
        const count   = document.getElementById('wl-count');
        const cards   = Array.from(document.querySelectorAll('.wl-card'));

        function apply() {
          const qv = (q.value || '').toLowerCase().trim();
          const gv = grade.value;
          const dealsOnly = dealsCB.checked;
          let shown = 0;
          cards.forEach(c => {
            const hay   = c.dataset.search || '';
            const cg    = c.dataset.grade  || '';
            const isDeal = c.dataset.deal === '1';
            const okQ   = !qv || hay.includes(qv);
            const okG   = gv === 'all' || cg === gv;
            const okD   = !dealsOnly || isDeal;
            const show  = okQ && okG && okD;
            c.style.display = show ? '' : 'none';
            if (show) shown++;
          });
          count.textContent = shown + ' / ' + cards.length + ' shown';

          // Sort within each grid.
          document.querySelectorAll('.wl-grid').forEach(grid => {
            const items = Array.from(grid.querySelectorAll('.wl-card')).filter(c => c.style.display !== 'none');
            items.sort((a, b) => {
              const ap = parseFloat(a.dataset.price)    || 0;
              const bp = parseFloat(b.dataset.price)    || 0;
              const ad = parseFloat(a.dataset.discount) || 0;
              const bd = parseFloat(b.dataset.discount) || 0;
              switch (sort.value) {
                case 'price-asc':  return ap - bp;
                case 'price-desc': return bp - ap;
                default:           return bd - ad;
              }
            });
            items.forEach(c => grid.appendChild(c));
          });
        }
        [q, grade, sort, dealsCB].forEach(el => el && el.addEventListener('input', apply));
        [q, grade, sort, dealsCB].forEach(el => el && el.addEventListener('change', apply));
        apply();
      })();
    </script>
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">My collection · live eBay scan</div>
        <h1 class="section-title">My <span class="accent">Wants</span></h1>
        <div class="section-sub">
          Live deals on the players I'm collecting — Browse API refreshes on every site rebuild.
          A "deal" = ≥{threshold:.0f}% below the median of comparable live listings (min {plan['min_comps']} comps).
          Edit <code>buyer_watchlist.json</code> to add or remove players.
        </div>
      </div>
    </div>

    {kpis}
    {filter_bar}

    {''.join(player_sections)}

    {script}
    """

    extra_css = """
<style>
  .wl-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 12px; margin: 22px 0; }
  .wl-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 16px 18px; }
  .wl-kpi-n { font-family: 'Bebas Neue', sans-serif; font-size: 40px; color: var(--gold); line-height: 1; }
  .wl-kpi-l { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .1em; margin-top: 6px; }
  .wl-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 12px 14px; margin: 18px 0 24px; position: sticky; top: 64px; z-index: 5; backdrop-filter: blur(8px); }
  .wl-filters select { padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; font-size: 13px; }
  .wl-chk { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 13px; cursor: pointer; }
  .wl-count { margin-left: auto; color: var(--text-muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; }
  .wl-section { margin: 32px 0; }
  .wl-section-head { margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .wl-section-head h2 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 36px; letter-spacing: .02em; }
  .wl-team { color: var(--text-muted); font-size: 13px; font-family: 'Inter', sans-serif; letter-spacing: .04em; font-weight: 400; margin-left: 10px; }
  .wl-notes { color: var(--text-muted); font-size: 13px; margin: 4px 0 0; }
  .wl-bucket { margin: 22px 0; }
  .wl-bucket-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 10px; }
  .wl-bucket-head h4 { margin: 0; font-size: 15px; color: var(--text); font-weight: 600; }
  .wl-grade { color: var(--gold); font-size: 11px; text-transform: uppercase; letter-spacing: .1em; margin-left: 6px; }
  .wl-stats { color: var(--text-muted); font-size: 12px; }
  .wl-stats b { color: var(--success); font-weight: 700; }
  .wl-hint { color: var(--text-dim); font-size: 12px; }
  .wl-empty { padding: 8px 0; }
  .wl-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; }
  .wl-card { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
  .wl-card:hover { transform: translateY(-2px); border-color: var(--gold); box-shadow: 0 8px 24px rgba(0,0,0,.25); }
  .wl-card.is-deal { border-left: 3px solid var(--success); }
  .wl-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }
  .wl-meta { padding: 10px 12px; }
  .wl-price-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
  .wl-price { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--gold); }
  .wl-disc { background: rgba(127,199,122,.15); color: var(--success); border: 1px solid rgba(127,199,122,.3); border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; }
  .wl-title { font-size: 12px; line-height: 1.4; color: var(--text); min-height: 32px; }
  .wl-buying { font-size: 10px; color: var(--text-muted); margin-top: 6px; letter-spacing: .04em; }
  @media (max-width: 640px) {
    .wl-grid { grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 8px; }
    .wl-filters { position: static; }
  }
</style>
"""

    html_doc = promote.html_shell("My Wants · Harpua2001", body,
                                  extra_head=extra_css,
                                  active_page="collect.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html_doc, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Nav registration                                                            #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    """Inject 'My Wants' link into promote._NAV_ITEMS at runtime. The
    persistent entry should be added to promote.py separately."""
    entry = ("collect.html", "My Wants", False, "Insights")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "seller_hub.html":
            items.insert(idx, entry)
            break
    else:
        items.append(entry)
    promote._NAV_ITEMS = items
    promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--player", help="Narrow to a single player by name.")
    args = ap.parse_args()

    ensure_nav_entry()
    plan = build_plan(only_player=args.player)
    save_plan(plan)
    out = render_report(plan)

    total = sum(b["n"] for p in plan["players"] for b in p["buckets"])
    deals = sum(b.get("n_deals", 0) for p in plan["players"] for b in p["buckets"])
    print(f"  Players: {len(plan['players'])}  ·  Listings scanned: {total}  ·  Deals: {deals}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Report: {out}")


if __name__ == "__main__":
    main()
