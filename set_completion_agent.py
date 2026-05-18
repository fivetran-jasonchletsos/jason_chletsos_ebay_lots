"""
set_completion_agent.py — Pokemon set-completion tracker for JC's son.

For each set defined in pokemon_sets.json:
  * Matches inventory rows (by year + fuzzy set name + card number)
  * Computes completion %
  * For UNOWNED key chase cards, builds an eBay search URL so the kid can hunt them
  * Optionally fetches a representative image + cheapest price from the eBay Browse
    API (with 429 backoff lifted from pokemon_deals_agent._search). Only one call
    per NEEDED card max; if Browse is rate-limited or token missing we fall back
    to the search link with no thumbnail.

Output: docs/sets.html — a kid-friendly progress page (bright Pokemon palette,
encouraging copy, progress bars, expandable owned lists, "buy on eBay" CTA per
needed card).

Run:
  python3 set_completion_agent.py
  python3 set_completion_agent.py --no-api    # skip Browse, links-only
  python3 set_completion_agent.py --set 151   # narrow to one set id
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import random
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests

import promote

REPO_ROOT   = Path(__file__).parent
SETS_FILE   = REPO_ROOT / "pokemon_sets.json"
INVENTORY   = REPO_ROOT / "inventory.csv"
DOCS_DIR    = REPO_ROOT / "docs"
OUTPUT_DIR  = REPO_ROOT / "output"
BROWSE_URL  = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Soft cap on Browse calls per run so we don't trip rate-limits across all sets.
MAX_BROWSE_CALLS = 60


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #

def _normalize(s: str) -> str:
    """Lowercase + strip non-alphanum for fuzzy set-name matching."""
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _card_num_root(num: str) -> str:
    """'4/102' -> '4'; '025/165' -> '25'; '183/165' -> '183'. Used for match."""
    n = (num or "").split("/")[0].strip()
    return n.lstrip("0") or n


# Aliases so 'Base Set' inventory row matches '1999 Pokemon Base Set' name etc.
SET_ALIASES = {
    "base-set":             ["baseset", "base"],
    "celebrations-2021":    ["celebrations"],
    "pokemon-go-2022":      ["pokemongo", "pogo"],
    "151":                  ["151", "scarletviolet151", "sv151"],
    "obsidian-flames":      ["obsidianflames"],
    "paldean-fates":        ["paldeanfates"],
    "surging-sparks":       ["surgingsparks"],
    "prismatic-evolutions": ["prismaticevolutions", "prismatic"],
}


def _set_matches(set_def: dict, inv_row: dict) -> bool:
    """Does this inventory row plausibly belong to this set?"""
    if (inv_row.get("sport") or "").strip().lower() != "pokemon":
        return False
    try:
        if int(set_def["year"]) != int(inv_row.get("year") or 0):
            return False
    except ValueError:
        return False
    inv_set = _normalize(inv_row.get("set") or "")
    inv_name = _normalize(inv_row.get("name") or "")
    target = _normalize(set_def["name"])
    if target and (target in inv_set or target in inv_name):
        return True
    for alias in SET_ALIASES.get(set_def["id"], []):
        if alias and (alias in inv_set or alias in inv_name):
            return True
    return False


# --------------------------------------------------------------------------- #
# Inventory                                                                   #
# --------------------------------------------------------------------------- #

def load_inventory() -> list[dict]:
    if not INVENTORY.exists():
        return []
    with INVENTORY.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("name")]


# --------------------------------------------------------------------------- #
# eBay Browse (with 429 backoff) — adapted from pokemon_deals_agent._search   #
# --------------------------------------------------------------------------- #

def _browse_lookup(token: str, q: str, _retry: int = 0) -> dict | None:
    """One Browse call, returns the cheapest match dict or None."""
    if not token:
        return None
    params = {
        "q": q,
        "limit": "10",
        "filter": "buyingOptions:{FIXED_PRICE|AUCTION},itemLocationCountry:US,priceCurrency:USD",
        "sort": "price",
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }
    try:
        r = requests.get(BROWSE_URL, params=params, headers=headers, timeout=15)
        if r.status_code == 429 and _retry < 3:
            wait = (2 ** _retry) * 6 + random.uniform(0, 3)
            print(f"  Browse 429 for '{q}' — backing off {wait:.1f}s (retry {_retry+1}/3)")
            time.sleep(wait)
            return _browse_lookup(token, q, _retry + 1)
        r.raise_for_status()
    except requests.RequestException as exc:
        print(f"  Browse failed for '{q}': {exc}")
        return None
    for it in r.json().get("itemSummaries", []) or []:
        try:
            price = float((it.get("price") or {}).get("value") or 0)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue
        return {
            "price":  price,
            "url":    promote._epn_wrap(it.get("itemWebUrl") or ""),
            "image":  ((it.get("image") or {}).get("imageUrl")) or "",
            "title":  it.get("title") or "",
        }
    return None


# --------------------------------------------------------------------------- #
# Per-set analysis                                                            #
# --------------------------------------------------------------------------- #

def analyze_set(set_def: dict, inventory: list[dict],
                token: str | None, calls_remaining: list[int]) -> dict:
    """Returns a dict with owned/needed/completion info ready for rendering."""
    matched_rows = [r for r in inventory if _set_matches(set_def, r)]

    # Dedupe by card_number (a kid only needs one of each for completion).
    owned_nums: dict[str, dict] = {}
    for r in matched_rows:
        root = _card_num_root(r.get("card_number") or "")
        if not root:
            continue
        owned_nums.setdefault(root, r)

    owned_count = len(owned_nums)
    total = int(set_def["total_cards"])
    pct = (owned_count / total * 100) if total else 0

    # Walk key chase cards, split into owned vs needed.
    owned_key, needed_key = [], []
    for kc in set_def.get("key_cards", []):
        root = _card_num_root(kc.get("number") or "")
        search_q = f"{set_def['year']} Pokemon {set_def['name']} {kc['name']} {kc['number']}"
        ebay_search_url = f"https://www.ebay.com/sch/i.html?_nkw={quote_plus(search_q)}"
        entry = {
            **kc,
            "search_url":     ebay_search_url,
            "search_url_epn": promote._epn_wrap(ebay_search_url),
            "image":          "",
            "price":          None,
            "buy_url":        ebay_search_url,
        }
        if root and root in owned_nums:
            owned_key.append(entry)
        else:
            # NEEDED — single Browse lookup (rate-budgeted).
            if token and calls_remaining[0] > 0:
                hit = _browse_lookup(token, search_q)
                calls_remaining[0] -= 1
                if hit:
                    entry["image"]   = hit["image"]
                    entry["price"]   = hit["price"]
                    entry["buy_url"] = hit["url"] or ebay_search_url
            needed_key.append(entry)

    # Owned cards we matched but that aren't in key_cards list — still show them.
    key_roots = {_card_num_root(kc["number"]) for kc in set_def.get("key_cards", [])}
    owned_other = []
    for root, row in owned_nums.items():
        if root in key_roots:
            continue
        owned_other.append({
            "number": row.get("card_number") or "",
            "name":   row.get("player") or row.get("name") or "",
            "rarity": row.get("parallel") or "",
        })

    return {
        "id":           set_def["id"],
        "name":         set_def["name"],
        "year":         set_def["year"],
        "total":        total,
        "blurb":        set_def.get("blurb", ""),
        "owned_count":  owned_count,
        "needed_count": total - owned_count,
        "pct":          round(pct, 1),
        "owned_key":    owned_key,
        "needed_key":   needed_key,
        "owned_other":  owned_other,
    }


# --------------------------------------------------------------------------- #
# Encouraging copy                                                            #
# --------------------------------------------------------------------------- #

def _encourage(pct: float, needed: int) -> str:
    if pct >= 100:
        return "MASTER COLLECTOR! Set complete!"
    if pct >= 75:
        return f"So close! Just {needed} more to finish!"
    if pct >= 50:
        return "Over halfway there — keep going!"
    if pct >= 25:
        return "Off to a great start!"
    if pct > 0:
        return f"You've got {needed} cards to find!"
    return "Brand new hunt — let's go!"


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #

def _esc(s: Any) -> str:
    return html.escape(str(s or ""), quote=True)


def _card_thumb(entry: dict) -> str:
    if entry.get("image"):
        return (
            f'<img class="card-thumb" src="{_esc(entry["image"])}" '
            f'alt="{_esc(entry["name"])}" loading="lazy">'
        )
    return '<div class="card-thumb card-thumb-placeholder">?</div>'


def render(set_reports: list[dict]) -> Path:
    total_owned = sum(s["owned_count"] for s in set_reports)
    total_possible = sum(s["total"] for s in set_reports)
    overall_pct = (total_owned / total_possible * 100) if total_possible else 0
    top = max(set_reports, key=lambda s: s["pct"]) if set_reports else None

    parts = []
    parts.append(f"""
