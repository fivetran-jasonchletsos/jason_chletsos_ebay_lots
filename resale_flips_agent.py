#!/usr/bin/env python3
"""
Resale Flips agent.

Buyer-side curated buy list. For each candidate listing pulled from the same
eBay Browse infrastructure that powers Deal Hunter, compute:

  asking, est. resale, net profit after eBay fees + shipping in/out, % below
  comp median, sold velocity, listing type, seller signals, photo signals,
  and warning badges (returned-relist, thin comps, centering risk, auction
  ending soon).

Data flow:
  1. Try to fetch fresh listings via promote.fetch_deals(cfg) using the eBay
     credentials in configuration.json.
  2. If that fails (no token, offline, etc.), fall back to a cached
     deals payload at output/_resale_flips_source.json from a prior run.
  3. Write the computed plan to output/resale_flips_plan.json and the rendered
     admin page to docs/resale_flips.html via promote.html_shell().

Run:
    python3 resale_flips_agent.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT       = Path(__file__).parent
DOCS_DIR   = ROOT / "docs"
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SOURCE_CACHE   = OUTPUT_DIR / "_resale_flips_source.json"
PLAN_FILE      = OUTPUT_DIR / "resale_flips_plan.json"
HTML_FILE      = DOCS_DIR   / "resale_flips.html"
SOLD_HISTORY   = ROOT / "sold_history.json"
CONFIG_FILE    = ROOT / "configuration.json"

# Cost model — tunable, but these are conservative for raw / mid-tier flips.
EBAY_FVF_PCT       = 0.13     # 13% final-value fee (incl. ad-valorem)
FIXED_FEE          = 0.30     # per-order fixed fee
INBOUND_SHIP       = 4.00     # avg shipping IN for a single mid-price card
OUTBOUND_SHIP      = 4.00     # what Jason pays to ship the resale out
INBOUND_HANDLING   = 0.50     # toploader + sleeve + label time at $.50/unit
AUCTION_SOON_HRS   = 2.0
THIN_COMPS_LIMIT   = 8

# Titles with structural centering / quality issues — known landmines.
CENTERING_RISK_NEEDLES = [
    "1986 fleer",                # basketball — chronic centering
    "1999 pokemon base charizard",
    "2018 optic",                # silver holo prizm centering
    "2020 prizm lamelo silver",
]

# Phrases that suggest a seller "doesn't know what they have."
NAIVE_SELLER_NEEDLES = [
    "cleaning out", "from attic", "from the attic", "estate find",
    "found in", "garage cleanout", "moms basement", "mom's basement",
    "no idea", "not sure what", "kids collection", "old collection",
]


# ---------------------------------------------------------------------------
# Imports from promote.py — share fetch + render plumbing.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(ROOT))
import promote  # noqa: E402  (path mutation required)


def load_cfg() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except Exception:
        return {}


def load_sold_history() -> list[dict]:
    if not SOLD_HISTORY.exists():
        return []
    try:
        data = json.loads(SOLD_HISTORY.read_text())
        return data if isinstance(data, list) else []
    except Exception:
        return []


def get_source_listings(cfg: dict) -> dict:
    """Try live fetch first, fall back to disk cache."""
    try:
        print("Fetching fresh deals via promote.fetch_deals(cfg) ...")
        data = promote.fetch_deals(cfg)
        if data and data.get("queries"):
            SOURCE_CACHE.write_text(json.dumps(data, indent=2), encoding="utf-8")
            print(f"  ok — cached to {SOURCE_CACHE}")
            return data
        print("  fetch returned no queries; trying disk fallback")
    except Exception as exc:
        print(f"  live fetch failed: {exc}; trying disk fallback")
    if SOURCE_CACHE.exists():
        print(f"Falling back to {SOURCE_CACHE}")
        return json.loads(SOURCE_CACHE.read_text())
    print("No cached source available. Returning empty payload.")
    return {"queries": [], "threshold": 30, "total_deals": 0}


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _net_profit(asking: float, resale: float) -> float:
    """Net profit after fees and shipping, both directions."""
    proceeds = resale * (1 - EBAY_FVF_PCT) - FIXED_FEE - OUTBOUND_SHIP
    cost     = asking + INBOUND_SHIP + INBOUND_HANDLING
    return round(proceeds - cost, 2)


def _sold_velocity_30d(title: str, sold_history: list[dict]) -> int:
    """How many similar items have sold in the last 30 days. Token overlap >= 2."""
    if not sold_history:
        return 0
    stop = {"card", "cards", "lot", "pack", "set", "near", "mint", "from", "with"}
    toks = {w for w in title.lower().split() if len(w) >= 4 and w not in stop}
    if not toks:
        return 0
    cutoff = datetime.now(timezone.utc).timestamp() - 30 * 86400
    n = 0
    for s in sold_history:
        try:
            sdate = s.get("sold_date") or ""
            # sold_date is ISO like "2026-05-27T01:33:30.000Z"
            ts = datetime.fromisoformat(sdate.replace("Z", "+00:00")).timestamp()
            if ts < cutoff:
                continue
        except Exception:
            continue
        s_toks = {w for w in (s.get("title") or "").lower().split() if len(w) >= 4}
        if len(toks & s_toks) >= 2:
            n += 1
    return n


def _centering_risk(title: str) -> bool:
    t = (title or "").lower()
    return any(n in t for n in CENTERING_RISK_NEEDLES)


def _naive_seller_signal(title: str) -> bool:
    t = (title or "").lower()
    return any(n in t for n in NAIVE_SELLER_NEEDLES)


def _missing_parallel_year(title: str) -> bool:
    """If a graded-modern title has no parallel keyword and no year, it might be
    mis-listed — sellers who don't know often skip these."""
    t = (title or "").lower()
    has_year = bool(re.search(r"\b(19|20)\d{2}\b", t))
    has_parallel = any(k in t for k in ("silver", "prizm", "holo", "refractor",
                                        "wave", "mojo", "color blast", "optic"))
    # only flag for clearly modern parallel-relevant items
    return ("prizm" in t or "optic" in t or "select" in t) and not has_parallel and not has_year


