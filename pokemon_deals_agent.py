"""
pokemon_deals_agent.py — multi-character Pokemon deal-hunter for the family page.

Reads pokemon_characters.json (a list of characters, each with their own search
buckets) and for each character:
  • Hits the eBay Browse API for every query in every bucket
  • Computes a median per bucket, flags items >=25% below median as deals (min 6 comps)
  • Renders docs/{slug}.html — a kid-friendly card grid with filter UI
  • Saves output/pokemon_{slug}_plan.json

Also renders docs/pokemon.html — a landing tile-grid linking to every character.

Legacy fallback: if pokemon_characters.json does not exist, falls back to
pokemon_queries.json and renders just docs/pikachu.html.

CLI:
  python3 pokemon_deals_agent.py
  python3 pokemon_deals_agent.py --character charizard
  python3 pokemon_deals_agent.py --bucket "Vintage Holo"   # one bucket across all chars
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

REPO_ROOT       = Path(__file__).parent
CHARACTERS_FILE = REPO_ROOT / "pokemon_characters.json"
LEGACY_QUERIES  = REPO_ROOT / "pokemon_queries.json"
OUTPUT_DIR      = REPO_ROOT / "output"
DOCS_DIR        = REPO_ROOT / "docs"
BROWSE_URL      = "https://api.ebay.com/buy/browse/v1/item_summary/search"


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
# Config loading                                                               #
# --------------------------------------------------------------------------- #

def load_characters() -> dict:
    """Load pokemon_characters.json, or fall back to legacy pokemon_queries.json."""
    if CHARACTERS_FILE.exists():
        return json.loads(CHARACTERS_FILE.read_text())
    # Legacy fallback: wrap pikachu-only config in characters shape
    legacy = json.loads(LEGACY_QUERIES.read_text())
    return {
        "deal_threshold_pct":   legacy.get("deal_threshold_pct", 25),
        "min_comps_for_median": legacy.get("min_comps_for_median", 6),
        "characters": [{
            "slug": "pikachu",
            "name": "Pikachu",
            "color": "#ffcc00",
            "tagline": "The mascot. The icon. The card that built the hobby.",
            "buckets": legacy.get("buckets", []),
        }],
    }


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

def build_plan(character: dict, threshold: float, min_comps: int,
               token: str, own: str, only_bucket: str | None = None) -> dict:
    buckets_out = []
    for b in character.get("buckets", []):
        if only_bucket and b["label"].lower() != only_bucket.lower():
            continue
        print(f"    -> {b['label']}")
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
        "slug":          character["slug"],
        "name":          character["name"],
        "color":         character.get("color", "#ffcc00"),
        "tagline":       character.get("tagline", ""),
        "threshold_pct": threshold,
        "min_comps":     min_comps,
        "buckets":       buckets_out,
    }


def save_plan(plan: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTPUT_DIR / f"pokemon_{plan['slug']}_plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    threshold = plan["threshold_pct"]
    buckets   = plan["buckets"]
    name      = plan["name"]
    slug      = plan["slug"]
    color     = plan.get("color", "#ffcc00")
    tagline   = plan.get("tagline", "")

    total_listings = sum(b["n"] for b in buckets)
    total_deals    = sum(b["n_deals"] for b in buckets)

    # ---- Grail Watch — most expensive cards across the WHOLE scan ---- #
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

    # ---- Hero strip: hottest deals (skip grails) ---- #
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
      <div class="pk-kpi"><div class="pk-n">{total_deals}</div><div class="pk-l">Deals &ge;{threshold:.0f}% below median</div></div>
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
             placeholder="Search card name, set, parallel..." autocomplete="off"
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
        if b.get("kind") == "grail":
            continue
        bslug = re.sub(r"[^a-z0-9]+", "-", b["label"].lower()).strip("-")
        kind = b.get("kind", "")
        tag  = KIND_TAG.get(kind, "")
        if not b.get("items"):
            sections.append(f"""
            <section class="pk-bucket" id="b-{bslug}" data-bucket="{_esc(b['label'])}">
              <div class="pk-bucket-head">
                <h3>{_esc(b['label'])} <span class="pk-tag pk-tag-{kind}">{tag}</span></h3>
                <p class="pk-blurb">{_esc(b.get('blurb',''))}</p>
                <span class="pk-stats">No live listings in ${b.get('min',0):.0f}-${b.get('max',0):.0f}.</span>
              </div>
            </section>""")
            continue
        items_sorted = sorted(b["items"], key=lambda x: (not x["is_deal"], x["price"]))
        cards = []
        for it in items_sorted:
            deal_cls = " is-deal" if it["is_deal"] else ""
            buying = " . ".join(
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
        <section class="pk-bucket" id="b-{bslug}" data-bucket="{_esc(b['label'])}">
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

    # ---- JS ---- #
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

    sub_line = (f"Live {name} deals for my son — every category, every grade, sorted by biggest discount. "
                f"A &quot;deal&quot; = &ge;{threshold:.0f}% below the median of that bucket (min {plan['min_comps']} comps).")
    if tagline:
        sub_line = f"{_esc(tagline)} " + sub_line

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Pokemon &middot; live eBay scan</div>
        <h1 class="section-title">{_esc(name)} <span class="accent">Hunt</span></h1>
        <div class="section-sub">
          {sub_line}
          <br><a href="pokemon.html" style="color:{color};">&larr; Back to all Pokemon</a>
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

    # Compute a darker shade of color for shadow / hover
    extra_css = f"""
