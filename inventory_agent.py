"""
inventory_agent.py — your unlisted-card inventory, ready to list on eBay.

Reads `inventory.csv` (export from SportsCardsPro "My Collection", or
hand-maintain). For each card:
  • Match to PriceCharting / SCP cache for a current market price
  • Suggest an eBay-best-practices title (year + brand + player + parallel + sport)
  • Map to one of the 8 store custom categories (matches website)
  • Render row with a "Generate Listing" button → opens a modal with
    AddItem XML and a Copy-Listing-Info block ready to paste into eBay UI
  • Optional Phase 2: live AddItem POST via Trading API

CSV columns (extras ignored):
  name, year, set, card_number, player, sport, parallel, grade, grader,
  condition, quantity, acquired_price, image_url, notes

Output:
  output/inventory_plan.json
  docs/inventory.html
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import promote

REPO_ROOT = Path(__file__).parent
CSV_PATH  = REPO_ROOT / "inventory.csv"
PLAN_PATH = REPO_ROOT / "output" / "inventory_plan.json"
REPORT    = REPO_ROOT / "docs"   / "inventory.html"
SCP_CACHE = REPO_ROOT / "sportscardspro_prices.json"

# eBay primary category IDs — single-card categories
EBAY_CATEGORY = {
    "Football":   "215",   # Sports Mem, Cards & Fan Shop > Sports Trading Cards > Football
    "Basketball": "214",
    "Baseball":   "213",
    "Hockey":     "216",
    "Pokemon":    "183454",  # Toys & Hobbies > Collectible Card Games > Pokemon TCG
    "Other":      "212",
}


# --------------------------------------------------------------------------- #
# CSV load                                                                     #
# --------------------------------------------------------------------------- #

def load_inventory() -> list[dict]:
    if not CSV_PATH.exists():
        print(f"  No {CSV_PATH.name} found — create it with these columns:")
        print(f"  name,year,set,card_number,player,sport,parallel,grade,grader,condition,quantity,acquired_price,image_url,notes")
        return []
    rows: list[dict] = []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            r = {k.strip(): (v or "").strip() for k, v in r.items() if k}
            if not r.get("name"):
                continue
            rows.append(r)
    return rows


# --------------------------------------------------------------------------- #
# Enrichment                                                                   #
# --------------------------------------------------------------------------- #

def _load_scp_cache() -> dict[str, dict]:
    """SCP cache is keyed by item_id (eBay listings). We can't directly look up
    by inventory row, but we'll fuzz-match by title tokens."""
    try:
        return json.loads(SCP_CACHE.read_text())
    except (OSError, ValueError):
        return {}


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[A-Za-z0-9]+", (s or "").lower()) if len(t) > 1}


def _scp_match(row: dict, cache: dict) -> dict | None:
    """Best-effort match — find SCP entries whose title shares >=4 distinct
    tokens with the inventory row's name."""
    row_toks = _tokens(row.get("name", ""))
    if len(row_toks) < 4:
        return None
    best, best_overlap = None, 0
    for v in cache.values():
        cand_toks = _tokens(v.get("matched_product") or v.get("title") or "")
        overlap = len(row_toks & cand_toks)
        if overlap > best_overlap:
            best_overlap, best = overlap, v
    return best if best_overlap >= 4 else None


def _category(row: dict) -> tuple[str, str]:
    """Returns (display_name, ebay_category_id) for the row."""
    sport = (row.get("sport") or "").strip().title()
    if sport in EBAY_CATEGORY:
        return sport, EBAY_CATEGORY[sport]
    # Try to infer from the name
    name = row.get("name", "").lower()
    if "pokemon" in name or "pikachu" in name or "charizard" in name:
        return "Pokemon", EBAY_CATEGORY["Pokemon"]
    if any(w in name for w in ("nfl", "football", "panini prizm", "topps chrome")):
        return "Football", EBAY_CATEGORY["Football"]
    if "nba" in name or "basketball" in name:
        return "Basketball", EBAY_CATEGORY["Basketball"]
    if "mlb" in name or "baseball" in name:
        return "Baseball", EBAY_CATEGORY["Baseball"]
    return "Other", EBAY_CATEGORY["Other"]


