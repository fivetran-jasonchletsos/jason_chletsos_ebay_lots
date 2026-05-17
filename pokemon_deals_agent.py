"""
pokemon_deals_agent.py — Pikachu deal-hunter for the family page.

Reads pokemon_queries.json (a list of Pikachu search buckets), hits the
eBay Browse API for each, computes a median per bucket, flags items
≥25% below median as deals (min 6 comps), and renders
docs/pikachu.html — a kid-friendly card grid with filter UI.

Output:
  output/pokemon_pikachu_plan.json    structured plan
  docs/pikachu.html                   buyer page

CLI:
  python3 pokemon_deals_agent.py
  python3 pokemon_deals_agent.py --bucket "Vintage Holo Pikachu"   # one bucket only
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
QUERIES     = REPO_ROOT / "pokemon_queries.json"
PLAN_PATH   = REPO_ROOT / "output" / "pokemon_pikachu_plan.json"
REPORT_PATH = REPO_ROOT / "docs" / "pikachu.html"
BROWSE_URL  = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# --------------------------------------------------------------------------- #
# Search                                                                       #
# --------------------------------------------------------------------------- #

def _search(token: str, q: str, min_price: float, max_price: float,
            own: str, require_text: str | None = None) -> list[dict]:
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
    out: list[dict] = []
    seen_ids: set[str] = set()
    for it in items:
        seller = ((it.get("seller") or {}).get("username") or "").lower()
        if seller == own.lower():
            continue
        title = it.get("title") or ""
        if require_text and require_text.lower() not in title.lower():
            continue
        try:
            price = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        iid = (it.get("itemId") or "").split("|")[-1]
        if iid in seen_ids:
            continue
        seen_ids.add(iid)
        out.append({
            "item_id":   iid,
            "title":     title,
            "price":     price,
            "url":       it.get("itemWebUrl") or "",
            "image":     ((it.get("image") or {}).get("imageUrl")) or "",
            "buying":    it.get("buyingOptions", []) or [],
            "seller":    seller,
            "condition": it.get("condition") or "",
        })
    return out


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

def build_plan(only_bucket: str | None = None) -> dict:
    cfg_full = json.loads(QUERIES.read_text())
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    own = cfg.get("seller_username") or "harpua2001"
    token = promote.get_app_token(cfg)

    threshold = float(cfg_full.get("deal_threshold_pct", 25))
    min_comps = int(cfg_full.get("min_comps_for_median", 6))

    buckets_out = []
    for b in cfg_full.get("buckets", []):
        if only_bucket and b["label"].lower() != only_bucket.lower():
            continue
        print(f"  → {b['label']}")
        all_items: list[dict] = []
        seen_ids: set[str] = set()
        for q in b["queries"]:
            for it in _search(token, q,
                              b.get("min", 5), b.get("max", 0),
                              own, b.get("require_text")):
                if it["item_id"] in seen_ids:
                    continue
                seen_ids.add(it["item_id"])
                all_items.append(it)
        if not all_items:
            buckets_out.append({**b, "items": [], "median": None, "n": 0, "n_deals": 0})
            continue
        prices = sorted(i["price"] for i in all_items)
        med = statistics.median(prices)
        for it in all_items:
            disc = (1 - it["price"] / med) * 100 if med else 0
            it["discount_pct"] = round(disc, 1)
            it["is_deal"] = disc >= threshold and len(all_items) >= min_comps
        all_items.sort(key=lambda x: -x["discount_pct"])
        buckets_out.append({
            **b,
            "items":   all_items,
            "median":  round(med, 2),
            "lo":      prices[0],
            "hi":      prices[-1],
            "n":       len(all_items),
            "n_deals": sum(1 for i in all_items if i["is_deal"]),
        })

    return {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "threshold_pct": threshold,
        "min_comps":     min_comps,
        "buckets":       buckets_out,
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


_EMOJI_DOT = {
    "vintage": "VINTAGE",
    "surf":    "SURF",
    "go":      "GO!",
    "vmax":    "VMAX",
    "ex":      "ex",
    "promo":   "PROMO",
    "psa":     "PSA 10",
}


def render_report(plan: dict) -> Path:
    threshold = plan["threshold_pct"]
    buckets = plan["buckets"]
    total_listings = sum(b["n"] for b in buckets)
    total_deals    = sum(b["n_deals"] for b in buckets)

    # ---- Grail Watch — most expensive Pikachus across the WHOLE scan,
    # not just the grail bucket. A $1,200 Base Set holo from the Vintage
    # bucket belongs in Grail Watch even if it didn't come from a grail query.
    # Dedupe by item_id (a card might appear in multiple buckets).
    grail_pool: dict[str, dict] = {}
    for b in buckets:
        for it in b["items"]:
            grail_pool[it["item_id"]] = it
    grail_strip = sorted(grail_pool.values(), key=lambda x: -x["price"])[:6]

    grail_html = ""
    if grail_strip:
        cards = []
        for it in grail_strip:
            cards.append(f"""
            <a class="pk-grail-card" href="{_esc(it['url'])}" target="_blank" rel="noopener">
              <div class="pk-grail-badge">LEGENDARY</div>
              <div class="pk-grail-img" style="background-image:url('{_esc(it['image'])}');"></div>
              <div class="pk-grail-meta">
                <div class="pk-grail-price">${it['price']:,.0f}</div>
                <div class="pk-grail-title">{_esc(it['title'][:64])}</div>
              </div>
            </a>""")
        grail_html = f"""
        <section class="pk-grail">
          <div class="pk-grail-head">
            <h2>Grail Watch</h2>
            <span class="pk-grail-sub">The legends. Cards built from dreams. Click to gawk.</span>
          </div>
          <div class="pk-grail-grid">{''.join(cards)}</div>
        </section>"""

    # ---- Hero strip: hottest deals (skip grails — those go in their own section) ---- #
    best_deals = sorted(
        (it for b in buckets if b.get("kind") != "grail" for it in b["items"] if it["is_deal"]),
        key=lambda x: -x["discount_pct"]
    )[:6]
    hero_cards = []
    for it in best_deals:
        hero_cards.append(f"""
        <a class="pk-hero-card" href="{_esc(it['url'])}" target="_blank" rel="noopener"
           title="{_esc(it['title'])}">
          <div class="pk-hero-img" style="background-image:url('{_esc(it['image'])}');"></div>
          <div class="pk-hero-meta">
            <span class="pk-hero-price">${it['price']:.2f}</span>
            <span class="pk-hero-disc">-{it['discount_pct']:.0f}%</span>
          </div>
        </a>""")
    hero_html = (f"""
    <section class="pk-hero">
      <div class="pk-hero-head">
        <h2>Hottest Deals Right Now</h2>
        <span class="pk-hero-sub">Biggest discounts vs. median across every bucket.</span>
      </div>
      <div class="pk-hero-grid">{''.join(hero_cards)}</div>
    </section>"""
                 if best_deals else "")

    # ---- KPI strip ---- #
    kpis = f"""
    <div class="pk-kpis">
      <div class="pk-kpi"><div class="pk-n">{len(buckets)}</div><div class="pk-l">Categories</div></div>
      <div class="pk-kpi"><div class="pk-n">{total_listings}</div><div class="pk-l">Live listings</div></div>
      <div class="pk-kpi"><div class="pk-n">{total_deals}</div><div class="pk-l">Deals ≥{threshold:.0f}% below median</div></div>
      <div class="pk-kpi"><div class="pk-n">{datetime.now().strftime('%H:%M')}</div><div class="pk-l">Last refreshed (local)</div></div>
    </div>
    """

    # ---- Filter bar ---- #
    bucket_options = "".join(
        f'<option value="{_esc(b["label"])}">{_esc(b["label"])} ({b["n"]})</option>'
        for b in buckets
    )
    filter_bar = f"""
    <div class="pk-filters">
      <input type="search" id="pk-q" class="search-input"
             placeholder="Search card name, set, parallel…" autocomplete="off"
             style="flex:1 1 240px; min-width:0;">
      <select id="pk-bucket">
        <option value="all">All categories</option>
        {bucket_options}
      </select>
      <select id="pk-max">
        <option value="0">Any price</option>
        <option value="10">Under $10</option>
        <option value="25">Under $25</option>
        <option value="50">Under $50</option>
        <option value="100">Under $100</option>
      </select>
      <select id="pk-sort">
        <option value="discount">Biggest discount</option>
        <option value="price-asc">Lowest price</option>
        <option value="price-desc">Highest price</option>
      </select>
      <label class="pk-chk"><input type="checkbox" id="pk-deals"> Deals only</label>
      <span id="pk-count" class="pk-count"></span>
    </div>
    """

    # ---- Per-bucket sections ---- #
    KIND_TAG = {
        "grail":         "LEGENDARY",
        "vintage":       "VINTAGE",
        "promo":         "PROMO",
        "tournament":    "TOURNAMENT",
        "international": "JAPANESE",
        "modern":        "MODERN",
        "sealed":        "SEALED",
        "graded":        "PSA 10",
    }
    sections = []
    for b in buckets:
        # Grail bucket already rendered in its own hero — skip here to avoid double-display.
        if b.get("kind") == "grail":
            continue
        slug = re.sub(r"[^a-z0-9]+", "-", b["label"].lower()).strip("-")
        kind = b.get("kind", "")
        tag  = KIND_TAG.get(kind, "")
        if not b.get("items"):
            sections.append(f"""
            <section class="pk-bucket" id="b-{slug}" data-bucket="{_esc(b['label'])}">
              <div class="pk-bucket-head">
                <h3>{_esc(b['label'])} <span class="pk-tag pk-tag-{kind}">{tag}</span></h3>
                <p class="pk-blurb">{_esc(b.get('blurb',''))}</p>
                <span class="pk-stats">No live listings in ${b.get('min',0):.0f}–${b.get('max',0):.0f}.</span>
              </div>
            </section>""")
            continue
        # Sort: deals first, then cheapest first within group
        items_sorted = sorted(b["items"], key=lambda x: (not x["is_deal"], x["price"]))
        cards = []
        for it in items_sorted:
            deal_cls = " is-deal" if it["is_deal"] else ""
            buying = " · ".join(
                "BIN" if x == "FIXED_PRICE" else
                "Auction" if x == "AUCTION" else
                "Best Offer" if x == "BEST_OFFER" else _esc(x)
                for x in it["buying"]
            )
            disc_badge = (f'<span class="pk-disc">-{it["discount_pct"]:.0f}%</span>'
                          if it["discount_pct"] > 0 else "")
            cards.append(f"""
            <a class="pk-card{deal_cls}" href="{_esc(it['url'])}" target="_blank" rel="noopener"
               data-price="{it['price']:.2f}"
               data-discount="{it['discount_pct']:.2f}"
               data-deal="{1 if it['is_deal'] else 0}"
               data-bucket="{_esc(b['label'])}"
               data-search="{_esc(it['title'].lower())}">
              <div class="pk-img" style="background-image:url('{_esc(it['image'])}');"></div>
              <div class="pk-meta">
                <div class="pk-price-row">
                  <span class="pk-price">${it['price']:.2f}</span>
                  {disc_badge}
                </div>
                <div class="pk-title">{_esc(it['title'][:84])}</div>
                <div class="pk-buying">{buying}</div>
              </div>
            </a>""")
        sections.append(f"""
        <section class="pk-bucket" id="b-{slug}" data-bucket="{_esc(b['label'])}">
          <div class="pk-bucket-head">
            <div class="pk-bucket-title">
              <h3>{_esc(b['label'])} <span class="pk-tag pk-tag-{kind}">{tag}</span></h3>
              <p class="pk-blurb">{_esc(b.get('blurb',''))}</p>
            </div>
            <div class="pk-bucket-stats">
              <div class="pk-stat"><div class="pk-stat-n">${b['lo']:.0f}</div><div class="pk-stat-l">Cheapest</div></div>
              <div class="pk-stat"><div class="pk-stat-n">${b['median']:.0f}</div><div class="pk-stat-l">Median</div></div>
              <div class="pk-stat"><div class="pk-stat-n">${b['hi']:.0f}</div><div class="pk-stat-l">Highest</div></div>
              <div class="pk-stat"><div class="pk-stat-n" style="color:var(--success);">{b['n_deals']}</div><div class="pk-stat-l">Deals / {b['n']}</div></div>
            </div>
          </div>
          <div class="pk-grid">{''.join(cards)}</div>
        </section>""")

    # ---- JS — client-side filter ---- #
    script = """
    <script>
      (function () {
        const q     = document.getElementById('pk-q');
        const bk    = document.getElementById('pk-bucket');
        const mx    = document.getElementById('pk-max');
        const srt   = document.getElementById('pk-sort');
        const deals = document.getElementById('pk-deals');
        const count = document.getElementById('pk-count');
        const cards = Array.from(document.querySelectorAll('.pk-card'));

        function apply() {
          const qv = (q.value || '').toLowerCase().trim();
          const bv = bk.value;
          const mxv = parseFloat(mx.value) || 0;
          const dealsOnly = deals.checked;
          let shown = 0;
          cards.forEach(c => {
            const hay   = c.dataset.search || '';
            const bucket = c.dataset.bucket || '';
            const price = parseFloat(c.dataset.price) || 0;
            const isDeal = c.dataset.deal === '1';
            const okQ  = !qv || hay.includes(qv);
            const okB  = bv === 'all' || bucket === bv;
            const okMx = mxv === 0 || price <= mxv;
            const okD  = !dealsOnly || isDeal;
            const show = okQ && okB && okMx && okD;
            c.style.display = show ? '' : 'none';
            if (show) shown++;
          });
          count.textContent = shown + ' / ' + cards.length + ' shown';

          // Sort within each grid
          document.querySelectorAll('.pk-grid').forEach(grid => {
            const items = Array.from(grid.querySelectorAll('.pk-card')).filter(c => c.style.display !== 'none');
            items.sort((a, b) => {
              const ap = parseFloat(a.dataset.price)    || 0;
              const bp = parseFloat(b.dataset.price)    || 0;
              const ad = parseFloat(a.dataset.discount) || 0;
              const bd = parseFloat(b.dataset.discount) || 0;
              switch (srt.value) {
                case 'price-asc':  return ap - bp;
                case 'price-desc': return bp - ap;
                default:           return bd - ad;
              }
            });
            items.forEach(c => grid.appendChild(c));
          });

          // Hide empty bucket sections after filtering
          document.querySelectorAll('.pk-bucket').forEach(section => {
            const grid = section.querySelector('.pk-grid');
            if (!grid) return;
            const visible = grid.querySelectorAll('.pk-card[style=""], .pk-card:not([style])').length;
            section.style.display = visible || (bv === 'all' && !qv && !dealsOnly && mxv === 0) ? '' : 'none';
          });
        }
        [q, bk, mx, srt, deals].forEach(el => el && el.addEventListener('input', apply));
        [q, bk, mx, srt, deals].forEach(el => el && el.addEventListener('change', apply));
        apply();
      })();
    </script>
    """

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Pokemon · live eBay scan</div>
        <h1 class="section-title">Pikachu <span class="accent">Hunt</span></h1>
        <div class="section-sub">
          Live Pikachu deals for my son — every category, every grade, sorted by biggest discount.
          A "deal" = ≥{threshold:.0f}% below the median of that bucket (min {plan['min_comps']} comps).
          Edit <code>pokemon_queries.json</code> to add or tweak buckets.
        </div>
      </div>
    </div>

    {kpis}
    {grail_html}
    {hero_html}
    {filter_bar}

    {''.join(sections)}

    {script}
    """

    extra_css = """
<style>
  .pk-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 22px 0; }
  .pk-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 16px 18px; border-left: 3px solid #ffcc00; }
  .pk-n { font-family: 'Bebas Neue', sans-serif; font-size: 40px; color: #ffcc00; line-height: 1; }
  .pk-l { color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .1em; margin-top: 6px; }

  /* GRAIL WATCH — legendary cards (Illustrator, Trophy, 1st Ed Shadowless) */
  .pk-grail { position: relative; background: linear-gradient(135deg, rgba(212,175,55,.12), rgba(255,140,0,.08), rgba(212,175,55,.12)); border: 1px solid rgba(212,175,55,.4); border-radius: var(--r-md); padding: 22px; margin: 22px 0 28px; overflow: hidden; }
  .pk-grail::before { content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 50% 0%, rgba(212,175,55,.18), transparent 60%); pointer-events: none; }
  .pk-grail-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; position: relative; }
  .pk-grail-head h2 { margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 40px; color: #d4af37; letter-spacing: .04em; text-shadow: 0 2px 8px rgba(212,175,55,.4); }
  .pk-grail-sub { color: #e0d8b5; font-size: 13px; font-style: italic; }
  .pk-grail-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; position: relative; }
  .pk-grail-card { display: block; position: relative; background: #14110a; border: 2px solid rgba(212,175,55,.5); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease; }
  .pk-grail-card:hover { transform: translateY(-4px) scale(1.02); border-color: #d4af37; box-shadow: 0 12px 40px rgba(212,175,55,.4); }
  .pk-grail-badge { position: absolute; top: 8px; left: 8px; background: #d4af37; color: #1a1500; font-size: 9px; font-weight: 900; letter-spacing: .15em; padding: 3px 8px; border-radius: 4px; z-index: 2; box-shadow: 0 2px 8px rgba(0,0,0,.4); }
  .pk-grail-img { aspect-ratio: 3 / 4; background-size: cover; background-position: center; background-color: #0a0907; }
  .pk-grail-meta { padding: 12px 14px; background: linear-gradient(180deg, transparent, rgba(212,175,55,.08)); }
  .pk-grail-price { font-family: 'Bebas Neue', sans-serif; font-size: 26px; color: #d4af37; line-height: 1; text-shadow: 0 1px 4px rgba(0,0,0,.5); }
  .pk-grail-title { font-size: 11px; line-height: 1.4; color: #c9c2a7; margin-top: 4px; min-height: 30px; }

  /* Hero strip — top 6 hottest deals */
  .pk-hero { background: linear-gradient(180deg, rgba(255,204,0,.06), transparent); border: 1px solid rgba(255,204,0,.15); border-radius: var(--r-md); padding: 18px; margin: 18px 0 24px; }
  .pk-hero-head { display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .pk-hero-head h2 { margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: #ffcc00; letter-spacing: .03em; }
  .pk-hero-sub { color: var(--text-muted); font-size: 13px; }
  .pk-hero-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }
  .pk-hero-card { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }
  .pk-hero-card:hover { transform: translateY(-3px); border-color: #ffcc00; box-shadow: 0 8px 26px rgba(255,204,0,.15); }
  .pk-hero-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }
  .pk-hero-meta { padding: 8px 10px; display: flex; justify-content: space-between; align-items: baseline; }
  .pk-hero-price { font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: #ffcc00; }
  .pk-hero-disc { color: var(--success); font-size: 11px; font-weight: 700; }

  /* Filter bar */
  .pk-filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 12px 14px; margin: 18px 0 24px; position: sticky; top: 64px; z-index: 5; backdrop-filter: blur(8px); }
  .pk-filters select { padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; font-size: 13px; }
  .pk-chk { display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 13px; cursor: pointer; }
  .pk-count { margin-left: auto; color: var(--text-muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; }

  /* Per-bucket header — stats bar to the right */
  .pk-bucket { margin: 36px 0; }
  .pk-bucket-head { display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }
  .pk-bucket-title h3 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 32px; letter-spacing: .02em; }
  .pk-tag { font-size: 10px; border-radius: 999px; padding: 3px 9px; margin-left: 10px; letter-spacing: .12em; font-weight: 700; }
  .pk-tag-vintage       { color: #c98a4d; background: rgba(201,138,77,.12);  border: 1px solid rgba(201,138,77,.35); }
  .pk-tag-promo         { color: #e07b6f; background: rgba(224,123,111,.12); border: 1px solid rgba(224,123,111,.35); }
  .pk-tag-tournament    { color: #d4af37; background: rgba(212,175,55,.12);  border: 1px solid rgba(212,175,55,.4); }
  .pk-tag-international { color: #ff6b6b; background: rgba(255,107,107,.1);  border: 1px solid rgba(255,107,107,.35); }
  .pk-tag-modern        { color: #ffcc00; background: rgba(255,204,0,.1);    border: 1px solid rgba(255,204,0,.3); }
  .pk-tag-sealed        { color: #7fc77a; background: rgba(127,199,122,.12); border: 1px solid rgba(127,199,122,.35); }
  .pk-tag-graded        { color: #6cb0ff; background: rgba(108,176,255,.12); border: 1px solid rgba(108,176,255,.35); }
  .pk-blurb { color: var(--text-muted); font-size: 13px; margin: 4px 0 0; max-width: 60ch; }

  .pk-bucket-stats { display: grid; grid-template-columns: repeat(4, auto); gap: 14px; }
  .pk-stat { text-align: center; min-width: 56px; }
  .pk-stat-n { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--text); line-height: 1; }
  .pk-stat-l { font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }

  /* Bigger card grid (was 200px → 220px) + Pokemon-card aspect ratio */
  .pk-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; }
  .pk-card { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease; position: relative; }
  .pk-card:hover { transform: translateY(-3px) scale(1.025); border-color: #ffcc00; box-shadow: 0 10px 28px rgba(255,204,0,.22); z-index: 2; }
  .pk-card.is-deal { border-left: 3px solid var(--success); }
  .pk-card.is-deal::after { content: "DEAL"; position: absolute; top: 8px; right: 8px; background: var(--success); color: #0a0a0a; font-size: 9px; font-weight: 900; letter-spacing: .15em; padding: 3px 7px; border-radius: 4px; z-index: 2; }
  .pk-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); transition: transform .25s ease; }
  .pk-card:hover .pk-img { transform: scale(1.05); }
  .pk-meta { padding: 10px 12px; }
  .pk-price-row { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }
  .pk-price { font-family: 'Bebas Neue', sans-serif; font-size: 24px; color: #ffcc00; }
  .pk-disc { background: rgba(127,199,122,.15); color: var(--success); border: 1px solid rgba(127,199,122,.3); border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; }
  .pk-title { font-size: 12px; line-height: 1.4; color: var(--text); min-height: 32px; }
  .pk-buying { font-size: 10px; color: var(--text-muted); margin-top: 6px; letter-spacing: .04em; }
  @media (max-width: 640px) {
    .pk-grid { grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }
    .pk-hero-grid { grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }
    .pk-grail-grid { grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }
    .pk-bucket-head { grid-template-columns: 1fr; }
    .pk-bucket-stats { grid-template-columns: repeat(4, 1fr); width: 100%; }
    .pk-filters { position: static; }
  }
</style>
"""

    html_doc = promote.html_shell("Pikachu Hunt · For My Son", body,
                                  extra_head=extra_css,
                                  active_page="pikachu.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html_doc, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Nav registration (runtime — persist via promote._NAV_ITEMS edit)            #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    entry = ("pikachu.html", "Pikachu", False, "Insights")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "collect.html":
            items.insert(idx + 1, entry)
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
    ap.add_argument("--bucket", help="Narrow to a single bucket label.")
    args = ap.parse_args()

    ensure_nav_entry()
    plan = build_plan(only_bucket=args.bucket)
    save_plan(plan)
    out = render_report(plan)

    total = sum(b["n"] for b in plan["buckets"])
    deals = sum(b["n_deals"] for b in plan["buckets"])
    print(f"  Buckets: {len(plan['buckets'])}  ·  Listings: {total}  ·  Deals: {deals}")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Report: {out}")


if __name__ == "__main__":
    main()
