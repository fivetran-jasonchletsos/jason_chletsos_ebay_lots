"""Listing Performance agent.

Pulls eBay Sell Analytics traffic_report (30d) and joins it with our local
listings snapshot to prove that today's seller-side optimization work
(Item Specifics, repricing, store categories, Best Offer) is paying off
in eBay search rank / impressions.

Outputs:
  output/listing_performance_plan.json
  docs/listing_performance.html

CLI:
  python3 listing_performance_agent.py
"""

from __future__ import annotations

import base64
import datetime as _dt
import html as _html
import json
import sys
from pathlib import Path
from typing import Any

import requests

import promote


# --------------------------------------------------------------------------- #
# Paths                                                                       #
# --------------------------------------------------------------------------- #

ROOT          = Path(__file__).parent
OUTPUT_DIR    = ROOT / "output"
DOCS_DIR      = ROOT / "docs"
PLAN_PATH     = OUTPUT_DIR / "listing_performance_plan.json"
HTML_PATH     = DOCS_DIR / "listing_performance.html"
SNAPSHOT_PATH = OUTPUT_DIR / "listings_snapshot.json"

ANALYTICS_BASE = "https://api.ebay.com/sell/analytics/v1"

# Scopes required for traffic_report. The user OAuth token MUST include
# sell.analytics.readonly. If the refresh-token grant was minted without
# that scope, eBay returns 403 / "insufficient permissions to access this
# resource" and the user must re-mint via oauth_remint_helper.py.
ANALYTICS_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
]


# --------------------------------------------------------------------------- #
# OAuth                                                                       #
# --------------------------------------------------------------------------- #

def get_analytics_token(cfg: dict) -> tuple[str | None, str | None]:
    """Refresh-token exchange asking for sell.analytics.readonly.

    Returns (access_token, error). On success error is None; on failure
    access_token is None and error is a short human-readable message.
    """
    creds = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    try:
        r = requests.post(
            "https://api.ebay.com/identity/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {creds}",
                "Content-Type":  "application/x-www-form-urlencoded",
            },
            data={
                "grant_type":    "refresh_token",
                "refresh_token": cfg["refresh_token"],
                "scope":         " ".join(ANALYTICS_SCOPES),
            },
            timeout=30,
        )
    except requests.RequestException as e:
        return None, f"network error: {e}"

    if r.status_code != 200:
        snippet = r.text[:240].replace("\n", " ")
        return None, f"token error {r.status_code}: {snippet}"
    tok = r.json().get("access_token")
    if not tok:
        return None, "token error: no access_token in response"
    return tok, None


# --------------------------------------------------------------------------- #
# Sell Analytics API                                                          #
# --------------------------------------------------------------------------- #

TRAFFIC_METRICS = [
    "LISTING_IMPRESSION_TOTAL",
    "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE",
    "CLICK_THROUGH_RATE",
    "SALES_CONVERSION_RATE",
]


def fetch_traffic_report(token: str, days_back: int = 30) -> dict[str, Any]:
    """Pull /sell/analytics/v1/traffic_report for the past `days_back` days.

    Returns:
      {
        "status":      <http status int or -1>,
        "error":       <None or string>,
        "rows":        [{item_id, impressions, search_impressions,
                         ctr, conv_rate, sold_qty}, ...],
        "raw":         <full response json or None>,
      }
    """
    today  = _dt.date.today()
    start  = today - _dt.timedelta(days=days_back)
    date_range = f"{start.strftime('%Y%m%d')}..{today.strftime('%Y%m%d')}"

    # All scoping params live inside `filter=` per the analytics API spec.
    flt = f"marketplace_ids:{{EBAY_US}},date_range:[{date_range}]"
    params = {
        "dimension": "LISTING",
        "metric":    ",".join(TRAFFIC_METRICS),
        "filter":    flt,
    }
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/json",
    }
    try:
        r = requests.get(f"{ANALYTICS_BASE}/traffic_report",
                         headers=headers, params=params, timeout=60)
    except requests.RequestException as e:
        return {"status": -1, "error": f"network error: {e}",
                "rows": [], "raw": None}

    if r.status_code != 200:
        snippet = r.text[:400].replace("\n", " ")
        scope_missing = (r.status_code in (401, 403)
                         or "scope" in snippet.lower()
                         or "insufficient" in snippet.lower())
        err = f"HTTP {r.status_code}: {snippet}"
        if scope_missing:
            err += (" — token likely missing sell.analytics.readonly; "
                    "run oauth_remint_helper.py to re-mint.")
        return {"status": r.status_code, "error": err, "rows": [], "raw": None}

    try:
        payload = r.json()
    except json.JSONDecodeError:
        return {"status": r.status_code, "error": "non-JSON response",
                "rows": [], "raw": None}

    rows = _parse_traffic_rows(payload)
    return {"status": r.status_code, "error": None, "rows": rows, "raw": payload}


