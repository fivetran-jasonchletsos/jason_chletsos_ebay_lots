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

# --- Roster ---
AGENT_NAME = 'Jeremy Lin'
AGENT_ROLE = 'Under $10'

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
    print(f"  Jeremy Lin (Under $10) reporting in.")
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--bucket", help="Narrow to a single bucket label.")
    args = ap.parse_args()
    ensure_nav_entry()
    plan = build_plan(only_bucket=args.bucket)
    save_plan(plan)
    n = sum(b["n"] for b in plan["buckets"])
    print(f"  Buckets: {len(plan['buckets'])}  ·  Listings: {n}")
    print(f"  Plan:   {OUT_PLAN}")


if __name__ == "__main__":
    main()
