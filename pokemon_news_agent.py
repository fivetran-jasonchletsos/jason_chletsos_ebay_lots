"""
pokemon_news_agent.py — Pokemon TCG release radar for my son.

Reads pokemon_news_config.json (curated upcoming/recent sets), hits the
eBay Browse API for each set's search query, and renders
docs/pokemon_news.html — a release calendar with live pre-order finds,
a Reshiram/Zekrom hero strip, and chase-card highlights.

Output:
  output/pokemon_news_plan.json    structured plan
  docs/pokemon_news.html           release-radar page

CLI:
  python3 pokemon_news_agent.py
  python3 pokemon_news_agent.py --set monochrome-bwr      # one set only
"""

from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Tiki Barber'
AGENT_ROLE = 'Pokémon News'

import argparse
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT   = Path(__file__).parent
CONFIG_PATH = REPO_ROOT / "pokemon_news_config.json"
PLAN_PATH   = REPO_ROOT / "output" / "pokemon_news_plan.json"
REPORT_PATH = REPO_ROOT / "docs" / "pokemon_news.html"
BROWSE_URL  = "https://api.ebay.com/buy/browse/v1/item_summary/search"


# --------------------------------------------------------------------------- #
# Search                                                                       #
# --------------------------------------------------------------------------- #

def _search(token: str, q: str, own_seller: str, limit: int = 50) -> list[dict]:
    params = {
        "q": q,
        "limit": str(limit),
        "filter": (
            "buyingOptions:{FIXED_PRICE|AUCTION},"
            "priceCurrency:USD"
        ),
        "sort": "price",
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
    seen: set[str] = set()
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
            "condition": it.get("condition") or "",
        })
    return out


# --------------------------------------------------------------------------- #
# Classification                                                               #
# --------------------------------------------------------------------------- #

def _classify(title: str) -> str:
    """Bucket the item: ETB / booster_box / booster_pack / single / other."""
    t = title.lower()
    if "etb" in t or "elite trainer box" in t:
        return "ETB"
    if "booster box" in t or "booster bundle" in t or "case " in t:
        return "Booster Box"
    if "booster pack" in t or "pack lot" in t or " packs" in t:
        return "Packs"
    if "psa" in t or "graded" in t or "bgs" in t:
        return "Graded Single"
    if any(x in t for x in (" ex ", " sar", " sir", "hyper rare", "full art", "alt art")):
        return "Single Card"
    return "Other"


def _is_preorder(title: str) -> bool:
    t = title.lower()
    return any(x in t for x in ("pre-order", "preorder", "pre order", "pre-sale", "presale"))


# --------------------------------------------------------------------------- #
# Plan                                                                         #
# --------------------------------------------------------------------------- #