def _auction_ends_soon(end_time: str, ltype: str) -> bool:
    if "Auction" not in (ltype or ""):
        return False
    if not end_time:
        return False
    try:
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        hrs = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        return 0 < hrs <= AUCTION_SOON_HRS
    except Exception:
        return False


def _seller_appearances_in_actives(seller: str, all_deals: list[dict],
                                   title: str) -> int:
    """Rough returned-relist heuristic: count other current listings from the
    same seller with overlapping title tokens."""
    if not seller:
        return 0
    toks = {w for w in (title or "").lower().split() if len(w) >= 4}
    if not toks:
        return 0
    n = 0
    for d in all_deals:
        if d.get("seller", "").lower() != seller.lower():
            continue
        if (d.get("title") or "").lower() == (title or "").lower():
            continue
        d_toks = {w for w in (d.get("title") or "").lower().split() if len(w) >= 4}
        if len(toks & d_toks) >= 3:
            n += 1
    return n


def score_listing(d: dict, all_deals: list[dict], sold_history: list[dict]) -> dict:
    asking   = float(d.get("price") or 0)
    median   = float(d.get("median") or 0)
    title    = d.get("title", "") or ""
    seller   = d.get("seller", "") or ""
    ltype    = d.get("listing_type", "BIN")
    end_time = d.get("end_time", "")

    if median <= 0 or asking <= 0:
        return None

    # Resale target: lean on the comp median itself. Most flips clear at ~comp
    # median; assume 0% upside over median for conservative net-profit math.
    resale = median

    net      = _net_profit(asking, resale)
    pct_below = round((1 - asking / median) * 100, 1)
    velocity = _sold_velocity_30d(title, sold_history)

    warnings = []
    if _centering_risk(title):
        warnings.append("Centering risk")
    if velocity < THIN_COMPS_LIMIT:
        warnings.append("Thin comps")
    if _auction_ends_soon(end_time, ltype):
        warnings.append("Auction ends soon")
    relisted = _seller_appearances_in_actives(seller, all_deals, title)
    if relisted >= 1:
        warnings.append("Returned-relist")

    # Seller / photo / naive signals
    feedback_str = (d.get("feedback") or "").rstrip("%")
    try:
        feedback_pct = float(feedback_str) if feedback_str else None
    except ValueError:
        feedback_pct = None
    naive = _naive_seller_signal(title) or _missing_parallel_year(title)

    # Photo signal — only the thumb URL is available; can't count images, but
    # we can flag stock-photo URLs eBay uses for catalog matches.
    img_url = d.get("image", "") or ""
    is_stock_photo = "/00/s-" not in img_url and "ebayimg.com" in img_url and "g/00" in img_url

    # Listing-type simplification for filters
    if "Auction" in ltype and "BIN" not in ltype:
        type_token = "Auction"
    elif "Offer" in ltype:
        type_token = "Best Offer"
    else:
        type_token = "BIN"

    return {
        **d,
        "asking":         round(asking, 2),
        "resale":         round(resale, 2),
        "net_profit":     net,
        "pct_below":      pct_below,
        "velocity_30d":   velocity,
        "warnings":       warnings,
        "feedback_pct":   feedback_pct,
        "naive_seller":   naive,
        "is_stock_photo": is_stock_photo,
        "type_token":     type_token,
        "end_time":       end_time,
    }