def _suggest_title(row: dict) -> str:
    """eBay best-practices title: year + set + player + parallel + sport.
    Caps at 80 chars (eBay max)."""
    parts: list[str] = []
    if row.get("year"):       parts.append(row["year"])
    if row.get("set"):        parts.append(row["set"])
    if row.get("player"):     parts.append(row["player"])
    if row.get("card_number") and not row.get("card_number").startswith("#"):
        parts.append(f"#{row['card_number']}")
    elif row.get("card_number"):
        parts.append(row["card_number"])
    if row.get("parallel"):   parts.append(row["parallel"])
    if row.get("grader") and row.get("grade"):
        parts.append(f"{row['grader']} {row['grade']}")
    sport = (row.get("sport") or "").strip().title()
    if sport and sport not in {p.lower().title() for p in parts}:
        parts.append(sport)
    title = " ".join(parts)
    title = re.sub(r"\s+", " ", title).strip()
    return title[:80]


def _suggest_price(row: dict, scp: dict | None) -> dict:
    """Return {price, basis, low, high}."""
    # 1. SCP cache hit (best signal)
    if scp:
        grade_key = (row.get("grade") or "ungraded").lower()
        for key in ("psa10_price", "psa9_price", "psa8_price",
                    "graded_price", "ungraded_price", "loose_price"):
            v = scp.get(key)
            if v and float(v) > 0:
                price = float(v) * 0.92  # list 8% below market for fast move
                return {"price": round(price, 2), "basis": f"SCP {key}",
                        "low": round(price * 0.85, 2), "high": round(price * 1.15, 2)}
    # 2. Acquired-price 2x fallback
    try:
        ap = float(row.get("acquired_price") or 0)
        if ap > 0:
            return {"price": round(ap * 2, 2), "basis": "2x acquired",
                    "low": round(ap * 1.5, 2), "high": round(ap * 3, 2)}
    except ValueError:
        pass
    # 3. Default $4.99
    return {"price": 4.99, "basis": "default", "low": 3.99, "high": 6.99}


def _suggest_specifics(row: dict, category: str) -> dict[str, str]:
    """Item Specifics eBay wants. Different per category but a common core applies."""
    out: dict[str, str] = {}
    if row.get("year"):           out["Year"] = row["year"]
    if row.get("set"):            out["Set"] = row["set"]
    if row.get("player"):
        if category in ("Pokemon",):
            out["Character"] = row["player"]
        else:
            out["Player/Athlete"] = row["player"]
            out["Athlete"] = row["player"]
    if row.get("card_number"):    out["Card Number"] = str(row["card_number"]).lstrip("#")
    if row.get("parallel"):       out["Parallel/Variety"] = row["parallel"]
    if row.get("grader") and row.get("grade"):
        out["Graded"] = "Yes"
        out["Professional Grader"] = row["grader"]
        out["Grade"] = row["grade"]
    else:
        out["Graded"] = "No"
    sport = (row.get("sport") or "").title()
    if sport and category != "Pokemon":
        out["Sport"] = sport
    return out


# --------------------------------------------------------------------------- #
# Plan + render                                                                #
# --------------------------------------------------------------------------- #