<style>
  :root {{
    --poke-red:    #ee1515;
    --poke-blue:   #3b4cca;
    --poke-yellow: #ffde00;
    --poke-gold:   #b3a125;
  }}
  .sets-hero {{
    background: linear-gradient(135deg, var(--poke-blue) 0%, var(--poke-red) 100%);
    border-radius: 20px;
    padding: 28px 24px;
    color: #fff;
    text-align: center;
    margin-bottom: 24px;
    box-shadow: 0 8px 24px rgba(0,0,0,.2);
  }}
  .sets-hero h1 {{
    margin: 0 0 8px; font-size: 28px; letter-spacing: 1px;
    text-shadow: 2px 2px 0 var(--poke-gold);
  }}
  .sets-hero .big {{
    font-size: 48px; font-weight: 800; color: var(--poke-yellow);
    text-shadow: 3px 3px 0 #000;
    line-height: 1.1;
  }}
  .sets-hero .sub {{ opacity: .9; margin-top: 6px; }}
  .set-card {{
    background: var(--card-bg, #fff);
    border: 3px solid var(--poke-yellow);
    border-radius: 16px;
    padding: 18px;
    margin-bottom: 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,.08);
  }}
  .set-card h2 {{
    margin: 0; font-size: 22px;
    color: var(--poke-blue);
  }}
  .set-card .year-pill {{
    display: inline-block; background: var(--poke-yellow); color: #000;
    padding: 2px 10px; border-radius: 999px; font-weight: 700; font-size: 12px;
    margin-left: 8px; vertical-align: middle;
  }}
  .set-card .blurb {{ color: var(--text-muted, #666); margin: 6px 0 12px; font-size: 14px; }}
  .progress-wrap {{
    background: #eee; border-radius: 12px; height: 22px; overflow: hidden;
    border: 2px solid #000; margin: 10px 0;
  }}
  .progress-bar {{
    height: 100%; background: linear-gradient(90deg, #4ade80 0%, #16a34a 100%);
    transition: width .6s ease; display: flex; align-items: center;
    justify-content: flex-end; padding-right: 8px; color: #fff;
    font-weight: 700; font-size: 12px; white-space: nowrap;
  }}
  .progress-meta {{ display:flex; justify-content:space-between; font-weight: 600; }}
  .progress-meta .encourage {{ color: var(--poke-red); }}
  .needed-grid, .owned-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr));
    gap: 12px; margin-top: 12px;
  }}
  .card-tile {{
    background: var(--bg-soft, #f8f9fc);
    border: 2px solid #e5e7eb;
    border-radius: 12px;
    padding: 10px;
    text-align: center;
    transition: transform .15s ease, border-color .15s ease;
  }}
  .card-tile:hover {{ transform: translateY(-2px); border-color: var(--poke-blue); }}
  .card-tile.needed {{ border-color: var(--poke-red); }}
  .card-tile.owned  {{ border-color: #16a34a; background: #f0fdf4; }}
  .card-thumb {{ width:100%; aspect-ratio: 2.5/3.5; object-fit: cover; border-radius: 6px; }}
  .card-thumb-placeholder {{
    display:flex; align-items:center; justify-content:center;
    background:#ddd; color:#999; font-size: 32px; font-weight: 800;
  }}
  .card-tile .num   {{ font-size: 11px; color: var(--text-muted, #666); margin-top: 6px; }}
  .card-tile .name  {{ font-weight: 700; font-size: 13px; line-height:1.2; margin-top:2px; }}
  .card-tile .rarity{{ font-size: 11px; color: var(--poke-blue); margin-top: 2px; }}
  .card-tile .price {{ font-weight: 800; color: #16a34a; margin-top: 4px; }}
  .card-tile .buy-btn {{
    display:inline-block; margin-top: 6px;
    background: var(--poke-red); color: #fff; padding: 4px 10px;
    border-radius: 999px; font-size: 11px; font-weight: 700;
    text-decoration: none;
  }}
  .card-tile .buy-btn:hover {{ background: var(--poke-blue); }}
  .owned-toggle {{
    margin-top: 14px; cursor:pointer; color: var(--poke-blue);
    font-weight: 700; user-select: none;
  }}
  details.owned-block summary {{ list-style: none; }}
  details.owned-block summary::-webkit-details-marker {{ display: none; }}
  .section-label {{
    margin-top: 14px; font-weight:800; color: var(--poke-red);
    border-bottom: 2px dashed var(--poke-yellow); padding-bottom: 4px;
  }}
  .section-label.owned {{ color: #16a34a; }}
</style>
""")

    parts.append(f"""
<main class="container" style="max-width:1100px; margin:0 auto; padding: 16px;">
  <div class="sets-hero">
    <h1>POKEMON SET COLLECTOR</h1>
    <div class="big">{total_owned} / {total_possible}</div>
    <div class="sub">cards owned across {len(set_reports)} tracked sets — <b>{overall_pct:.1f}%</b> complete</div>
    {"<div class='sub'>Top set: <b>" + _esc(top['name']) + f"</b> at {top['pct']:.0f}%</div>" if top else ""}
  </div>
""")

    for s in set_reports:
        encourage = _encourage(s["pct"], s["needed_count"])
        parts.append(f"""
  <div class="set-card">
    <h2>{_esc(s['name'])}<span class="year-pill">{s['year']}</span></h2>
    <div class="blurb">{_esc(s['blurb'])}</div>
    <div class="progress-meta">
      <div>{s['owned_count']} / {s['total']} cards</div>
      <div class="encourage">{_esc(encourage)}</div>
    </div>
    <div class="progress-wrap">
      <div class="progress-bar" style="width: {max(s['pct'], 4)}%;">{s['pct']:.0f}%</div>
    </div>
""")

        if s["needed_key"]:
            parts.append('<div class="section-label">CHASE CARDS TO HUNT</div><div class="needed-grid">')
            for c in s["needed_key"]:
                price_html = f'<div class="price">${c["price"]:.2f}+</div>' if c.get("price") else ""
                parts.append(f"""
  <div class="card-tile needed">
    {_card_thumb(c)}
    <div class="num">#{_esc(c['number'])}</div>
    <div class="name">{_esc(c['name'])}</div>
    <div class="rarity">{_esc(c.get('rarity',''))}</div>
    {price_html}
    <a class="buy-btn" href="{_esc(c['buy_url'])}" target="_blank" rel="noopener">Find on eBay</a>
  </div>""")
            parts.append('</div>')

        if s["owned_key"] or s["owned_other"]:
            parts.append(f"""
    <details class="owned-block">
      <summary class="owned-toggle">▶ Show owned cards ({len(s['owned_key']) + len(s['owned_other'])})</summary>
      <div class="section-label owned">CARDS YOU OWN</div>
      <div class="owned-grid">
""")
            for c in s["owned_key"]:
                parts.append(f"""
        <div class="card-tile owned">
          <div class="card-thumb card-thumb-placeholder">✓</div>
          <div class="num">#{_esc(c['number'])}</div>
          <div class="name">{_esc(c['name'])}</div>
          <div class="rarity">{_esc(c.get('rarity',''))}</div>
        </div>""")
            for c in s["owned_other"]:
                parts.append(f"""
        <div class="card-tile owned">
          <div class="card-thumb card-thumb-placeholder">✓</div>
          <div class="num">#{_esc(c['number'])}</div>
          <div class="name">{_esc(c['name'])}</div>
          <div class="rarity">{_esc(c.get('rarity',''))}</div>
        </div>""")
            parts.append("</div></details>")

        parts.append("</div>")  # /set-card

    parts.append("</main>")

    body = "".join(parts)
    out  = DOCS_DIR / "sets.html"
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    out.write_text(
        promote.html_shell(
            f"Set Collector · {promote.SELLER_NAME}",
            body,
            active_page="sets.html",
        ),
        encoding="utf-8",
    )
    return out


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.strip() if __doc__ else "")
    ap.add_argument("--no-api", action="store_true", help="Skip eBay Browse calls.")
    ap.add_argument("--set", help="Narrow to a single set id (e.g. 151).")
    args = ap.parse_args()

    config = json.loads(SETS_FILE.read_text())
    sets   = config["sets"]
    if args.set:
        sets = [s for s in sets if s["id"].lower() == args.set.lower()]
        if not sets:
            raise SystemExit(f"No set matched id={args.set}")

    inventory = load_inventory()
    print(f"Loaded {len(inventory)} inventory rows and {len(sets)} sets.")

    token: str | None = None
    if not args.no_api:
        try:
            cfg = json.loads(promote.CONFIG_FILE.read_text())
            token = promote.get_app_token(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"  No eBay token ({exc}); running in --no-api mode.")
            token = None

    calls_remaining = [MAX_BROWSE_CALLS]
    reports = []
    for sd in sets:
        print(f"== {sd['name']} ({sd['year']}) ==")
        rpt = analyze_set(sd, inventory, token, calls_remaining)
        print(f"   owned {rpt['owned_count']}/{rpt['total']} ({rpt['pct']:.1f}%)")
        reports.append(rpt)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "set_completion.json").write_text(
        json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "sets":         reports,
        }, indent=2),
        encoding="utf-8",
    )

    out = render(reports)
    total_owned = sum(s["owned_count"] for s in reports)
    total_poss  = sum(s["total"]       for s in reports)
    print(f"Wrote {out} — {total_owned}/{total_poss} cards across {len(reports)} sets.")


if __name__ == "__main__":
    main()
