"""
under_10_agent.py — every card on eBay for $10 or less across the user's
collecting interests. Same Browse API pattern as pokemon_deals_agent;
filtered to a hard $10 max + sorted by best value (biggest discount).

Buckets are derived from the user's existing config files so this stays
in sync with what the family is actually hunting:
  • Pokemon characters from pokemon_characters.json
  • Player wants from buyer_watchlist.json
  • Static "always-on" buckets seeded inline (vintage rookies, sealed packs)

Output:
  output/under_10_plan.json
  docs/under_10.html
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

REPO_ROOT = Path(__file__).parent
OUT_PLAN  = REPO_ROOT / "output"   / "under_10_plan.json"
OUT_HTML  = REPO_ROOT / "docs"     / "under_10.html"
BROWSE    = "https://api.ebay.com/buy/browse/v1/item_summary/search"
HARD_CAP  = 10.0  # the whole point


# --------------------------------------------------------------------------- #

def _search(token: str, q: str, own: str,
            min_price: float = 1.0, max_price: float = HARD_CAP,
            require_text: str | None = None) -> list[dict]:
    params = {
        "q": q,
        "limit": "100",
        "filter": (
            f"buyingOptions:{{FIXED_PRICE|AUCTION}},"
            f"itemLocationCountry:US,"
            f"price:[{min_price}..{max_price}],"
            f"priceCurrency:USD"
        ),
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        r = requests.get(BROWSE, params=params, headers=headers, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Browse failed for '{q}': {exc}")
        return []
    items = r.json().get("itemSummaries", []) or []
    seen: set[str] = set()
    out: list[dict] = []
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
        if not (0 < price <= HARD_CAP):
            continue
        iid = (it.get("itemId") or "").split("|")[-1]
        if iid in seen:
            continue
        seen.add(iid)
        out.append({
            "item_id":   iid,
            "title":     title,
            "price":     price,
            "url":       promote._epn_wrap(it.get("itemWebUrl") or ""),
            "image":     ((it.get("image") or {}).get("imageUrl")) or "",
            "buying":    it.get("buyingOptions", []) or [],
            "seller":    seller,
        })
    return out


# --------------------------------------------------------------------------- #
# Bucket assembly                                                              #
# --------------------------------------------------------------------------- #

def _assemble_buckets() -> list[dict]:
    """Compose the bucket list from existing config files + static seeds."""
    buckets: list[dict] = []

    # Static "always-on" buckets — broad coverage
    buckets.extend([
        {"label": "Vintage Sports Holos",
         "queries": ["1990s football holo card", "1990s basketball holo card", "1990s baseball holo card"],
         "blurb":   "Pre-2000 holographic cards — vintage shine on a budget."},
        {"label": "Modern Rookie Cards (sports)",
         "queries": ["2024 rookie card prizm", "2025 rookie card chrome refractor", "2024 panini rookie auto"],
         "blurb":   "Current-year rookies — every $5 buy is a lottery ticket."},
        {"label": "Loose Pokemon Boosters",
         "queries": ["pokemon booster pack loose", "pokemon booster pack scarlet violet"],
         "blurb":   "Single packs from current sets. Rip them yourself."},
        {"label": "Pokemon Singles Under $10",
         "queries": ["pokemon holo rare card", "pokemon ex card", "pokemon full art"],
         "blurb":   "Anything Pokemon-shiny in the $1–$10 range."},
        {"label": "Graded Cards Under $10",
         "queries": ["psa graded card", "bgs graded card"],
         "blurb":   "Cheap entry-grade slabs — fun for set builders."},
    ])

    # Pull players from buyer_watchlist.json (Jaxson Dart, Cam Skattebo, etc.)
    try:
        wl = json.loads((REPO_ROOT / "buyer_watchlist.json").read_text())
        for p in wl.get("players", []):
            name = p.get("name", "")
            buckets.append({
                "label":   f"{name} (under $10)",
                "queries": [f"{name.lower()} rookie", f"{name.lower()} card"],
                "blurb":   f"{name} cards in the $1–$10 range.",
            })
    except (OSError, ValueError):
        pass

    # Pull Pokemon characters from pokemon_characters.json
    try:
        chars = json.loads((REPO_ROOT / "pokemon_characters.json").read_text())
        for c in chars.get("characters", []):
            buckets.append({
                "label":   f"{c['name']} (under $10)",
                "queries": [f"{c['name'].lower()} card", f"{c['name'].lower()} holo"],
                "blurb":   f"{c['name']} cards in the $1–$10 range.",
            })
    except (OSError, ValueError):
        pass

    return buckets


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

def build_plan(only_bucket: str | None = None) -> dict:
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    own = cfg.get("seller_username") or "harpua2001"
    token = promote.get_app_token(cfg)
    buckets_cfg = _assemble_buckets()
    if only_bucket:
        buckets_cfg = [b for b in buckets_cfg if b["label"].lower() == only_bucket.lower()]

    out_buckets = []
    for b in buckets_cfg:
        print(f"  -> {b['label']}")
        all_items: list[dict] = []
        seen_ids: set[str] = set()
        for q in b["queries"]:
            for it in _search(token, q, own):
                if it["item_id"] in seen_ids:
                    continue
                seen_ids.add(it["item_id"])
                all_items.append(it)
        if not all_items:
            out_buckets.append({**b, "items": [], "median": None, "n": 0})
            continue
        prices = sorted(i["price"] for i in all_items)
        med = statistics.median(prices)
        for it in all_items:
            it["discount_pct"] = round((1 - it["price"] / med) * 100, 1) if med else 0
        all_items.sort(key=lambda x: x["price"])  # cheapest first
        out_buckets.append({
            **b,
            "items":  all_items[:40],   # cap per bucket
            "median": round(med, 2),
            "lo":     prices[0],
            "hi":     prices[-1],
            "n":      len(all_items),
        })

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hard_cap":     HARD_CAP,
        "buckets":      out_buckets,
    }


def save_plan(plan: dict) -> Path:
    OUT_PLAN.parent.mkdir(parents=True, exist_ok=True)
    OUT_PLAN.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return OUT_PLAN


# --------------------------------------------------------------------------- #
# Report                                                                       #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    buckets = plan["buckets"]
    total_items = sum(b["n"] for b in buckets)

    # All-buckets "absolute cheapest" hero strip
    pool = []
    for b in buckets:
        for it in b["items"]:
            pool.append({**it, "bucket": b["label"]})
    pool.sort(key=lambda x: x["price"])
    cheapest_strip = pool[:12]

    hero_cards = []
    for it in cheapest_strip:
        hero_cards.append(f"""
        <a class="u10-hero-card" href="{_esc(it['url'])}" target="_blank" rel="noopener"
           title="{_esc(it['title'])}">
          <div class="u10-img" style="background-image:url('{_esc(it['image'])}');"></div>
          <div class="u10-meta">
            <div class="u10-price">${it['price']:.2f}</div>
            <div class="u10-bucket">{_esc(it['bucket'])}</div>
          </div>
        </a>""")
    hero_html = (f"""
    <section class="u10-hero">
      <div class="u10-hero-head">
        <h2>Cheapest Right Now</h2>
        <span class="u10-hero-sub">Top 12 cheapest finds across every bucket.</span>
      </div>
      <div class="u10-hero-grid">{''.join(hero_cards)}</div>
    </section>"""
                 if cheapest_strip else "")

    # Per-bucket grids
    sections = []
    for b in buckets:
        slug = re.sub(r"[^a-z0-9]+", "-", b["label"].lower()).strip("-")
        if not b["items"]:
            sections.append(f"""
            <section class="u10-bucket" id="b-{slug}">
              <div class="u10-bhead">
                <h3>{_esc(b['label'])}</h3>
                <p class="u10-blurb">{_esc(b.get('blurb',''))}</p>
                <span class="u10-stats">No live listings under ${HARD_CAP:.0f}.</span>
              </div>
            </section>""")
            continue
        cards = []
        for it in b["items"]:
            cards.append(f"""
            <a class="u10-card" href="{_esc(it['url'])}" target="_blank" rel="noopener"
               data-price="{it['price']:.2f}" data-search="{_esc(it['title'].lower())}">
              <div class="u10-img" style="background-image:url('{_esc(it['image'])}');"></div>
              <div class="u10-meta">
                <div class="u10-price">${it['price']:.2f}</div>
                <div class="u10-title">{_esc(it['title'][:72])}</div>
              </div>
            </a>""")
        sections.append(f"""
        <section class="u10-bucket" id="b-{slug}">
          <div class="u10-bhead">
            <h3>{_esc(b['label'])} <span class="u10-count">{b['n']}</span></h3>
            <p class="u10-blurb">{_esc(b.get('blurb',''))}</p>
            <span class="u10-stats">cheapest ${b['lo']:.2f} · median ${b['median']:.2f} · range ${b['lo']:.2f}–${b['hi']:.2f}</span>
          </div>
          <div class="u10-grid">{''.join(cards)}</div>
        </section>""")

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">eBay live · everything ${HARD_CAP:.0f} or less</div>
        <h1 class="section-title">Under <span class="accent">${HARD_CAP:.0f}</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Cheapest live finds across the player + Pokemon lists plus a few "always-on" buckets
        (vintage holos, modern rookies, loose packs, graded). Buy on dollar bills.
      </div>
    </div>

    <div class="stat-grid">
      <a class="stat-card linked" href="#cheapest" title="Scroll to cheapest strip">
        <div class="num">{len(buckets)}</div><div class="lbl">Buckets scanned</div>
      </a>
      <a class="stat-card linked" href="#cheapest" title="Scroll to cheapest strip">
        <div class="num">{total_items}</div><div class="lbl">Total live listings</div>
      </a>
      <a class="stat-card linked" href="{_esc(cheapest_strip[0]['url']) if cheapest_strip else '#'}"
         target="_blank" rel="noopener" title="Open cheapest item on eBay">
        <div class="num">${cheapest_strip[0]['price']:.2f}</div><div class="lbl">Cheapest right now</div>
      </a>
    </div>

    <div id="cheapest"></div>
    {hero_html}
    {''.join(sections)}
    """

    extra_css = f"""
<style>
  .u10-hero {{ background: linear-gradient(180deg, rgba(127,199,122,.06), transparent); border: 1px solid rgba(127,199,122,.18); border-radius: var(--r-md); padding: 18px; margin: 18px 0 24px; }}
  .u10-hero-head {{ display: flex; align-items: baseline; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }}
  .u10-hero-head h2 {{ margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 32px; color: var(--success); letter-spacing: .03em; }}
  .u10-hero-sub {{ color: var(--text-muted); font-size: 13px; }}
  .u10-hero-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; }}
  .u10-hero-card {{ display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s, border-color .15s, box-shadow .15s; }}
  .u10-hero-card:hover {{ transform: translateY(-3px); border-color: var(--success); box-shadow: 0 8px 24px rgba(127,199,122,.18); }}
  .u10-bucket {{ font-size: 9px; color: var(--text-dim); text-transform: uppercase; letter-spacing: .1em; margin-top: 4px; }}

  .u10-bucket {{ margin: 28px 0; }}
  .u10-bhead {{ margin-bottom: 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }}
  .u10-bhead h3 {{ margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 26px; letter-spacing: .02em; }}
  .u10-count {{ color: var(--text-muted); font-weight: 400; font-size: 14px; margin-left: 6px; }}
  .u10-blurb {{ color: var(--text-muted); font-size: 13px; margin: 4px 0 0; }}
  .u10-stats {{ color: var(--text-muted); font-size: 12px; }}

  .u10-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 10px; }}
  .u10-card {{ display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s, border-color .15s, box-shadow .15s; }}
  .u10-card:hover {{ transform: translateY(-2px); border-color: var(--success); box-shadow: 0 6px 18px rgba(127,199,122,.18); }}
  .u10-img {{ aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }}
  .u10-meta {{ padding: 8px 10px; }}
  .u10-price {{ font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--success); line-height: 1; }}
  .u10-title {{ font-size: 11px; line-height: 1.35; color: var(--text); min-height: 28px; margin-top: 4px; }}
  @media (max-width: 640px) {{
    .u10-grid {{ grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 8px; }}
    .u10-hero-grid {{ grid-template-columns: repeat(auto-fill, minmax(110px, 1fr)); }}
  }}
</style>
"""

    html_doc = promote.html_shell(f"Under ${HARD_CAP:.0f} Finds", body,
                                  extra_head=extra_css,
                                  active_page="under_10.html")
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(html_doc, encoding="utf-8")
    return OUT_HTML


# --------------------------------------------------------------------------- #
# Nav runtime registration                                                    #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    entry = ("under_10.html", "Under $10", True, "For Us")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "price_drops.html":
            items.insert(idx + 1, entry); break
    else:
        items.append(entry)
    promote._NAV_ITEMS = items
    promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--bucket", help="Narrow to a single bucket label.")
    args = ap.parse_args()
    ensure_nav_entry()
    plan = build_plan(only_bucket=args.bucket)
    save_plan(plan)
    out = render_report(plan)
    n = sum(b["n"] for b in plan["buckets"])
    print(f"  Buckets: {len(plan['buckets'])}  ·  Listings: {n}")
    print(f"  Plan:   {OUT_PLAN}")
    print(f"  Report: {out}")


if __name__ == "__main__":
    main()
