"""
vault_eligibility.py — flag listings eligible for eBay Vault.

eBay Vault is a free authenticated-storage program for trading cards
priced $250+ (vault-to-vault transfer, no condition risk). Vaulted
listings see ~12% conversion lift. As of 2026 there's no public Sell
API endpoint to flip Vault on a listing — it's a Seller Hub UI toggle.
So this agent is READ-ONLY: it builds the eligible-item shortlist and a
copy-paste ID block the seller can work from.

Eligibility (cards only — lots can't be vaulted):
  - $250+ singles  → "route_to_vault"
  - $100–$249 singles → "consider_vault" (graded/high-margin still lift)
  - lots or under $100 → "too_low" (skipped)

Run: python3 vault_eligibility.py
Out: output/vault_plan.json, docs/vault.html
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import promote

REPO_ROOT   = Path(__file__).parent
OUTPUT_DIR  = REPO_ROOT / "output"
DOCS_DIR    = REPO_ROOT / "docs"
PLAN_PATH   = OUTPUT_DIR / "vault_plan.json"
REPORT_PATH = DOCS_DIR / "vault.html"

VAULT_PRICE_FLOOR    = 250.0   # eBay's hard minimum for Vault eligibility
CONSIDER_PRICE_FLOOR = 100.0   # below $250 but still worth a manual look
CONVERSION_LIFT      = 0.12    # ~12% lift observed on vaulted listings
SINGLES_CATEGORIES   = {
    "Football Singles", "Basketball Singles", "Baseball Singles", "Pokemon",
}


def _load_json(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _load_snapshot() -> list[dict]:
    snap = _load_json(OUTPUT_DIR / "listings_snapshot.json") or []
    return snap if isinstance(snap, list) else []


def _price(l: dict) -> float:
    try:
        return float(l.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def find_vault_eligible(listings: list[dict]) -> list[dict]:
    """Score every listing against Vault rules. Returns the full
    decorated list (route / consider / too_low). Caller can filter.
    """
    out: list[dict] = []
    for l in listings:
        cat = promote._categorize(l)
        p   = _price(l)
        if cat not in SINGLES_CATEGORIES:
            action = "too_low"          # lots, "Other", etc. — not vaultable
        elif p >= VAULT_PRICE_FLOOR:
            action = "route_to_vault"
        elif p >= CONSIDER_PRICE_FLOOR:
            action = "consider_vault"
        else:
            action = "too_low"
        out.append({
            "item_id":            l.get("item_id"),
            "title":              l.get("title"),
            "price":              p,
            "category":           cat,
            "pic":                l.get("pic"),
            "url":                l.get("url"),
            "recommended_action": action,
        })
    # sort: route first, then consider, then by price desc
    rank = {"route_to_vault": 0, "consider_vault": 1, "too_low": 2}
    out.sort(key=lambda x: (rank[x["recommended_action"]], -x["price"]))
    return out


def _summarize(eligible: list[dict]) -> dict:
    route    = [e for e in eligible if e["recommended_action"] == "route_to_vault"]
    consider = [e for e in eligible if e["recommended_action"] == "consider_vault"]
    too_low  = [e for e in eligible if e["recommended_action"] == "too_low"]
    lift_30d = sum(e["price"] * CONVERSION_LIFT for e in route)
    return {
        "route_to_vault":     len(route),
        "consider":           len(consider),
        "too_low":            len(too_low),
        "estimated_lift_30d": round(lift_30d, 2),
    }


def build_plan() -> dict:
    listings = _load_snapshot()
    eligible = find_vault_eligible(listings)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary":      _summarize(eligible),
        "listings":     eligible,
    }


def save_plan(plan: dict) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return PLAN_PATH


def _fmt_money(n) -> str:
    try:
        return f"${float(n):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _row_for(e: dict) -> str:
    pic   = e.get("pic") or ""
    url   = e.get("url") or "#"
    title = (e.get("title") or "")[:80]
    action = e["recommended_action"]
    badge_cls = {
        "route_to_vault": "vt-badge vt-badge-go",
        "consider_vault": "vt-badge vt-badge-mid",
        "too_low":        "vt-badge vt-badge-low",
    }[action]
    return f"""
      <tr>
        <td><div class="vt-thumb" style="background-image:url('{pic}');"></div></td>
        <td><a href="{url}" target="_blank" rel="noopener">{title}</a>
            <div class="vt-cat">{e['category']}</div></td>
        <td class="num">${e['price']:.2f}</td>
        <td><span class="{badge_cls}">{action.replace('_', ' ')}</span></td>
        <td class="vt-mono">{e['item_id']}</td>
        <td><button class="btn btn-outline" disabled
            title="Enable in Seller Hub → Vault tab; API write not yet available">
            Route to Vault</button></td>
      </tr>"""


def build_report(eligible: list[dict]) -> Path:
    summary = _summarize(eligible)
    route   = [e for e in eligible if e["recommended_action"] == "route_to_vault"]
    consider = [e for e in eligible if e["recommended_action"] == "consider_vault"]

    kpis_html = f"""
    <div class="vt-kpis">
      <div class="vt-kpi">
        <div class="vt-kpi-n">{summary['route_to_vault']}</div>
        <div class="vt-kpi-l">Ready to Vault ($250+)</div>
        <div class="vt-kpi-foot">Singles only — lots can't be vaulted</div>
      </div>
      <div class="vt-kpi">
        <div class="vt-kpi-n">{summary['consider']}</div>
        <div class="vt-kpi-l">Worth a manual look ($100–$249)</div>
        <div class="vt-kpi-foot">Graded / high-margin items still benefit</div>
      </div>
      <div class="vt-kpi">
        <div class="vt-kpi-n">{_fmt_money(summary['estimated_lift_30d'])}</div>
        <div class="vt-kpi-l">Estimated 30d lift</div>
        <div class="vt-kpi-foot">~12% conversion uplift on vaulted listings</div>
      </div>
      <div class="vt-kpi">
        <div class="vt-kpi-n">{summary['too_low']}</div>
        <div class="vt-kpi-l">Skipped</div>
        <div class="vt-kpi-foot">Lots or under $100</div>
      </div>
    </div>"""

    visible = route + consider
    if not visible:
        table_html = '<div class="vt-empty">No vault-eligible listings in this snapshot. Re-run after pricing data updates.</div>'
    else:
        rows = "".join(_row_for(e) for e in visible)
        table_html = f"""
        <table class="vt-tbl">
          <thead><tr>
            <th></th><th>Listing</th><th class="num">Price</th>
            <th>Action</th><th>Item ID</th><th></th>
          </tr></thead>
          <tbody>{rows}</tbody>
        </table>"""

    paste_block = "\n".join(e["item_id"] for e in route) or "(none)"

    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">eBay Vault · eligibility audit</div>
        <h1 class="section-title">Vault <span class="accent">Eligibility</span></h1>
        <div class="section-sub">
          eBay Vault is a free authenticated-storage program for trading cards $250+.
          Buyers love it — no condition risk, vault-to-vault transfer — and listings
          that opt in see roughly a 12% conversion lift. There's no public write API
          for this yet, so flip each item on in
          <b>Seller Hub → Listings → Vault</b>; the IDs you need are in the copy-paste
          block at the bottom.
        </div>
      </div>
    </div>

    {kpis_html}

    <section class="vt-section">
      <div class="vt-section-head">
        <h2>Eligible listings <span class="vt-count">{len(visible)}</span></h2>
        <span class="vt-hint">Sorted by Vault readiness, then price.
        The "Route to Vault" button is disabled — flip it in Seller Hub UI for now.</span>
      </div>
      {table_html}
    </section>

    <section class="vt-section">
      <div class="vt-section-head">
        <h2>Copy-paste IDs <span class="vt-count">{len(route)}</span></h2>
        <span class="vt-hint">Paste into Seller Hub's bulk-edit ID box to filter
        the listing grid down to just these items, then toggle Vault on each.</span>
      </div>
      <textarea class="vt-paste" readonly onclick="this.select()">{paste_block}</textarea>
    </section>
    """

    extra_css = """
<style>
  .vt-kpis { display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:14px; margin:22px 0 28px; }
  .vt-kpi { background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md); padding:18px 20px; position:relative; overflow:hidden; }
  .vt-kpi::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background:var(--gold); opacity:.7; }
  .vt-kpi-n { font-family:'Bebas Neue',sans-serif; font-size:44px; color:var(--gold); line-height:1; }
  .vt-kpi-l { color:var(--text-muted); font-size:12px; text-transform:uppercase; letter-spacing:.08em; margin-top:6px; }
  .vt-kpi-foot { color:var(--text-dim); font-size:11px; margin-top:8px; border-top:1px dashed var(--border); padding-top:8px; }
  .vt-section { margin:36px 0; }
  .vt-section-head { display:flex; align-items:baseline; gap:14px; flex-wrap:wrap; margin-bottom:14px; }
  .vt-section-head h2 { margin:0; font-family:'Bebas Neue',sans-serif; font-size:28px; letter-spacing:.02em; }
  .vt-count { color:var(--text-muted); font-weight:400; font-size:18px; margin-left:6px; }
  .vt-hint  { color:var(--text-muted); font-size:13px; }
  .vt-tbl { width:100%; border-collapse:collapse; font-size:13px; background:var(--surface); border:1px solid var(--border); border-radius:var(--r-md); overflow:hidden; }
  .vt-tbl th, .vt-tbl td { padding:10px 14px; text-align:left; border-bottom:1px solid var(--border); vertical-align:middle; }
  .vt-tbl th { background:var(--surface-2); color:var(--text-muted); font-size:11px; text-transform:uppercase; letter-spacing:.08em; }
  .vt-tbl tr:last-child td { border-bottom:none; }
  .vt-tbl tr:hover td { background:var(--surface-2); }
  .vt-tbl .num { text-align:right; font-variant-numeric:tabular-nums; font-family:'JetBrains Mono',monospace; }
  .vt-thumb { width:56px; height:56px; background-size:cover; background-position:center; background-color:var(--surface-2); border-radius:6px; border:1px solid var(--border); }
  .vt-cat   { color:var(--text-dim); font-size:11px; margin-top:2px; }
  .vt-mono  { font-family:'JetBrains Mono',monospace; font-size:11px; color:var(--text-dim); }
  .vt-badge { display:inline-block; padding:3px 9px; border-radius:999px; font-size:10px; text-transform:uppercase; letter-spacing:.08em; border:1px solid var(--border); }
  .vt-badge-go  { color:#0a0a0a; background:var(--gold); border-color:var(--gold); }
  .vt-badge-mid { color:var(--gold); background:var(--surface-2); }
  .vt-badge-low { color:var(--text-dim); background:var(--surface-2); }
  .vt-empty { color:var(--text-muted); padding:24px; text-align:center; background:var(--surface); border:1px dashed var(--border); border-radius:var(--r-md); }
  .vt-paste { width:100%; min-height:140px; background:var(--surface); color:var(--text); border:1px solid var(--border); border-radius:var(--r-md); padding:12px 14px; font-family:'JetBrains Mono',monospace; font-size:12px; resize:vertical; }
</style>
"""

    html = promote.html_shell("Vault Eligibility · Harpua2001", body,
                              extra_head=extra_css,
                              active_page="vault.html")
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip())
    ap.add_argument("--report-only", action="store_true",
                    help="Re-render docs/vault.html from the cached plan.")
    args = ap.parse_args()

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

    out = build_report(plan["listings"])
    s = plan["summary"]
    print(f"  Report written: {out}")
    print(f"  Route: {s['route_to_vault']}  · Consider: {s['consider']}  "
          f"· Skipped: {s['too_low']}  · 30d lift est: ${s['estimated_lift_30d']:,.2f}")


if __name__ == "__main__":
    main()