def build_plan() -> dict:
    rows = load_inventory()
    scp = _load_scp_cache()
    enriched: list[dict] = []
    for r in rows:
        cat_name, cat_id = _category(r)
        scp_match = _scp_match(r, scp)
        price_rec = _suggest_price(r, scp_match)
        title     = _suggest_title(r) or r.get("name", "")
        specifics = _suggest_specifics(r, cat_name)
        enriched.append({
            "raw":            r,
            "title":          title,
            "ebay_category":  cat_name,
            "category_id":    cat_id,
            "store_category": cat_name,  # matches our 8-bucket store sidebar
            "price":          price_rec["price"],
            "price_basis":    price_rec["basis"],
            "price_low":      price_rec["low"],
            "price_high":     price_rec["high"],
            "specifics":      specifics,
            "scp_match":      bool(scp_match),
            "image_url":      r.get("image_url", ""),
        })
    return {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count":         len(enriched),
        "ready":         sum(1 for e in enriched if e["image_url"]),
        "needs_photo":   sum(1 for e in enriched if not e["image_url"]),
        "items":         enriched,
    }


def save_plan(plan: dict) -> Path:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


def _esc(s: Any) -> str:
    return html.escape(str(s or ""))


def render_report(plan: dict) -> Path:
    items = plan["items"]
    total_value = sum(e["price"] for e in items)

    # KPI strip
    kpis = f"""
    <div class="stat-grid">
      <a class="stat-card linked" href="#inventory-table" title="Scroll to inventory">
        <div class="num">{plan['count']}</div><div class="lbl">Cards in inventory</div>
      </a>
      <a class="stat-card linked" href="#ready" title="Ready to list">
        <div class="num">{plan['ready']}</div><div class="lbl">Ready (have photo)</div>
      </a>
      <a class="stat-card linked" href="#needs-photo" title="Missing photo">
        <div class="num">{plan['needs_photo']}</div><div class="lbl">Need photo upload</div>
      </a>
      <div class="stat-card">
        <div class="num">${total_value:,.0f}</div><div class="lbl">Total list value</div>
      </div>
    </div>
    """

    # Per-row inventory table
    if not items:
        body_rows = '<tr><td colspan="6" class="inv-empty">No inventory yet. Create <code>inventory.csv</code> at the repo root with columns: name,year,set,card_number,player,sport,parallel,grade,grader,condition,quantity,acquired_price,image_url,notes</td></tr>'
    else:
        body_rows = ""
        for i, e in enumerate(items):
            r = e["raw"]
            img_html = (f'<img src="{_esc(e["image_url"])}" alt="" loading="lazy">'
                        if e["image_url"] else '<div class="inv-noimg">no photo</div>')
            ready = bool(e["image_url"])
            btn_disabled = "" if ready else "disabled title=\"Add image_url to CSV first\""
            specifics_json = json.dumps(e["specifics"])
            body_rows += f"""
            <tr id="row-{i}" data-ready="{1 if ready else 0}">
              <td class="inv-img-cell">{img_html}</td>
              <td>
                <div class="inv-title">{_esc(e['title'])}</div>
                <div class="inv-sub">{_esc(r.get('condition','—'))} · {_esc(e['ebay_category'])} → eBay cat {_esc(e['category_id'])}</div>
              </td>
              <td class="num">
                <div class="inv-price">${e['price']:.2f}</div>
                <div class="inv-pb">{_esc(e['price_basis'])}</div>
                <div class="inv-pb">range ${e['price_low']:.2f}–${e['price_high']:.2f}</div>
              </td>
              <td>
                <details><summary>{len(e['specifics'])} specifics</summary>
                  <ul class="inv-spec">{''.join(f'<li><b>{_esc(k)}</b>: {_esc(v)}</li>' for k, v in e['specifics'].items())}</ul>
                </details>
              </td>
              <td>
                <button class="btn btn-outline btn-sm" onclick='invShowListing({i})'>Show listing info</button>
                <button class="btn btn-gold btn-sm" {btn_disabled}
                        onclick='invDraftOnEbay({i})'>Draft on eBay →</button>
              </td>
            </tr>
            <script type="application/json" id="listing-{i}">{specifics_json}</script>"""

    # Modal for showing listing info / draft flow
    modal_html = """
    <div id="inv-modal" class="inv-modal" style="display:none;">
      <div class="inv-modal-box">
        <button class="inv-close" onclick="invCloseModal()">×</button>
        <div id="inv-modal-content"></div>
      </div>
    </div>
    """

    # Embedded items JSON for the JS (single source of truth on the page)
    items_json = json.dumps(items)

    body = f"""
    <div class="section-head section-head--inline">
      <div class="sh-title">
        <div class="eyebrow">SportsCardsPro inventory · ready to list</div>
        <h1 class="section-title">My <span class="accent">Inventory</span></h1>
      </div>
      <div class="section-sub sh-sub">
        Cards I own but haven't listed yet. Each row is an eBay-ready draft —
        title, category, suggested price, and item specifics derived from your
        SCP export. Click <b>Show listing info</b> to copy a formatted block,
        or <b>Draft on eBay →</b> to create a real draft listing (Phase 2 —
        requires image upload + Lambda /ebay/create-listing route).
      </div>
    </div>

    {kpis}

    <div class="action-bar">
      <button class="btn btn-outline" onclick="invExportCSV()">Export draft CSV</button>
      <span class="inv-hint">Drop your SportsCardsPro export at <code>inventory.csv</code> (root of repo) and re-run <code>python3 inventory_agent.py</code>.</span>
    </div>

    <div id="inventory-table" class="inv-table-wrap">
      <table class="inv-table">
        <thead>
          <tr><th>Photo</th><th>Title (eBay-optimized)</th><th class="num">Suggested price</th><th>Specifics</th><th>Actions</th></tr>
        </thead>
        <tbody>{body_rows}</tbody>
      </table>
    </div>

    {modal_html}

    <script>
      const INV_ITEMS = {items_json};
      const LAMBDA = 'https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay';

      function invShowListing(i) {{
        const it = INV_ITEMS[i];
        const specBlock = Object.entries(it.specifics).map(([k,v]) => `  ${{k}}: ${{v}}`).join('\\n');
        const copyText = [
          `TITLE: ${{it.title}}`,
          `CATEGORY: ${{it.ebay_category}} (eBay ID: ${{it.category_id}})`,
          `STORE CATEGORY: ${{it.store_category}}`,
          `STARTING PRICE: $${{it.price.toFixed(2)}}  (basis: ${{it.price_basis}})`,
          `PRICE RANGE: $${{it.price_low.toFixed(2)}}–$${{it.price_high.toFixed(2)}}`,
          ``,
          `ITEM SPECIFICS:`,
          specBlock,
        ].join('\\n');
        const html = `
          <h3>${{it.title}}</h3>
          <p class="inv-hint">Copy this block, paste into eBay's Sell-Your-Item form. Each line maps to an eBay field.</p>
          <textarea class="inv-copy" readonly rows="14">${{copyText}}</textarea>
          <button class="btn btn-outline" onclick="navigator.clipboard.writeText(this.previousElementSibling.value);this.textContent='Copied!';">Copy to clipboard</button>
          <a class="btn btn-gold" href="https://www.ebay.com/sl/sell" target="_blank" rel="noopener" style="margin-left:8px;">Open eBay Sell-Your-Item form →</a>
        `;
        document.getElementById('inv-modal-content').innerHTML = html;
        document.getElementById('inv-modal').style.display = 'flex';
      }}

      async function invDraftOnEbay(i) {{
        const it = INV_ITEMS[i];
        if (!it.image_url) {{ alert('Add image_url to the CSV row first.'); return; }}
        if (!confirm(`Create live eBay draft for "${{it.title}}" at $${{it.price.toFixed(2)}}?`)) return;
        document.getElementById('inv-modal-content').innerHTML = '<h3>Drafting...</h3><pre id="inv-resp">Calling Lambda /ebay/create-listing...</pre>';
        document.getElementById('inv-modal').style.display = 'flex';
        try {{
          const r = await fetch(LAMBDA + '/create-listing', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(it),
          }});
          const data = await r.json();
          document.getElementById('inv-resp').textContent = JSON.stringify(data, null, 2);
        }} catch (e) {{
          document.getElementById('inv-resp').textContent = 'Lambda route /ebay/create-listing not deployed yet (Phase 2). Error: ' + e;
        }}
      }}

      function invCloseModal() {{ document.getElementById('inv-modal').style.display = 'none'; }}

      function invExportCSV() {{
        const headers = ['title','price','category','category_id','store_category','image_url'];
        const lines = [headers.join(',')];
        for (const it of INV_ITEMS) {{
          lines.push([it.title, it.price, it.ebay_category, it.category_id, it.store_category, it.image_url].map(v => `"${{(v||'').toString().replace(/"/g,'""')}}"`).join(','));
        }}
        const blob = new Blob([lines.join('\\n')], {{type: 'text/csv'}});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'ebay_drafts.csv'; a.click();
        URL.revokeObjectURL(url);
      }}
    </script>
    """

    extra_css = """
<style>
  .inv-table-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; margin: 18px 0; }
  .inv-table { width: 100%; border-collapse: collapse; }
  .inv-table th, .inv-table td { padding: 12px 14px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .inv-table th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .inv-table tr:last-child td { border-bottom: none; }
  .inv-table tr:hover td { background: var(--surface-2); }
  .inv-table .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .inv-img-cell { width: 80px; }
  .inv-img-cell img { width: 64px; height: 64px; object-fit: cover; border-radius: 6px; }
  .inv-noimg { width: 64px; height: 64px; display:flex; align-items:center; justify-content:center; background:var(--surface-2); border:1px dashed var(--border); border-radius:6px; color:var(--text-dim); font-size:10px; }
  .inv-title { font-weight: 600; color: var(--text); }
  .inv-sub { font-size: 11px; color: var(--text-muted); margin-top: 4px; }
  .inv-price { font-family: 'Bebas Neue', sans-serif; font-size: 22px; color: var(--gold); }
  .inv-pb { font-size: 10px; color: var(--text-dim); margin-top: 2px; }
  .inv-spec { list-style: none; padding: 8px 0 0 12px; margin: 0; font-size: 12px; }
  .inv-spec li { padding: 2px 0; color: var(--text-muted); }
  .inv-spec li b { color: var(--text); }
  .inv-empty { text-align: center; padding: 40px; color: var(--text-muted); }
  .inv-empty code { background: var(--surface-2); padding: 2px 6px; border-radius: 4px; font-size: 11px; }
  .inv-hint { color: var(--text-muted); font-size: 13px; }
  .inv-modal { position: fixed; inset: 0; background: rgba(0,0,0,.7); backdrop-filter: blur(4px); z-index: 100; display: flex; align-items: center; justify-content: center; padding: 20px; }
  .inv-modal-box { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 28px; max-width: 720px; width: 100%; max-height: 90vh; overflow: auto; position: relative; }
  .inv-close { position: absolute; top: 12px; right: 16px; background: none; border: none; color: var(--text-muted); font-size: 28px; cursor: pointer; }
  .inv-close:hover { color: var(--text); }
  .inv-copy { width: 100%; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: 12px; color: var(--text); font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; margin: 14px 0; }
  .action-bar { display:flex; align-items:center; gap:14px; margin:12px 0; flex-wrap:wrap; }
  details summary { cursor: pointer; color: var(--gold); font-size: 12px; }
</style>
"""
    html_doc = promote.html_shell("Inventory · Harpua2001", body,
                                  extra_head=extra_css,
                                  active_page="inventory.html")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(html_doc, encoding="utf-8")
    return REPORT


def ensure_nav_entry() -> None:
    entry = ("inventory.html", "Inventory", False, "Sell")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    for idx, it in enumerate(items):
        if it[0] == "price_review.html":
            items.insert(idx, entry); break
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
    print(f"  Inventory: {plan['count']} cards loaded  ({plan['ready']} ready, {plan['needs_photo']} need photos)")
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Report: {out}")


if __name__ == "__main__":
    main()
