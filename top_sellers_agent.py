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

# --- Roster ---
AGENT_NAME = 'Wayne Gretzky'
AGENT_ROLE = 'Top Sellers'

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
    print(f"  Wayne Gretzky (Top Sellers) reporting in.")
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.parse_args()
    ensure_nav_entry()
    plan = build_plan()
    save_plan(plan)
    n = sum(s["n"] for s in plan["sellers"])
    print(f"  Sellers: {len(plan['sellers'])}  ·  Listings indexed: {n}")
    print(f"  Plan:   {PLAN_PATH}")


if __name__ == "__main__":
    main()