def _parse_traffic_rows(payload: dict) -> list[dict]:
    """Walk the eBay analytics response shape into flat dicts.

    Shape (observed on /sell/analytics/v1/traffic_report):
      payload.header.dimensionKeys[].key   -> dim name (e.g. "LISTING")
      payload.header.metrics[].key         -> metric name
      payload.records[].dimensionValues[].value
      payload.records[].metricValues[].value
    """
    out: list[dict] = []
    header  = payload.get("header") or {}
    records = payload.get("records") or []
    dim_keys    = [d.get("key") for d in (header.get("dimensionKeys") or [])]
    metric_keys = [m.get("key") for m in (header.get("metrics") or [])]

    for rec in records:
        dvals = rec.get("dimensionValues") or []
        mvals = rec.get("metricValues") or []
        item_id = ""
        for i, k in enumerate(dim_keys):
            if k == "LISTING" and i < len(dvals):
                item_id = str(dvals[i].get("value") or "").strip()
                break
        if not item_id and dvals:
            item_id = str(dvals[0].get("value") or "").strip()

        def _m(name: str) -> float:
            try:
                idx = metric_keys.index(name)
            except ValueError:
                return 0.0
            if idx >= len(mvals):
                return 0.0
            v = mvals[idx].get("value")
            if v is None:
                return 0.0
            try:
                return float(v)
            except (TypeError, ValueError):
                return 0.0

        imp        = int(_m("LISTING_IMPRESSION_TOTAL"))
        ctr_frac   = _m("CLICK_THROUGH_RATE")        # returned as fraction
        conv_frac  = _m("SALES_CONVERSION_RATE")     # returned as fraction
        ctr_pct    = ctr_frac * 100.0 if ctr_frac <= 1.5 else ctr_frac
        conv_pct   = conv_frac * 100.0 if conv_frac <= 1.5 else conv_frac
        # Sold qty isn't part of traffic_report; estimate from imp*ctr*conv.
        est_sold   = int(round(imp * (ctr_frac if ctr_frac <= 1.5 else ctr_frac/100.0)
                                   * (conv_frac if conv_frac <= 1.5 else conv_frac/100.0)))

        out.append({
            "item_id":            item_id,
            "impressions":        imp,
            "search_impressions": int(_m("LISTING_IMPRESSION_SEARCH_RESULTS_PAGE")),
            "ctr":                round(ctr_pct, 3),
            "conv_rate":          round(conv_pct, 3),
            "sold_qty":           est_sold,
        })
    return out


# --------------------------------------------------------------------------- #
# Snapshot join                                                               #
# --------------------------------------------------------------------------- #

def load_snapshot() -> list[dict]:
    if not SNAPSHOT_PATH.exists():
        return []
    try:
        return json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return []


def merge_with_snapshot(traffic: list[dict], listings: list[dict]) -> list[dict]:
    by_id = {str(l.get("item_id")): l for l in listings if l.get("item_id")}
    merged: list[dict] = []
    for row in traffic:
        iid = str(row.get("item_id") or "")
        listing = by_id.get(iid, {})
        merged.append({
            **row,
            "title":    listing.get("title") or "",
            "price":    listing.get("price") or "",
            "pic":      listing.get("pic") or "",
            "url":      listing.get("url")
                        or (f"https://www.ebay.com/itm/{iid}" if iid else ""),
            "category": listing.get("category") or "",
        })
    return merged