# ---------------------------------------------------------------------------
# Page render
# ---------------------------------------------------------------------------

def _badge(text: str, kind: str = "") -> str:
    cls = {
        "warn":   "badge badge-warning",
        "danger": "badge badge-danger",
        "ok":     "badge badge-success",
        "gold":   "tag tag-gold",
        "muted":  "tag",
    }.get(kind, "tag")
    return f'<span class="{cls}">{text}</span>'


def _warning_chip(w: str) -> str:
    if w == "Centering risk":
        return _badge(w, "warn")
    if w == "Thin comps":
        return _badge(w, "warn")
    if w == "Auction ends soon":
        return _badge(w, "danger")
    if w == "Returned-relist":
        return _badge(w, "danger")
    return _badge(w, "muted")


def _end_hint(end_time: str, ltype: str) -> str:
    if "Auction" not in (ltype or "") or not end_time:
        return ""
    try:
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
        return f' · ends {end_dt.strftime("%b %-d %-I:%M%p UTC")}'
    except Exception:
        return ""


def build_page(plan: dict) -> Path:
    flips = plan["flips"]
    cats  = sorted({(f.get("from_category") or "") for f in flips if f.get("from_category")})
    cat_options = '<option value="All">All categories</option>' + \
                  "".join(f'<option value="{c}">{c}</option>' for c in cats)

    cards = []
    for f in flips:
        url = promote._epn_wrap(f.get("url") or "")
        img = (
            f'<img src="{f["image"]}" alt="" loading="lazy">' if f.get("image")
            else '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:var(--text-dim);font-size:11px;">No image</div>'
        )

        # Listing-type badge
        ltype = f.get("listing_type", "BIN")
        if "Auction" in ltype:
            type_badge = _badge(ltype, "warn")
        elif "Offer" in ltype:
            type_badge = _badge(ltype, "gold")
        else:
            type_badge = _badge(ltype)

        warns_html = " ".join(_warning_chip(w) for w in f["warnings"])
        seller_chip = ""
        fb = f.get("feedback_pct")
        if fb is not None:
            seller_chip = f'<span class="seller-chip" title="Seller feedback">{f.get("seller","")} · {fb:.1f}%</span>'
        else:
            seller_chip = f'<span class="seller-chip">{f.get("seller","")}</span>'

        naive_chip   = ' <span class="tag tag-gold" title="Title heuristic: missing year or parallel keyword, or naive-seller phrase">Naive seller?</span>' if f.get("naive_seller") else ""
        stockphoto   = ' <span class="tag" title="Looks like an eBay catalog stock photo, not seller pics">Stock photo</span>' if f.get("is_stock_photo") else ""

        net = f["net_profit"]
        net_cls = "net-positive" if net > 0 else "net-negative"
        cat_tag = f'<span class="tag tag-gold">{f.get("from_category","")}</span>' if f.get("from_category") else ""

        cards.append(f'''
      <article class="flip-card"
        data-net="{net:.2f}"
        data-asking="{f["asking"]:.2f}"
        data-pct="{f["pct_below"]:.1f}"
        data-velocity="{f["velocity_30d"]}"
        data-cat="{f.get("from_category","")}"
        data-type="{f["type_token"]}"
        data-title="{(f.get("title","") or "").lower().replace(chr(34),"")}">
        <div class="flip-thumb">{img}</div>
        <div class="flip-body">
          <div class="flip-meta-row">
            {type_badge}
            {cat_tag}
            <span class="tag">{f.get("condition","Used")}</span>
            {warns_html}
            {naive_chip}{stockphoto}
          </div>
          <a href="{url}" target="_blank" rel="noopener" class="flip-title">{f.get("title","")[:140]}</a>
          <div class="flip-meta-row" style="margin-top:6px;">
            <span class="flip-from">Seen via <em>"{f.get("from_query","")}"</em>{_end_hint(f.get("end_time",""), ltype)}</span>
            {seller_chip}
          </div>
          <div class="flip-stats">
            <div><span class="lbl">Asking</span><span class="val">${f["asking"]:.2f}</span></div>
            <div><span class="lbl">Est. resale</span><span class="val">${f["resale"]:.2f}</span></div>
            <div><span class="lbl">% below comp</span><span class="val">{f["pct_below"]:.1f}%</span></div>
            <div><span class="lbl">Sold last 30d</span><span class="val">{f["velocity_30d"]}</span></div>
          </div>
        </div>
        <div class="flip-net-block">
          <div class="lbl">Net after fees</div>
          <div class="flip-net {net_cls}">${net:.2f}</div>
          <a href="{url}" target="_blank" rel="noopener" class="btn btn-gold" style="padding:8px 14px;font-size:11px;margin-top:8px;">Open on eBay</a>
        </div>
      </article>''')

    cards_html = "\n".join(cards) if cards else \
        '<div class="panel" style="text-align:center;padding:48px;color:var(--text-muted);">No candidate flips today. Try widening the comp threshold in deal_queries.json.</div>'

    # KPIs
    profitable = [f for f in flips if f["net_profit"] > 0]
    best       = max(flips, key=lambda x: x["net_profit"], default=None)
    best_net   = best["net_profit"] if best else 0
    best_url   = promote._epn_wrap((best or {}).get("url") or "#")
    total_pot  = sum(f["net_profit"] for f in profitable)
    avg_pct    = round(sum(f["pct_below"] for f in flips) / len(flips), 1) if flips else 0

    extra_css = """
    .flip-grid { display: grid; gap: 14px; margin-bottom: 28px; }
    .flip-card {
      display: grid;
      grid-template-columns: 124px 1fr 160px;
      gap: 18px; align-items: stretch;
      background: var(--surface);
      border: 1px solid var(--border);
      border-left: 3px solid var(--gold);
      border-radius: var(--r-lg);
      padding: 16px 20px;
      transition: all var(--t-fast);
    }
    .flip-card:hover { transform: translateY(-1px); border-color: var(--border-mid); }
    .flip-thumb {
      width: 124px; height: 124px;
      border-radius: var(--r-sm); overflow: hidden; background: var(--surface-3);
    }
    .flip-thumb img { width: 100%; height: 100%; object-fit: cover; }
    .flip-body { min-width: 0; }
    .flip-meta-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
    .flip-title { display: block; font-size: 15px; font-weight: 600; color: var(--text); line-height: 1.35; text-decoration: none; margin-top: 8px; }
    .flip-title:hover { color: var(--gold); }
    .flip-from { font-size: 11px; color: var(--text-muted); }
    .flip-from em { color: var(--gold); font-style: normal; font-weight: 600; }
    .seller-chip { font-size: 11px; color: var(--text-dim); margin-left: auto; }
    .flip-stats {
      display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px;
      margin-top: 12px; padding-top: 10px; border-top: 1px dashed var(--border);
    }
    .flip-stats > div { display: flex; flex-direction: column; gap: 2px; }
    .flip-stats .lbl { font-size: 10px; letter-spacing: .06em; text-transform: uppercase; color: var(--text-dim); }
    .flip-stats .val { font-size: 14px; font-weight: 600; color: var(--text); }
    .flip-net-block { text-align: right; align-self: center; }
    .flip-net-block .lbl { font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--text-muted); }
    .flip-net {
      font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500;
      font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1;
      font-size: 32px; line-height: 1; margin-top: 2px;
    }
    .net-positive { color: var(--gold); }
    .net-negative { color: #b04141; }
    @media (max-width: 720px) {
      .flip-card { grid-template-columns: 88px 1fr; padding: 12px; gap: 12px; }
      .flip-thumb { width: 88px; height: 88px; }
      .flip-stats { grid-template-columns: repeat(2, 1fr); }
      .flip-net-block { grid-column: 1 / -1; text-align: left; }
      .seller-chip { margin-left: 0; }
    }
    """

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">Buy-side flip candidates · net of eBay fees and shipping both ways</div>
        <h1 class="section-title">Resale <span class="accent">Flips</span></h1>
      </div>
      <div class="section-sub sh-sub">Listings priced below comp median with the net-profit math already done. Sort by net, filter out thin-comp and centering-risk landmines, then act before the auction clock runs out.</div>
    </div>

    <div class="stat-grid">
      <div class="stat-card"><div class="num">{len(flips)}</div><div class="lbl">Candidates</div></div>
      <div class="stat-card"><div class="num">{len(profitable)}</div><div class="lbl">Net Positive</div></div>
      <a class="stat-card linked" href="{best_url}" target="_blank" rel="noopener" title="Open best-net flip on eBay">
        <div class="num">${best_net:.0f}</div><div class="lbl">Best Net Flip</div>
      </a>
      <div class="stat-card"><div class="num">${total_pot:,.0f}</div><div class="lbl">Total Net Potential</div></div>
    </div>

    <div class="panel" style="margin-bottom:16px;">
      <div class="panel-head">
        <div class="panel-title">Cost model</div>
        <div class="panel-sub">eBay {EBAY_FVF_PCT*100:.0f}% FVF, ${FIXED_FEE:.2f} fixed, ${INBOUND_SHIP:.2f} in, ${OUTBOUND_SHIP:.2f} out, ${INBOUND_HANDLING:.2f} handling. Resale target = comp median.</div>
      </div>
    </div>

    <div class="filter-bar">
      <div class="filter-row">
        <input type="search" id="flip-search" class="search-input" placeholder="Filter by keyword (player, set, brand)..." oninput="flipApply()" autocomplete="off">
        <select id="flip-cat" onchange="flipApply()" style="max-width:220px;">{cat_options}</select>
        <select id="flip-type" onchange="flipApply()" style="max-width:180px;">
          <option value="All">All listing types</option>
          <option value="BIN">Buy It Now</option>
          <option value="Auction">Auction</option>
          <option value="Best Offer">Best Offer</option>
        </select>
        <select id="flip-sort" onchange="flipApply()" style="max-width:220px;">
          <option value="net-desc">Sort: Net profit high to low</option>
          <option value="pct-desc">Sort: Biggest % below comp</option>
          <option value="velocity-desc">Sort: Fastest sold velocity</option>
          <option value="asking-asc">Sort: Cheapest asking</option>
        </select>
      </div>
      <div class="filter-row">
        <label style="font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:6px;">
          Min net profit
          <input type="number" id="flip-min-net" value="0" step="5" style="width:90px;" oninput="flipApply()">
        </label>
        <label style="font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:6px;">
          Min sold velocity (30d)
          <input type="number" id="flip-min-vel" value="0" step="1" style="width:80px;" oninput="flipApply()">
        </label>
        <label style="font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:6px;">
          <input type="checkbox" id="flip-hide-thin" onchange="flipApply()"> Hide thin comps
        </label>
        <label style="font-size:12px;color:var(--text-muted);display:flex;align-items:center;gap:6px;">
          <input type="checkbox" id="flip-hide-center" onchange="flipApply()"> Hide centering risk
        </label>
      </div>
    </div>

    <div id="flip-results-meta" style="font-size:12px;color:var(--text-muted);margin-bottom:14px;letter-spacing:.08em;text-transform:uppercase;font-weight:600;">
      Showing <span id="flip-visible-count">{len(cards)}</span> of {len(cards)} candidates
    </div>

    <div class="flip-grid" id="flip-grid">
      {cards_html}
    </div>

    <script>
      window.flipApply = function() {{
        const q    = (document.getElementById('flip-search').value || '').toLowerCase().trim();
        const cat  = document.getElementById('flip-cat').value;
        const type = document.getElementById('flip-type').value;
        const sort = document.getElementById('flip-sort').value;
        const minNet = parseFloat(document.getElementById('flip-min-net').value) || 0;
        const minVel = parseFloat(document.getElementById('flip-min-vel').value) || 0;
        const hideThin   = document.getElementById('flip-hide-thin').checked;
        const hideCenter = document.getElementById('flip-hide-center').checked;
        const grid = document.getElementById('flip-grid');
        const cards = Array.from(grid.querySelectorAll('.flip-card'));
        let vis = 0;
        cards.forEach(c => {{
          const net = parseFloat(c.dataset.net);
          const vel = parseFloat(c.dataset.velocity);
          let ok = true;
          if (q && !(c.dataset.title || '').includes(q)) ok = false;
          if (ok && cat !== 'All' && c.dataset.cat !== cat) ok = false;
          if (ok && type !== 'All' && c.dataset.type !== type) ok = false;
          if (ok && net < minNet) ok = false;
          if (ok && vel < minVel) ok = false;
          if (ok && hideThin   && c.querySelector('.badge-warning')?.textContent === 'Thin comps') ok = false;
          if (ok && hideThin   && Array.from(c.querySelectorAll('.badge-warning, .tag')).some(b => b.textContent === 'Thin comps')) ok = false;
          if (ok && hideCenter && Array.from(c.querySelectorAll('.badge-warning, .tag')).some(b => b.textContent === 'Centering risk')) ok = false;
          c.style.display = ok ? '' : 'none';
          if (ok) vis++;
        }});
        document.getElementById('flip-visible-count').textContent = vis;
        const visCards = cards.filter(c => c.style.display !== 'none');
        const keyMap = {{
          'net-desc':       c => -parseFloat(c.dataset.net),
          'pct-desc':       c => -parseFloat(c.dataset.pct),
          'velocity-desc':  c => -parseFloat(c.dataset.velocity),
          'asking-asc':     c =>  parseFloat(c.dataset.asking),
        }};
        const keyFn = keyMap[sort] || keyMap['net-desc'];
        visCards.sort((a, b) => keyFn(a) - keyFn(b));
        visCards.forEach(c => grid.appendChild(c));
      }};
      flipApply();
    </script>
    """

    html = promote.html_shell(
        title="Resale Flips — Harpua2001",
        body=body,
        extra_head=f"<style>{extra_css}</style>",
        active_page="resale_flips.html",
    )
    HTML_FILE.write_text(html, encoding="utf-8")
    return HTML_FILE


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    cfg = load_cfg()
    sold = load_sold_history()
    source = get_source_listings(cfg)

    # Flatten the deals from the source payload, attach query meta.
    all_deals = []
    for q in source.get("queries", []):
        for d in q.get("deals", []):
            all_deals.append({**d, "from_query": q.get("q", ""),
                              "from_category": q.get("category", "")})

    # Score each into a flip candidate. Skip rows that score returns None.
    flips = []
    for d in all_deals:
        scored = score_listing(d, all_deals, sold)
        if scored:
            flips.append(scored)
    flips.sort(key=lambda x: -x["net_profit"])

    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_queries": len(source.get("queries", [])),
        "source_deals": sum(len(q.get("deals", [])) for q in source.get("queries", [])),
        "total_candidates": len(flips),
        "net_positive": sum(1 for f in flips if f["net_profit"] > 0),
        "cost_model": {
            "ebay_fvf_pct": EBAY_FVF_PCT,
            "fixed_fee": FIXED_FEE,
            "inbound_ship": INBOUND_SHIP,
            "outbound_ship": OUTBOUND_SHIP,
            "inbound_handling": INBOUND_HANDLING,
        },
        "flips": flips,
    }
    PLAN_FILE.write_text(json.dumps(plan, indent=2, default=str), encoding="utf-8")
    print(f"Wrote {PLAN_FILE} ({len(flips)} candidates)")

    out_html = build_page(plan)
    print(f"Wrote {out_html} ({out_html.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