<style>
  .pk-kpis {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 12px; margin: 22px 0; }}
  .pk-kpi {{ background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 16px 18px; border-left: 3px solid {color}; }}
  .pk-n {{ font-family: 'Bebas Neue', sans-serif; font-size: 40px; color: {color}; line-height: 1; }}
  .pk-l {{ color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .1em; margin-top: 6px; }}

  /* GRAIL WATCH */
  .pk-grail {{ position: relative; background: linear-gradient(135deg, rgba(212,175,55,.12), rgba(255,140,0,.08), rgba(212,175,55,.12)); border: 1px solid rgba(212,175,55,.4); border-radius: var(--r-md); padding: 22px; margin: 22px 0 28px; overflow: hidden; }}
  .pk-grail::before {{ content: ""; position: absolute; inset: 0; background: radial-gradient(circle at 50% 0%, rgba(212,175,55,.18), transparent 60%); pointer-events: none; }}
  .pk-grail-head {{ display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 16px; position: relative; }}
  .pk-grail-head h2 {{ margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 40px; color: #d4af37; letter-spacing: .04em; text-shadow: 0 2px 8px rgba(212,175,55,.4); }}
  .pk-grail-sub {{ color: #e0d8b5; font-size: 13px; font-style: italic; }}
  .pk-grail-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; position: relative; }}
  .pk-grail-card {{ display: block; position: relative; background: #14110a; border: 2px solid rgba(212,175,55,.5); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .2s ease, border-color .2s ease, box-shadow .2s ease; }}
  .pk-grail-card:hover {{ transform: translateY(-4px) scale(1.02); border-color: #d4af37; box-shadow: 0 12px 40px rgba(212,175,55,.4); }}
  .pk-grail-badge {{ position: absolute; top: 8px; left: 8px; background: #d4af37; color: #1a1500; font-size: 9px; font-weight: 900; letter-spacing: .15em; padding: 3px 8px; border-radius: 4px; z-index: 2; box-shadow: 0 2px 8px rgba(0,0,0,.4); }}
  .pk-grail-img {{ aspect-ratio: 3 / 4; background-size: cover; background-position: center; background-color: #0a0907; }}
  .pk-grail-meta {{ padding: 12px 14px; background: linear-gradient(180deg, transparent, rgba(212,175,55,.08)); }}
  .pk-grail-price {{ font-family: 'Bebas Neue', sans-serif; font-size: 26px; color: #d4af37; line-height: 1; text-shadow: 0 1px 4px rgba(0,0,0,.5); }}
  .pk-grail-title {{ font-size: 11px; line-height: 1.4; color: #c9c2a7; margin-top: 4px; min-height: 30px; }}

  /* Hero strip */
  .pk-hero {{ background: linear-gradient(180deg, rgba(0,0,0,.06), transparent); border: 1px solid {color}26; border-radius: var(--r-md); padding: 18px; margin: 18px 0 24px; }}
  .pk-hero-head {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
  .pk-hero-head h2 {{ margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: {color}; letter-spacing: .03em; }}
  .pk-hero-sub {{ color: var(--text-muted); font-size: 13px; }}
  .pk-hero-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .pk-hero-card {{ display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s ease, border-color .15s ease, box-shadow .15s ease; }}
  .pk-hero-card:hover {{ transform: translateY(-3px); border-color: {color}; box-shadow: 0 8px 26px {color}26; }}
  .pk-hero-img {{ aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }}
  .pk-hero-meta {{ padding: 8px 10px; display: flex; justify-content: space-between; align-items: baseline; }}
  .pk-hero-price {{ font-family: 'Bebas Neue', sans-serif; font-size: 18px; color: {color}; }}
  .pk-hero-disc {{ color: var(--success); font-size: 11px; font-weight: 700; }}

  /* Filter bar */
  .pk-filters {{ display: flex; flex-wrap: wrap; gap: 10px; align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 12px 14px; margin: 18px 0 24px; position: sticky; top: 64px; z-index: 5; backdrop-filter: blur(8px); }}
  .pk-filters select {{ padding: 8px 10px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; font-size: 13px; }}
  .pk-chk {{ display: inline-flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 13px; cursor: pointer; }}
  .pk-count {{ margin-left: auto; color: var(--text-muted); font-size: 12px; letter-spacing: .08em; text-transform: uppercase; font-weight: 700; }}

  /* Per-bucket */
  .pk-bucket {{ margin: 36px 0; }}
  .pk-bucket-head {{ display: grid; grid-template-columns: 1fr auto; gap: 18px; align-items: end; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid var(--border); }}
  .pk-bucket-title h3 {{ margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 32px; letter-spacing: .02em; }}
  .pk-tag {{ font-size: 10px; border-radius: 999px; padding: 3px 9px; margin-left: 10px; letter-spacing: .12em; font-weight: 700; }}
  .pk-tag-vintage       {{ color: #c98a4d; background: rgba(201,138,77,.12);  border: 1px solid rgba(201,138,77,.35); }}
  .pk-tag-promo         {{ color: #e07b6f; background: rgba(224,123,111,.12); border: 1px solid rgba(224,123,111,.35); }}
  .pk-tag-tournament    {{ color: #d4af37; background: rgba(212,175,55,.12);  border: 1px solid rgba(212,175,55,.4); }}
  .pk-tag-international {{ color: #ff6b6b; background: rgba(255,107,107,.1);  border: 1px solid rgba(255,107,107,.35); }}
  .pk-tag-modern        {{ color: {color}; background: {color}1a;    border: 1px solid {color}4d; }}
  .pk-tag-sealed        {{ color: #7fc77a; background: rgba(127,199,122,.12); border: 1px solid rgba(127,199,122,.35); }}
  .pk-tag-graded        {{ color: #6cb0ff; background: rgba(108,176,255,.12); border: 1px solid rgba(108,176,255,.35); }}
  .pk-blurb {{ color: var(--text-muted); font-size: 13px; margin: 4px 0 0; max-width: 60ch; }}

  .pk-bucket-stats {{ display: grid; grid-template-columns: repeat(4, auto); gap: 14px; }}
  .pk-stat {{ text-align: center; min-width: 56px; }}
  .pk-stat-n {{ font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--text); line-height: 1; }}
  .pk-stat-l {{ font-size: 9px; color: var(--text-muted); text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }}

  /* Card grid */
  .pk-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(210px, 1fr)); gap: 14px; }}
  .pk-card {{ display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease; position: relative; }}
  .pk-card:hover {{ transform: translateY(-3px) scale(1.025); border-color: {color}; box-shadow: 0 10px 28px {color}38; z-index: 2; }}
  .pk-card.is-deal {{ border-left: 3px solid var(--success); }}
  .pk-card.is-deal::after {{ content: "DEAL"; position: absolute; top: 8px; right: 8px; background: var(--success); color: #0a0a0a; font-size: 9px; font-weight: 900; letter-spacing: .15em; padding: 3px 7px; border-radius: 4px; z-index: 2; }}
  .pk-img {{ aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); transition: transform .25s ease; }}
  .pk-card:hover .pk-img {{ transform: scale(1.05); }}
  .pk-meta {{ padding: 10px 12px; }}
  .pk-price-row {{ display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 6px; }}
  .pk-price {{ font-family: 'Bebas Neue', sans-serif; font-size: 24px; color: {color}; }}
  .pk-disc {{ background: rgba(127,199,122,.15); color: var(--success); border: 1px solid rgba(127,199,122,.3); border-radius: 999px; padding: 2px 8px; font-size: 11px; font-weight: 700; }}
  .pk-title {{ font-size: 12px; line-height: 1.4; color: var(--text); min-height: 32px; }}
  .pk-buying {{ font-size: 10px; color: var(--text-muted); margin-top: 6px; letter-spacing: .04em; }}
  @media (max-width: 640px) {{
    .pk-grid {{ grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 8px; }}
    .pk-hero-grid {{ grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); }}
    .pk-grail-grid {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); }}
    .pk-bucket-head {{ grid-template-columns: 1fr; }}
    .pk-bucket-stats {{ grid-template-columns: repeat(4, 1fr); width: 100%; }}
    .pk-filters {{ position: static; }}
  }}
</style>
"""

    html_doc = promote.html_shell(f"{name} Hunt &middot; For My Son", body,
                                  extra_head=extra_css,
                                  active_page=f"{slug}.html")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DOCS_DIR / f"{slug}.html"
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------- #
# Landing page: docs/pokemon.html                                              #
# --------------------------------------------------------------------------- #

def render_landing(plans: list[dict]) -> Path:
    """Render docs/pokemon.html — a tile grid with one tile per character."""
    tiles = []
    for p in plans:
        slug   = p["slug"]
        name   = p["name"]
        color  = p.get("color", "#ffcc00")
        n      = sum(b["n"] for b in p["buckets"])
        deals  = sum(b["n_deals"] for b in p["buckets"])
        # Pick a hero image: the most expensive scanned card across all buckets
        all_items = [it for b in p["buckets"] for it in b["items"]]
        hero_img = ""
        if all_items:
            top = max(all_items, key=lambda x: x["price"])
            hero_img = top.get("image", "")
        tiles.append(f"""
        <a class="pmon-tile" href="{slug}.html" style="--accent:{color};">
          <div class="pmon-tile-img" style="background-image:url('{_esc(hero_img)}');"></div>
          <div class="pmon-tile-meta">
            <div class="pmon-tile-name">{_esc(name)}</div>
            <div class="pmon-tile-stats">
              <span class="pmon-tile-n">{n}</span> <span class="pmon-tile-l">listings</span>
              &middot;
              <span class="pmon-tile-n" style="color:var(--success);">{deals}</span> <span class="pmon-tile-l">deals</span>
            </div>
            <div class="pmon-tile-tag">{_esc(p.get('tagline','Click to hunt.'))}</div>
          </div>
        </a>""")

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">Pokemon &middot; live eBay scan</div>
        <h1 class="section-title">Pokemon <span class="accent">Hunt</span></h1>
        <div class="section-sub">
          Pick a Pokemon. Every page is a live scan of eBay: vintage holos, modern alt arts,
          PSA 10s, and grail watch &mdash; sorted by biggest discount vs. median.
        </div>
      </div>
    </div>

    <div class="pmon-grid">
      {''.join(tiles)}
    </div>
    """

    extra_css = """
<style>
  .pmon-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; margin: 24px 0 48px; }
  .pmon-tile { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .18s ease, border-color .18s ease, box-shadow .18s ease; position: relative; }
  .pmon-tile::before { content: ""; position: absolute; top: 0; left: 0; right: 0; height: 4px; background: var(--accent); z-index: 2; }
  .pmon-tile:hover { transform: translateY(-4px) scale(1.02); border-color: var(--accent); box-shadow: 0 14px 36px rgba(0,0,0,.4); }
  .pmon-tile-img { aspect-ratio: 4 / 3; background-size: cover; background-position: center; background-color: var(--surface-2); transition: transform .3s ease; }
  .pmon-tile:hover .pmon-tile-img { transform: scale(1.05); }
  .pmon-tile-meta { padding: 14px 16px 18px; }
  .pmon-tile-name { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: var(--accent); letter-spacing: .03em; line-height: 1; }
  .pmon-tile-stats { margin-top: 8px; color: var(--text-muted); font-size: 13px; }
  .pmon-tile-n { font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: var(--text); }
  .pmon-tile-l { font-size: 11px; text-transform: uppercase; letter-spacing: .1em; }
  .pmon-tile-tag { margin-top: 10px; font-size: 12px; color: var(--text-muted); font-style: italic; line-height: 1.4; min-height: 32px; }
</style>
"""

    html_doc = promote.html_shell("Pokemon Hunt &middot; All Characters", body,
                                  extra_head=extra_css,
                                  active_page="pokemon.html")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out = DOCS_DIR / "pokemon.html"
    out.write_text(html_doc, encoding="utf-8")
    return out


# --------------------------------------------------------------------------- #
# Orchestration                                                                #
# --------------------------------------------------------------------------- #

def build_all_characters(config: dict, only_character: str | None = None,
                         only_bucket: str | None = None) -> list[dict]:
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    own = cfg.get("seller_username") or "harpua2001"
    token = promote.get_app_token(cfg)
    threshold = float(config.get("deal_threshold_pct", 25))
    min_comps = int(config.get("min_comps_for_median", 6))

    plans: list[dict] = []
    for ch in config.get("characters", []):
        if only_character and ch["slug"].lower() != only_character.lower():
            continue
        print(f"== {ch['name']} ==")
        plan = build_plan(ch, threshold, min_comps, token, own, only_bucket=only_bucket)
        save_plan(plan)
        render_report(plan)
        plans.append(plan)
    return plans


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--character", help="Narrow to a single character slug (e.g. pikachu).")
    ap.add_argument("--bucket",    help="Narrow to a single bucket label.")
    args = ap.parse_args()

    config = load_characters()
    plans = build_all_characters(config,
                                 only_character=args.character,
                                 only_bucket=args.bucket)

    # Always rebuild the landing page from whatever plans we have on disk so
    # single-character runs do not blow away the grid.
    all_plans: list[dict] = []
    for ch in config.get("characters", []):
        match = next((p for p in plans if p["slug"] == ch["slug"]), None)
        if match:
            all_plans.append(match)
            continue
        plan_path = OUTPUT_DIR / f"pokemon_{ch['slug']}_plan.json"
        if plan_path.exists():
            try:
                all_plans.append(json.loads(plan_path.read_text()))
            except (OSError, json.JSONDecodeError):
                pass
    if all_plans:
        landing = render_landing(all_plans)
        print(f"  Landing: {landing}")

    total_listings = sum(sum(b["n"] for b in p["buckets"]) for p in plans)
    total_deals    = sum(sum(b["n_deals"] for b in p["buckets"]) for p in plans)
    print(f"  Characters: {len(plans)}  .  Listings: {total_listings}  .  Deals: {total_deals}")


if __name__ == "__main__":
    main()