# --------------------------------------------------------------------------- #
# Scoring                                                                     #
# --------------------------------------------------------------------------- #

def compute_top_movers(merged: list[dict]) -> dict[str, list[dict]]:
    """Return categorized leader/laggard buckets."""
    impression_leaders = sorted(
        merged, key=lambda r: r.get("impressions", 0), reverse=True
    )[:10]

    ctr_pool = [r for r in merged if r.get("impressions", 0) >= 50]
    ctr_leaders = sorted(
        ctr_pool, key=lambda r: r.get("ctr", 0.0), reverse=True
    )[:10]

    needs_help = [r for r in merged if r.get("impressions", 0) < 10]
    # Sort by price desc so the most valuable dead listings bubble up first.
    def _price(r: dict) -> float:
        try:
            return float(r.get("price") or 0)
        except (TypeError, ValueError):
            return 0.0
    needs_help.sort(key=_price, reverse=True)

    return {
        "impression_leaders": impression_leaders,
        "ctr_leaders":        ctr_leaders,
        "needs_help":         needs_help[:25],
    }


def compute_kpis(merged: list[dict]) -> dict[str, Any]:
    total_imp   = sum(int(r.get("impressions", 0)) for r in merged)
    total_search = sum(int(r.get("search_impressions", 0)) for r in merged)
    total_sold  = sum(int(r.get("sold_qty", 0)) for r in merged)
    # Reconstruct clicks via CTR * impressions
    clicks = 0.0
    for r in merged:
        imp = int(r.get("impressions", 0))
        ctr = float(r.get("ctr", 0.0))  # stored as percentage
        clicks += imp * (ctr / 100.0)
    avg_ctr = (clicks / total_imp * 100.0) if total_imp else 0.0
    return {
        "total_impressions":         total_imp,
        "total_search_impressions":  total_search,
        "total_clicks":              int(round(clicks)),
        "avg_ctr_pct":               round(avg_ctr, 2),
        "total_sold_qty":            total_sold,
        "listing_count":             len(merged),
    }


# --------------------------------------------------------------------------- #
# HTML rendering                                                              #
# --------------------------------------------------------------------------- #

CSS = (
    "body{font-family:-apple-system,BlinkMacSystemFont,Inter,sans-serif;background:#0a0a0a;color:#eaeaea;margin:0;padding:24px;}"
    "h1{font-family:'Bebas Neue',sans-serif;font-size:42px;letter-spacing:2px;margin:0 0 4px;color:#d4af37;}"
    "h2{font-family:'Bebas Neue',sans-serif;font-size:26px;letter-spacing:1.5px;margin:32px 0 12px;color:#d4af37;border-bottom:1px solid #222;padding-bottom:6px;}"
    ".sub{color:#888;margin-bottom:24px;font-size:13px;}"
    ".kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px;}"
    ".kpi{background:#141414;border:1px solid #222;border-radius:10px;padding:14px 16px;}"
    ".kpi .label{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:#888;}"
    ".kpi .value{font-family:'Bebas Neue',sans-serif;font-size:30px;color:#fff;margin-top:4px;}"
    "table{width:100%;border-collapse:collapse;background:#101010;border:1px solid #222;border-radius:10px;overflow:hidden;}"
    "th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #1c1c1c;font-size:13px;vertical-align:middle;}"
    "th{background:#161616;color:#d4af37;font-weight:600;text-transform:uppercase;font-size:11px;letter-spacing:1px;}"
    "tr:last-child td{border-bottom:none;}"
    "img.thumb{width:46px;height:46px;object-fit:cover;border-radius:6px;background:#222;}"
    "a{color:#7ec8ff;text-decoration:none;}a:hover{text-decoration:underline;}"
    ".alert{background:#3a1a1a;border:1px solid #6a2a2a;color:#ffb4b4;padding:14px 18px;border-radius:10px;margin-bottom:24px;font-size:14px;}"
    ".alert b{color:#ffd1d1;}.hint{color:#888;font-size:12px;font-style:italic;}"
    ".empty{padding:32px;text-align:center;color:#666;font-style:italic;}"
    ".bar{display:inline-block;height:6px;background:#d4af37;border-radius:3px;vertical-align:middle;margin-right:6px;}"
    ".num{font-variant-numeric:tabular-nums;}"
)


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def _hint_for(row: dict) -> str:
    title = (row.get("title") or "").strip()
    hints: list[str] = []
    if not row.get("pic"):
        hints.append("Add a hero photo")
    if len(title) < 35:
        hints.append("Lengthen title (aim 70-80 chars w/ year, set, brand, parallel)")
    if not row.get("category"):
        hints.append("Assign store category")
    if int(row.get("search_impressions", 0)) == 0 and int(row.get("impressions", 0)) > 0:
        hints.append("Listing is found, not via search — fix Item Specifics")
    if not hints:
        hints.append("Reshoot photos / refresh Item Specifics")
    return " · ".join(hints)