def build_plan(only_slug: str | None = None) -> dict:
    cfg_full = json.loads(CONFIG_PATH.read_text())
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    own = cfg.get("seller_username") or "harpua2001"
    token = promote.get_app_token(cfg)
    limit = int(cfg_full.get("max_results_per_set", 24))

    sets_out = []
    for s in cfg_full.get("sets", []):
        if only_slug and s["slug"].lower() != only_slug.lower():
            continue
        print(f"  -> {s['name']}")
        items = _search(token, s["search_query"], own, limit=limit * 2)
        if not items and s.get("fallback_query"):
            items = _search(token, s["fallback_query"], own, limit=limit * 2)

        # Annotate.
        for it in items:
            it["type"] = _classify(it["title"])
            it["is_preorder"] = _is_preorder(it["title"])
        items.sort(key=lambda x: (not x["is_preorder"], x["price"]))
        items = items[:limit]

        type_counts: dict[str, int] = {}
        for it in items:
            type_counts[it["type"]] = type_counts.get(it["type"], 0) + 1
        cheapest = min((i["price"] for i in items), default=None)
        n_preorder = sum(1 for i in items if i["is_preorder"])

        # Chase-card mini-scans: 4 listings per chase card.
        chase_finds = []
        for chase in s.get("chase_cards", []):
            cq = f"{chase} {s['name'].split(':')[0]}"
            chase_items = _search(token, cq, own, limit=8)[:4]
            for ci in chase_items:
                ci["type"] = _classify(ci["title"])
                ci["is_preorder"] = _is_preorder(ci["title"])
            chase_finds.append({
                "name": chase,
                "items": chase_items,
                "cheapest": min((i["price"] for i in chase_items), default=None),
            })

        sets_out.append({
            **s,
            "items":       items,
            "n":           len(items),
            "n_preorder":  n_preorder,
            "type_counts": type_counts,
            "cheapest":    cheapest,
            "chase_finds": chase_finds,
        })

    # Sort: featured first, then by release date ascending (future first based
    # on today, but we just sort all chronologically — page filters later).
    featured_slug = cfg_full.get("featured_set", "")
    sets_out.sort(key=lambda x: (x["slug"] != featured_slug, x["release_date"]))

    return {
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "featured_slug":  featured_slug,
        "sets":           sets_out,
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


def _money(v: float | None) -> str:
    return f"${v:,.2f}" if isinstance(v, (int, float)) and v else "—"


def _date_str(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%b %d, %Y")
    except Exception:
        return iso or "TBD"


def _render_card(it: dict) -> str:
    buying = " · ".join(
        "BIN" if x == "FIXED_PRICE" else
        "Auction" if x == "AUCTION" else
        "Best Offer" if x == "BEST_OFFER" else _esc(x)
        for x in it.get("buying", [])
    )
    preorder_chip = '<span class="pn-chip pn-chip-pre">PRE-ORDER</span>' if it.get("is_preorder") else ""
    type_chip = f'<span class="pn-chip pn-chip-type">{_esc(it["type"])}</span>'
    return f"""
    <a class="pn-card" href="{_esc(it['url'])}" target="_blank" rel="noopener"
       title="{_esc(it['title'])}">
      <div class="pn-img" style="background-image:url('{_esc(it['image'])}');"></div>
      <div class="pn-meta">
        <div class="pn-price-row">
          <span class="pn-price">${it['price']:.2f}</span>
          {preorder_chip}
        </div>
        <div class="pn-title">{_esc(it['title'][:90])}</div>
        <div class="pn-foot">
          {type_chip}
          <span class="pn-buy">{buying}</span>
        </div>
      </div>
    </a>"""


def _render_hero(featured: dict | None) -> str:
    if not featured:
        return ""
    items = featured.get("items", [])[:6]
    cards = "".join(_render_card(it) for it in items)
    chase_html = ""
    chase = featured.get("chase_finds", [])
    if chase:
        chase_chips = "".join(
            f'<span class="pn-hero-chase">{_esc(c["name"])}'
            + (f' · from {_money(c["cheapest"])}' if c.get("cheapest") else "")
            + '</span>'
            for c in chase
        )
        chase_html = f'<div class="pn-hero-chases">{chase_chips}</div>'

    cheapest = featured.get("cheapest")
    cheapest_str = _money(cheapest)
    return f"""
    <section class="pn-hero">
      <div class="pn-hero-bg"></div>
      <div class="pn-hero-inner">
        <div class="pn-hero-eyebrow">FEATURED · {_esc(featured['release_label'])}</div>
        <h1 class="pn-hero-title">{_esc(featured['name'])}</h1>
        <p class="pn-hero-blurb">{_esc(featured['blurb'])}</p>
        <div class="pn-hero-stats">
          <span><b>{featured['n']}</b> live listings</span>
          <span><b>{featured['n_preorder']}</b> pre-orders</span>
          <span>cheapest <b>{cheapest_str}</b></span>
        </div>
        {chase_html}
        <div class="pn-hero-grid">{cards}</div>
      </div>
    </section>"""


def _render_set_section(s: dict) -> str:
    slug = _esc(s["slug"])
    items = s.get("items", [])
    cards = "".join(_render_card(it) for it in items) if items else \
        '<div class="pn-empty">No live listings yet — set is too far out or no sellers have it up.</div>'

    chase_blocks = []
    for c in s.get("chase_finds", []):
        if not c.get("items"):
            continue
        chase_cards = "".join(_render_card(it) for it in c["items"])
        chase_blocks.append(f"""
        <div class="pn-chase">
          <div class="pn-chase-head">
            <h4>{_esc(c['name'])}</h4>
            <span class="pn-chase-sub">from {_money(c.get('cheapest'))}</span>
          </div>
          <div class="pn-grid pn-grid-sm">{chase_cards}</div>
        </div>""")

    type_chips = " ".join(
        f'<span class="pn-type-chip">{_esc(t)}: <b>{n}</b></span>'
        for t, n in sorted(s.get("type_counts", {}).items(), key=lambda x: -x[1])
    )

    search_url = "https://www.ebay.com/sch/i.html?_nkw=" + _esc(s["search_query"].replace(" ", "+"))

    return f"""
    <section class="pn-set" id="set-{slug}" data-lang="{_esc(s['language']).lower()}">
      <div class="pn-set-head">
        <div class="pn-set-meta">
          <span class="pn-tag pn-tag-{_esc(s['language']).lower()}">{_esc(s['tag'])}</span>
          <span class="pn-set-date">{_date_str(s['release_date'])}</span>
        </div>
        <h2>{_esc(s['name'])}</h2>
        <p class="pn-blurb">{_esc(s['blurb'])}</p>
        <div class="pn-set-stats">
          {type_chips}
          <a class="pn-cta" href="{search_url}" target="_blank" rel="noopener">Buy Pre-Order on eBay &rarr;</a>
        </div>
      </div>
      <div class="pn-grid">{cards}</div>
      {''.join(chase_blocks)}
    </section>"""


def _render_calendar(sets: list[dict]) -> str:
    today = datetime.now().date().isoformat()
    upcoming = [s for s in sets if s["release_date"] >= today]
    past     = [s for s in sets if s["release_date"] < today]
    upcoming.sort(key=lambda x: x["release_date"])
    past.sort(key=lambda x: x["release_date"], reverse=True)

    def row(s: dict, future: bool) -> str:
        search_url = "https://www.ebay.com/sch/i.html?_nkw=" + _esc(s["search_query"].replace(" ", "+"))
        status = "UPCOMING" if future else "RELEASED"
        return f"""
        <a class="pn-cal-row pn-cal-{'fut' if future else 'past'}" href="#set-{_esc(s['slug'])}">
          <span class="pn-cal-date">{_date_str(s['release_date'])}</span>
          <span class="pn-cal-name">{_esc(s['name'])}</span>
          <span class="pn-cal-lang">{_esc(s['language'])}</span>
          <span class="pn-cal-status">{status}</span>
          <span class="pn-cal-cta"><a href="{search_url}" target="_blank" rel="noopener" onclick="event.stopPropagation();">Pre-Order &rarr;</a></span>
        </a>"""

    rows = "".join(row(s, True) for s in upcoming) + "".join(row(s, False) for s in past)
    return f"""
    <section class="pn-cal">
      <div class="pn-cal-head">
        <h2>Release Calendar</h2>
        <span class="pn-cal-sub">{len(upcoming)} upcoming · {len(past)} recently released</span>
      </div>
      <div class="pn-cal-list">{rows}</div>
    </section>"""


# --------------------------------------------------------------------------- #
# Nav registration (runtime only — persist in promote.py separately)          #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    entry = ("pokemon_news.html", "Pokemon News", False, "Insights")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "pikachu.html":
            items.insert(idx + 1, entry)
            break
    else:
        items.append(entry)
    promote._NAV_ITEMS = items
    promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def main() -> None:
    print(f"  Tiki Barber (Pokémon News) reporting in.")
    ap = argparse.ArgumentParser(description=(__doc__ or "").strip())
    ap.add_argument("--set", dest="slug", help="Narrow to a single set by slug.")
    args = ap.parse_args()

    ensure_nav_entry()
    plan = build_plan(only_slug=args.slug)
    save_plan(plan)

    total = sum(s["n"] for s in plan["sets"])
    pre   = sum(s["n_preorder"] for s in plan["sets"])
    print(f"  Sets: {len(plan['sets'])}  ·  Listings: {total}  ·  Pre-orders: {pre}")
    print(f"  Plan:   {PLAN_PATH}")


if __name__ == "__main__":
    main()
