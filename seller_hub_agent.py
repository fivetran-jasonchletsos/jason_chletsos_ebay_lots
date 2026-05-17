"""
seller_hub_agent.py — derives the Seller Hub artifacts that should mirror
the buyer-facing website, and renders docs/seller_hub.html.

Phase 1 (this file): READ-ONLY. Produces a plan + admin preview page.
Phase 2/3 will add Lambda endpoints that actually mutate the eBay store
(Trading SetStoreCategories, Marketing item_promotion, ad_campaign).

What it derives:
  - Store categories: bucket counts using promote._categorize() — the
    SAME taxonomy the storefront pages use. Drives the eBay store
    sidebar so buyers landing at ebay.com/str/harpua2001 see the same
    nav as the website.
  - Featured items: top 6 priced items with images (mirrors
    promote.build_dashboard's top_picks heuristic).
  - Promotion proposals: re-reads output/promotions_plan.json and
    output/promoted_listings_plan.json so the admin can see what's
    queued, without re-running those agents.

Run:
    python3 seller_hub_agent.py             # build plan + report
    python3 seller_hub_agent.py --report-only

Artifacts:
    output/seller_hub_plan.json    structured plan
    docs/seller_hub.html           admin preview
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import promote

REPO_ROOT  = Path(__file__).parent
OUTPUT_DIR = REPO_ROOT / "output"
DOCS_DIR   = REPO_ROOT / "docs"
PLAN_PATH  = OUTPUT_DIR / "seller_hub_plan.json"
REPORT_PATH = DOCS_DIR / "seller_hub.html"

# eBay Store custom-category limits (Basic+ subscription):
#   - 300 top-level + 300 subcategories
#   - 30-char name limit
# Our taxonomy is way under both. We just enforce the name limit.
EBAY_CATEGORY_NAME_MAX = 30


# --------------------------------------------------------------------------- #
# Snapshot loading                                                            #
# --------------------------------------------------------------------------- #

def _load_json(path: Path) -> dict | list | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_snapshot() -> list[dict]:
    snap = _load_json(OUTPUT_DIR / "listings_snapshot.json") or []
    if not isinstance(snap, list):
        return []
    return snap


# --------------------------------------------------------------------------- #
# Phase 1a — store categories                                                 #
# --------------------------------------------------------------------------- #

def derive_store_categories(listings: list[dict]) -> list[dict]:
    """Group listings into the same buckets the website shows. Return one
    record per category with item count, value, and a sample item id list
    so the admin can verify the mapping looks right before pushing live.
    """
    buckets: dict[str, dict] = {}
    for l in listings:
        cat = promote._categorize(l)
        b = buckets.setdefault(cat, {
            "name":        cat[:EBAY_CATEGORY_NAME_MAX],
            "raw_name":    cat,
            "count":       0,
            "total_value": 0.0,
            "sample_ids":  [],
        })
        b["count"] += 1
        try:
            b["total_value"] += float(l.get("price") or 0)
        except (TypeError, ValueError):
            pass
        if len(b["sample_ids"]) < 3:
            b["sample_ids"].append(l["item_id"])
    # Order categories the way they're rendered on index.html: by count desc.
    return sorted(buckets.values(), key=lambda x: x["count"], reverse=True)


# --------------------------------------------------------------------------- #
# Phase 1b — featured items                                                   #
# --------------------------------------------------------------------------- #

def derive_featured_items(listings: list[dict], n: int = 6) -> list[dict]:
    """Top-N priced items with images. eBay storefront 'Featured' carousel
    needs items with strong photography + price. Same heuristic the
    homepage hero uses.
    """
    with_pic = [l for l in listings if l.get("pic")]
    def _price(l):
        try: return float(l.get("price") or 0)
        except (TypeError, ValueError): return 0
    return sorted(with_pic, key=_price, reverse=True)[:n]


# --------------------------------------------------------------------------- #
# Phase 1c — promotion + ad rollup (read-only)                                #
# --------------------------------------------------------------------------- #

def load_promotion_summary() -> dict:
    """Read the latest plan files from sister agents so the Seller Hub view
    shows ALL revenue moves on one page (not just store-level config).

    Plan shapes (as produced by promotions_agent.py and promoted_listings_agent.py):
      promotions_plan.json     → top-level "markdowns" list; each item has
                                 "decision" ("apply" | "skip" | "blocked"),
                                 "discount_pct", "current_price", "target_price",
                                 and top-level "volume_discount" dict.
      promoted_listings_plan.json → top-level "decisions" list; each item has
                                 "tier" (lowercase: "standard"|"no_ad"|...),
                                 "rate" (0..1 fraction), "price", and
                                 "projected_30d_spend"/"projected_30d_lift_usd".
    """
    markdowns = _load_json(OUTPUT_DIR / "promotions_plan.json") or {}
    ads       = _load_json(OUTPUT_DIR / "promoted_listings_plan.json") or {}

    md_plan = (markdowns.get("markdowns") or markdowns.get("plan")
               or markdowns.get("decisions") or [])
    md_apply = [m for m in md_plan if (m.get("decision") or "").lower() == "apply"]
    md_total = sum(
        max((m.get("current_price") or 0) - (m.get("target_price") or 0), 0)
        for m in md_apply
    )

    # Volume discount: agent emits {"action": "would_create"|"in_sync"|..., ...}
    vol = markdowns.get("volume_discount") or {}
    vol_enabled = (vol.get("action") in ("would_create", "in_sync", "created", "updated")
                   if isinstance(vol, dict) else bool(vol))

    ad_plan  = ads.get("decisions") or ads.get("plan") or []
    ad_apply = [a for a in ad_plan if (a.get("rate") or a.get("recommended_rate") or 0) > 0]
    ad_spend = sum((a.get("projected_30d_spend") or 0) for a in ad_apply) or sum(
        (a.get("rate") or a.get("recommended_rate") or 0) * (a.get("price") or 0)
        for a in ad_apply
    )
    ad_lift  = sum((a.get("projected_30d_lift_usd") or 0) for a in ad_apply)

    return {
        "markdowns": {
            "queued":         len(md_apply),
            "total_discount": round(md_total, 2),
            "volume_discount_enabled": vol_enabled,
        },
        "promoted_listings": {
            "queued":     len(ad_apply),
            "ad_spend":   round(ad_spend, 2),
            "projected_lift": round(ad_lift, 2),
            "tier_split": _tier_split(ad_apply),
        },
    }


def _tier_split(items: list[dict]) -> dict[str, int]:
    out: dict[str, int] = {}
    for a in items:
        t = (a.get("tier") or a.get("recommended_tier") or "STANDARD").upper()
        out[t] = out.get(t, 0) + 1
    return out


# --------------------------------------------------------------------------- #
# Plan assembly                                                               #
# --------------------------------------------------------------------------- #

def build_plan() -> dict:
    listings = _load_snapshot()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "seller":       promote.SELLER_NAME,
        "store_url":    f"https://www.ebay.com/str/{promote.SELLER_NAME.lower()}",
        "listings_total": len(listings),
        "categories":   derive_store_categories(listings),
        "featured":     [
            {"item_id": l["item_id"], "title": l["title"],
             "price": float(l.get("price") or 0),
             "pic":   l.get("pic"), "url": l.get("url")}
            for l in derive_featured_items(listings)
        ],
        "promotions":   load_promotion_summary(),
    }


def save_plan(plan: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


# --------------------------------------------------------------------------- #
# HTML report — admin preview                                                  #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    try: return f"${float(n):,.0f}"
    except (TypeError, ValueError): return "—"


def render_report(plan: dict) -> Path:
    cats     = plan["categories"]
    featured = plan["featured"]
    promos   = plan["promotions"]

    # ---- KPI strip (Healthcare-Epic style: big number + lever footer) ---- #
    total_cats  = len(cats)
    total_items = plan["listings_total"]
    md = promos["markdowns"]
    pl = promos["promoted_listings"]
    kpis_html = f"""
    <div class="sh-kpis">
      <div class="sh-kpi">
        <div class="sh-kpi-n">{total_cats}</div>
        <div class="sh-kpi-l">Store categories to sync</div>
        <div class="sh-kpi-foot">Matches the website nav exactly</div>
      </div>
      <div class="sh-kpi">
        <div class="sh-kpi-n">{total_items}</div>
        <div class="sh-kpi-l">Listings ready to bucket</div>
        <div class="sh-kpi-foot">All active inventory</div>
      </div>
      <div class="sh-kpi">
        <div class="sh-kpi-n">{pl['queued']}</div>
        <div class="sh-kpi-l">Promoted-Listings queued</div>
        <div class="sh-kpi-foot">~{_fmt_money(pl['ad_spend'])} ad spend / mo</div>
      </div>
      <div class="sh-kpi">
        <div class="sh-kpi-n">{md['queued']}</div>
        <div class="sh-kpi-l">Markdowns queued</div>
        <div class="sh-kpi-foot">{_fmt_money(md['total_discount'])} in discounts</div>
      </div>
    </div>"""

    # ---- categories table ---- #
    if not cats:
        cats_html = '<div class="sh-empty">No active listings found. Run a rebuild first.</div>'
    else:
        rows = []
        for c in cats:
            sample = " · ".join(c["sample_ids"])
            warn = ""
            if c["raw_name"] != c["name"]:
                warn = f' <span class="sh-warn" title="Truncated to 30 chars for eBay">trimmed→ "{c["name"]}"</span>'
            rows.append(f"""
              <tr>
                <td><b>{c['raw_name']}</b>{warn}</td>
                <td class="num">{c['count']}</td>
                <td class="num">{_fmt_money(c['total_value'])}</td>
                <td class="sh-mono">{sample}</td>
              </tr>""")
        cats_html = f"""
        <table class="sh-tbl">
          <thead><tr><th>Category</th><th class="num">Items</th><th class="num">Inventory $</th><th>Sample IDs</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        <div class="sh-actions">
          <button class="btn btn-outline" onclick="sellerHubPreview()">Preview from Lambda</button>
          <button class="btn btn-outline" onclick="sellerHubSync(true)">Dry-run sync</button>
          <button class="btn btn-gold"    onclick="sellerHubSync(false)"
                  title="Live write — calls Trading SetStoreCategories + bulk ReviseItem">Push to eBay live →</button>
          <span class="sh-hint">Live mode calls <code>/ebay/sync-store-categories</code>. Always run Dry-run first to see the diff.</span>
        </div>
        <pre id="sh-resp" class="sh-resp" style="display:none;"></pre>"""

    # ---- featured items strip ---- #
    if featured:
        cards = []
        for f in featured:
            pic = f.get("pic") or ""
            url = f.get("url") or "#"
            cards.append(f"""
            <a class="sh-feat" href="{url}" target="_blank" rel="noopener">
              <div class="sh-feat-img" style="background-image:url('{pic}');"></div>
              <div class="sh-feat-info">
                <div class="sh-feat-title">{(f['title'] or '')[:60]}</div>
                <div class="sh-feat-price">${f['price']:.2f}</div>
              </div>
            </a>""")
        feat_html = f'<div class="sh-feat-grid">{"".join(cards)}</div>'
    else:
        feat_html = '<div class="sh-empty">No featured candidates with images.</div>'

    # ---- promotions rollup ---- #
    tier_split = pl.get("tier_split") or {}
    tier_chips = " ".join(
        f'<span class="sh-chip">{t}: <b>{n}</b></span>' for t, n in tier_split.items()
    ) or '<span class="sh-hint">No active campaign tiers yet.</span>'
    promo_html = f"""
    <div class="sh-promo-grid">
      <div class="sh-card">
        <h4>Markdown Manager</h4>
        <div class="sh-row"><span>Queued items</span><b>{md['queued']}</b></div>
        <div class="sh-row"><span>Total discount</span><b>{_fmt_money(md['total_discount'])}</b></div>
        <div class="sh-row"><span>Volume discount</span><b>{'✓ on' if md['volume_discount_enabled'] else '— off'}</b></div>
        <a class="sh-link" href="promotions.html">Open Promotions agent →</a>
        <div class="sh-card-actions">
          <button class="btn btn-outline btn-sm" onclick="sellerHubPromoSync('promoted', true)">Dry-run sync</button>
        </div>
      </div>
      <div class="sh-card">
        <h4>Promoted Listings</h4>
        <div class="sh-row"><span>Items with ads</span><b>{pl['queued']}</b></div>
        <div class="sh-row"><span>Monthly ad spend</span><b>{_fmt_money(pl['ad_spend'])}</b></div>
        <div class="sh-row"><span>Projected 30d lift</span><b style="color:var(--success);">{_fmt_money(pl.get('projected_lift', 0))}</b></div>
        <div class="sh-row sh-tier-row"><span>Tier split</span><span class="sh-tier-chips">{tier_chips}</span></div>
        <a class="sh-link" href="promoted_listings.html">Open Promoted Ads agent →</a>
        <div class="sh-card-actions">
          <button class="btn btn-outline btn-sm" onclick="sellerHubPromoSync('promoted', true)">Dry-run sync</button>
          <button class="btn btn-gold btn-sm"    onclick="sellerHubPromoSync('promoted', false)">Push bids live →</button>
        </div>
      </div>
    </div>"""

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">eBay Seller Hub · sync layer</div>
        <h1 class="section-title">Seller <span class="accent">Hub</span></h1>
        <div class="section-sub">
          Mirror the website's structure into your eBay store at
          <a href="{plan['store_url']}" target="_blank" rel="noopener">{plan['store_url']}</a>.
          Same categories, same featured items, same revenue moves.
          Phase 1 is read-only: preview here, push live in Phase 2.
        </div>
      </div>
    </div>

    {kpis_html}

    <section class="sh-section">
      <div class="sh-section-head">
        <h2>Store categories <span class="sh-count">{total_cats}</span></h2>
        <span class="sh-hint">Derived from <code>promote._categorize()</code> — identical to the buckets on
        <a href="index.html">index.html</a>, <a href="steals.html">steals.html</a>, and the rest of the site.</span>
      </div>
      {cats_html}
    </section>

    <section class="sh-section">
      <div class="sh-section-head">
        <h2>Featured items <span class="sh-count">{len(featured)}</span></h2>
        <span class="sh-hint">Top-priced listings with images. eBay storefronts let you pin a hero strip — these are the candidates.</span>
      </div>
      {feat_html}
    </section>

    <section class="sh-section">
      <div class="sh-section-head">
        <h2>Promotions &amp; Promoted Listings</h2>
        <span class="sh-hint">Rollup of the two existing agents. Drives the Marketing tab in Seller Hub.</span>
      </div>
      {promo_html}
    </section>

    <section class="sh-section">
      <div class="sh-section-head">
        <h2>More tools</h2>
        <span class="sh-hint">Sister agents that produce admin pages — each with its own dry-run + apply flow.</span>
      </div>
      <div class="sh-feat-grid">
        <a class="sh-feat" href="best_offer.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">Best Offer</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">Auto-accept · auto-decline</div>
          </div>
        </a>
        <a class="sh-feat" href="combined_shipping.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">Combined Shipping</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">$0.50 ea additional · $5 cap</div>
          </div>
        </a>
        <a class="sh-feat" href="vault.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">eBay Vault</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">$250+ singles · authenticated ship</div>
          </div>
        </a>
        <a class="sh-feat" href="photo_quality.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">Photo Quality Audit</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">Cassini rank: 8+ photos required</div>
          </div>
        </a>
        <a class="sh-feat" href="email_campaign.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">Email Campaign</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">Weekly Steals to followers</div>
          </div>
        </a>
        <a class="sh-feat" href="promotions.html">
          <div class="sh-feat-info">
            <div class="sh-feat-title">Markdowns</div>
            <div class="sh-feat-price" style="font-size:13px;color:var(--text-muted);">Stale-inventory ladder + volume</div>
          </div>
        </a>
      </div>
    </section>

    <section class="sh-section">
      <div class="sh-section-head">
        <h2>Phased rollout</h2>
      </div>
      <ol class="sh-phases">
        <li><b>Phase 1 — Preview (now).</b> This page. Confirms the website-to-store mapping is correct before any writes.</li>
        <li><b>Phase 2 — Categories sync.</b> Lambda endpoint <code>/ebay/sync-store-categories</code> calls Trading
          <code>SetStoreCategories</code> + bulk <code>ReviseItem</code> with <code>Item.Storefront.StoreCategoryID</code>.</li>
        <li><b>Phase 3 — Promotions / Promoted Ads.</b> Existing agents already write to <code>/sell/marketing/v1</code>;
          this page just becomes the single launchpad.</li>
      </ol>
    </section>

    <script>
      const SH_LAMBDA = 'https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay';

      function shShow(label, data, isError) {{
        const el = document.getElementById('sh-resp');
        el.className = 'sh-resp' + (isError ? ' sh-resp-err' : ' sh-resp-ok');
        el.style.display = 'block';
        el.textContent = '// ' + label + ' · ' + new Date().toLocaleTimeString() + '\\n' +
          (typeof data === 'string' ? data : JSON.stringify(data, null, 2));
        el.scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
      }}

      async function sellerHubPreview() {{
        try {{
          const r = await fetch(SH_LAMBDA + '/preview-store-categories', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: '{{}}'
          }});
          shShow('GET /preview-store-categories', await r.json(), !r.ok);
        }} catch (e) {{
          shShow('preview failed', String(e), true);
        }}
      }}

      async function sellerHubSync(dryRun) {{
        if (!dryRun && !confirm('LIVE write to your eBay store categories. Continue?')) return;
        try {{
          const r = await fetch(SH_LAMBDA + '/sync-store-categories', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{dry_run: dryRun}})
          }});
          shShow(dryRun ? 'DRY-RUN /sync-store-categories' : 'LIVE /sync-store-categories',
                 await r.json(), !r.ok);
        }} catch (e) {{
          shShow('sync failed', String(e), true);
        }}
      }}

      async function sellerHubPromoSync(kind, dryRun) {{
        if (!dryRun && !confirm('LIVE write to eBay. Continue?')) return;
        const path = kind === 'promoted' ? '/sync-promoted' : '/best-offer-bulk';
        try {{
          const r = await fetch(SH_LAMBDA + path, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{dry_run: dryRun}})
          }});
          shShow((dryRun ? 'DRY-RUN ' : 'LIVE ') + path, await r.json(), !r.ok);
        }} catch (e) {{
          shShow(path + ' failed', String(e), true);
        }}
      }}
    </script>
    """

    extra_css = """
<style>
  .sh-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin: 22px 0 28px; }
  .sh-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 18px 20px; position: relative; overflow: hidden; }
  .sh-kpi::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background: var(--gold); opacity:.7; }
  .sh-kpi-n { font-family: 'Bebas Neue', sans-serif; font-size: 44px; color: var(--gold); line-height: 1; }
  .sh-kpi-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 6px; }
  .sh-kpi-foot { color: var(--text-dim); font-size: 11px; margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 8px; }
  .sh-section { margin: 36px 0; }
  .sh-section-head { display: flex; align-items: baseline; gap: 14px; flex-wrap: wrap; margin-bottom: 14px; }
  .sh-section-head h2 { margin: 0; font-family: 'Bebas Neue', sans-serif; font-size: 28px; letter-spacing: .02em; }
  .sh-count { color: var(--text-muted); font-weight: 400; font-size: 18px; margin-left: 6px; }
  .sh-hint  { color: var(--text-muted); font-size: 13px; }
  .sh-hint code { background: var(--surface-2); padding: 1px 6px; border-radius: 4px; }
  .sh-tbl { width: 100%; border-collapse: collapse; font-size: 13px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; }
  .sh-tbl th, .sh-tbl td { padding: 10px 14px; text-align: left; border-bottom: 1px solid var(--border); }
  .sh-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .sh-tbl tr:last-child td { border-bottom: none; }
  .sh-tbl tr:hover td { background: var(--surface-2); }
  .sh-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .sh-mono { font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--text-dim); }
  .sh-warn { font-size: 11px; color: var(--gold); margin-left: 6px; }
  .sh-actions { display: flex; gap: 10px; align-items: center; margin: 16px 0; flex-wrap: wrap; }
  .sh-empty { color: var(--text-muted); padding: 24px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
  .sh-feat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; }
  .sh-feat { display: block; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); overflow: hidden; text-decoration: none; color: inherit; transition: transform .15s ease, border-color .15s ease; }
  .sh-feat:hover { transform: translateY(-2px); border-color: var(--gold); }
  .sh-feat-img { aspect-ratio: 1 / 1; background-size: cover; background-position: center; background-color: var(--surface-2); }
  .sh-feat-info { padding: 10px 12px; }
  .sh-feat-title { font-size: 12px; color: var(--text); line-height: 1.35; min-height: 32px; }
  .sh-feat-price { font-family: 'Bebas Neue', sans-serif; font-size: 20px; color: var(--gold); margin-top: 6px; }
  .sh-promo-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
  .sh-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 18px 20px; }
  .sh-card h4 { margin: 0 0 12px; font-size: 13px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .sh-row { display: flex; justify-content: space-between; padding: 6px 0; border-bottom: 1px dashed var(--border); font-size: 14px; }
  .sh-row:last-of-type { border-bottom: none; }
  .sh-row b { font-family: 'JetBrains Mono', monospace; color: var(--text); }
  .sh-tier-row { align-items: flex-start; }
  .sh-tier-chips { display: flex; flex-wrap: wrap; gap: 6px; justify-content: flex-end; }
  .sh-chip { background: var(--surface-2); border: 1px solid var(--border); border-radius: 999px; padding: 3px 9px; font-size: 11px; color: var(--text-muted); }
  .sh-link { display: inline-block; margin-top: 12px; color: var(--gold); font-size: 12px; text-decoration: none; }
  .sh-link:hover { text-decoration: underline; }
  .sh-phases { color: var(--text-muted); line-height: 1.7; padding-left: 22px; }
  .sh-phases li { margin: 6px 0; }
  .sh-phases code { background: var(--surface-2); padding: 1px 6px; border-radius: 4px; color: var(--text); }
  .sh-resp { margin: 14px 0; padding: 14px 16px; background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); font-family: 'JetBrains Mono', monospace; font-size: 12px; line-height: 1.5; max-height: 360px; overflow: auto; white-space: pre-wrap; word-break: break-word; }
  .sh-resp-ok { border-left: 3px solid var(--success); }
  .sh-resp-err { border-left: 3px solid var(--danger); color: var(--danger); }
  .sh-card-actions { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; }
  .btn-sm { padding: 6px 12px; font-size: 11px; }
</style>
"""

    html = promote.html_shell("Seller Hub · Harpua2001", body,
                              extra_head=extra_css,
                              active_page="seller_hub.html")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Nav registration                                                            #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    """Insert 'Seller Hub' into promote._NAV_ITEMS at runtime so the link
    appears on every page rendered through html_shell. Does not modify
    promote.py on disk — promote.py's persistent nav patch is a separate
    edit handled there.
    """
    entry = ("seller_hub.html", "Seller Hub", False, "Insights")
    if entry in promote._NAV_ITEMS:
        return
    items = list(promote._NAV_ITEMS)
    # Place right after Promoted Ads so all eBay-write surfaces sit together.
    anchor = "promoted_listings.html"
    for idx, it in enumerate(items):
        if it[0] == anchor:
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
    ap.add_argument("--report-only", action="store_true",
                    help="Re-render docs/seller_hub.html from the cached plan.")
    args = ap.parse_args()

    ensure_nav_entry()

    if args.report_only:
        plan = _load_json(PLAN_PATH)
        if plan is None:
            print("No cached plan — running full build.")
            plan = build_plan()
            save_plan(plan)
    else:
        plan = build_plan()
        save_plan(plan)
        print(f"  Plan written: {PLAN_PATH}")

    out = render_report(plan)
    print(f"  Report written: {out}")
    print(f"  Categories: {len(plan['categories'])}  · Listings: {plan['listings_total']}")
    print(f"  Featured: {len(plan['featured'])}  · PL queued: {plan['promotions']['promoted_listings']['queued']}")


if __name__ == "__main__":
    main()