def _row_html(r: dict, *, with_hint: bool = False) -> str:
    iid    = _esc(r.get("item_id"))
    title  = _esc((r.get("title") or "")[:80] or f"Item {iid}")
    pic    = _esc(r.get("pic"))
    url    = _esc(r.get("url") or f"https://www.ebay.com/itm/{iid}")
    imp    = int(r.get("impressions", 0))
    search = int(r.get("search_impressions", 0))
    ctr    = float(r.get("ctr", 0.0))
    sold   = int(r.get("sold_qty", 0))
    price  = _esc(r.get("price"))
    thumb  = (f'<img class="thumb" src="{pic}" alt="">'
              if pic else '<div class="thumb"></div>')
    bar_w  = max(2, min(120, imp // 5))
    extra  = (f'<td><span class="hint">{_esc(_hint_for(r))}</span></td>'
              if with_hint else "")
    return (
        f"<tr>"
        f"<td>{thumb}</td>"
        f"<td><a href='{url}' target='_blank' rel='noopener'>{title}</a>"
        f"<br><span class='hint'>#{iid} · ${price}</span></td>"
        f"<td class='num'><span class='bar' style='width:{bar_w}px'></span>{imp:,}</td>"
        f"<td class='num'>{search:,}</td>"
        f"<td class='num'>{ctr:.2f}%</td>"
        f"<td class='num'>{sold}</td>"
        f"{extra}"
        f"</tr>"
    )


def _table(rows: list[dict], *, with_hint: bool = False,
           empty_msg: str = "No data") -> str:
    if not rows:
        return f"<div class='empty'>{_esc(empty_msg)}</div>"
    hdr_hint = "<th>Suggested fix</th>" if with_hint else ""
    body = "\n".join(_row_html(r, with_hint=with_hint) for r in rows)
    return (
        "<table><thead><tr>"
        "<th></th><th>Listing</th><th>Impressions</th>"
        "<th>Search</th><th>CTR</th><th>Sold</th>"
        f"{hdr_hint}"
        "</tr></thead><tbody>"
        f"{body}"
        "</tbody></table>"
    )


def render_html(plan: dict) -> str:
    kpis     = plan.get("kpis") or {}
    buckets  = plan.get("buckets") or {}
    error    = plan.get("error")
    status   = plan.get("status")
    fetched  = plan.get("fetched_at") or ""
    days     = plan.get("window_days", 30)

    alert = ""
    if error:
        alert = (
            f"<div class='alert'><b>Sell Analytics unavailable.</b><br>"
            f"{_esc(error)}<br>"
            f"<span class='hint'>Run <code>oauth_remint_helper.py</code> to "
            f"re-mint your refresh token with the "
            f"<code>sell.analytics.readonly</code> scope, then re-run this agent.</span>"
            f"</div>"
        )

    kpi_strip = (
        "<div class='kpis'>"
        f"<div class='kpi'><div class='label'>Impressions (30d)</div>"
        f"<div class='value'>{kpis.get('total_impressions', 0):,}</div></div>"
        f"<div class='kpi'><div class='label'>Search Impressions</div>"
        f"<div class='value'>{kpis.get('total_search_impressions', 0):,}</div></div>"
        f"<div class='kpi'><div class='label'>Clicks (est.)</div>"
        f"<div class='value'>{kpis.get('total_clicks', 0):,}</div></div>"
        f"<div class='kpi'><div class='label'>Avg CTR</div>"
        f"<div class='value'>{kpis.get('avg_ctr_pct', 0.0):.2f}%</div></div>"
        f"<div class='kpi'><div class='label'>Sold Qty</div>"
        f"<div class='value'>{kpis.get('total_sold_qty', 0):,}</div></div>"
        f"<div class='kpi'><div class='label'>Listings Tracked</div>"
        f"<div class='value'>{kpis.get('listing_count', 0):,}</div></div>"
        "</div>"
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<title>Listing Performance · Harpua2001</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{CSS}</style>
</head><body>
<h1>Listing Performance</h1>
<div class="sub">Sell Analytics traffic_report · last {days} days · generated {_esc(fetched)} · HTTP {_esc(status)}</div>
{alert}
{kpi_strip}

<h2>Impression Leaders</h2>
<p class="hint">Which listings are eBay actually surfacing? Big numbers here mean the
seller-side work (specifics, categories, repricing) is moving these into search results.</p>
{_table(buckets.get('impression_leaders') or [],
        empty_msg='No traffic data yet — re-mint OAuth with sell.analytics.readonly.')}

<h2>CTR Leaders <span class="hint" style="font-size:12px">(min 50 impressions)</span></h2>
<p class="hint">High CTR = title + thumbnail are doing their job. Promote these via promoted listings; clone their title pattern onto laggards.</p>
{_table(buckets.get('ctr_leaders') or [],
        empty_msg='No qualifying listings yet (need at least 50 impressions).')}

<h2>Needs Help · Zero / Low Traffic</h2>
<p class="hint">Fewer than 10 impressions in 30 days. Almost always a title, category, or Item Specifics problem.</p>
{_table(buckets.get('needs_help') or [], with_hint=True,
        empty_msg='Nothing under 10 impressions — your specifics work paid off.')}

</body></html>
"""


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def build_plan() -> dict:
    cfg = json.loads(promote.CONFIG_FILE.read_text())
    listings = load_snapshot()

    token, tok_err = get_analytics_token(cfg)
    if not token:
        plan = {
            "fetched_at":   _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "window_days":  30,
            "status":       "AUTH_FAILED",
            "error":        (tok_err or "no token")
                            + " — token missing sell.analytics.readonly scope; "
                              "run oauth_remint_helper.py to re-mint.",
            "kpis":         compute_kpis([]),
            "buckets":      {"impression_leaders": [],
                             "ctr_leaders": [],
                             "needs_help": []},
            "row_count":    0,
        }
        return plan

    report = fetch_traffic_report(token, days_back=30)
    merged = merge_with_snapshot(report["rows"], listings)
    buckets = compute_top_movers(merged)
    plan = {
        "fetched_at":  _dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "window_days": 30,
        "status":      report["status"],
        "error":       report["error"],
        "kpis":        compute_kpis(merged),
        "buckets":     buckets,
        "row_count":   len(merged),
    }
    return plan


def main() -> int:
    OUTPUT_DIR.mkdir(exist_ok=True)
    DOCS_DIR.mkdir(exist_ok=True)

    plan = build_plan()

    PLAN_PATH.write_text(json.dumps(plan, indent=2))
    HTML_PATH.write_text(render_html(plan))

    kpis = plan.get("kpis", {})
    print(f"  Plan written -> {PLAN_PATH}")
    print(f"  HTML written -> {HTML_PATH}")
    print(f"  Status: {plan.get('status')}")
    if plan.get("error"):
        print(f"  Error:  {plan['error'][:200]}")
    print(f"  Impressions: {kpis.get('total_impressions', 0):,} | "
          f"Clicks: {kpis.get('total_clicks', 0):,} | "
          f"Sold: {kpis.get('total_sold_qty', 0):,} | "
          f"Listings: {kpis.get('listing_count', 0):,}")

    top = (plan.get("buckets") or {}).get("impression_leaders") or []
    if top:
        print("  Top impression leaders:")
        for r in top[:5]:
            print(f"    {r.get('item_id')}  imp={r.get('impressions'):,}  "
                  f"ctr={r.get('ctr'):.2f}%  sold={r.get('sold_qty')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
