"""
watchers_offer_agent.py — nightly Send-Offer-to-Watchers automation.

Anyone who hit "Watch" on a listing is already half-sold. eBay's Send Offer to
Watchers feature has a 10-25% conversion rate. Most sellers never use it. This
agent finds every active listing with ≥1 watcher and queues a guardrailed
discount offer (default 12%, capped at 18%, never below floor).

Floor price per listing:
    max(absolute_floor, current_price * min_floor_multiplier,
        sold_history_median * 0.92)

Algorithm:
    1. Load active listings + sold history (cached snapshot or fresh fetch).
    2. For each listing, pull watcher_count from Sell Analytics
       traffic_report (dimension=LISTING).
    3. For listings with watchers >= min_watchers_to_offer:
         - Skip if listing got an offer in the last `cooldown_days`.
         - Compute offer price = current * (1 - discount_pct).
         - Skip if offer price < floor.
         - Expected uplift = (current - offer) * watchers * take_rate (0.15).
    4. Apply via REST sell/negotiation/v1/send_offer_to_interested_buyers.

Usage:
    python watchers_offer_agent.py                  # dry run (default)
    python watchers_offer_agent.py --apply          # actually send offers
    python watchers_offer_agent.py --no-fetch       # reuse cached snapshot
    python watchers_offer_agent.py --report-only    # rebuild docs/watchers.html

Artifacts:
    output/watcher_offers_plan.json      latest plan
    output/watcher_offers_history.json   append-only log (drives cooldown)
    docs/watchers.html                   admin-only HTML report
    watcher_offers_config.json           tunable config (created on first run)
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import xml.etree.ElementTree as ET

import promote

REPO_ROOT     = Path(__file__).parent
CONFIG_PATH   = REPO_ROOT / "watcher_offers_config.json"
HISTORY_PATH  = REPO_ROOT / "output" / "watcher_offers_history.json"
PLAN_PATH     = REPO_ROOT / "output" / "watcher_offers_plan.json"
SNAPSHOT_PATH = REPO_ROOT / "output" / "listings_snapshot.json"
REPORT_PATH   = promote.OUTPUT_DIR / "watchers.html"
SOLD_PATH     = REPO_ROOT / "sold_history.json"

DEFAULT_CONFIG: dict = {
    "enabled":                True,
    "discount_pct":           0.12,
    "max_discount_pct":       0.18,
    "min_floor_multiplier":   0.85,
    "absolute_floor":         1.00,
    "sold_floor_multiplier":  0.92,
    "min_watchers_to_offer":  1,
    "cooldown_days":          7,
    "max_offers_per_run":     50,
    "offer_duration_days":    2,
    "allow_counter_offer":    True,
    "take_rate_baseline":     0.15,
    "message":                "Saw you were watching — here's {pct}% off if you grab it today. Free combined shipping on 2+ cards.",
}


# --------------------------------------------------------------------------- #
# Config + history I/O                                                        #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_PATH.read_text())
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text())
    except json.JSONDecodeError:
        return []


def append_history(entries: list[dict]) -> None:
    if not entries:
        return
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    history = load_history()
    history.extend(entries)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


def _recent_offer_ids(history: list[dict], cooldown_days: int) -> set[str]:
    """Return item_ids that received an offer within cooldown window."""
    if not history:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    recent: set[str] = set()
    for h in history:
        ts = h.get("offered_at") or ""
        try:
            t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if t >= cutoff and h.get("item_id"):
            recent.add(str(h["item_id"]))
    return recent


# --------------------------------------------------------------------------- #
# OAuth — needs sell.marketing scope for the negotiation endpoint             #
# --------------------------------------------------------------------------- #

def get_marketing_token(cfg: dict) -> str:
    """
    Refresh-token grant including sell.marketing scope (required for the
    sell/negotiation endpoint). Falls back to promote.get_access_token if
    the marketing scope isn't authorized on the refresh token.
    """
    import base64
    credentials = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    scopes = " ".join([
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/sell.marketing",
        "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
        "https://api.ebay.com/oauth/api_scope/sell.negotiation",
    ])
    resp = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {credentials}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "scope":         scopes,
        },
        timeout=30,
    )
    if resp.status_code != 200:
        print(f"  WARN: marketing-scope token request returned {resp.status_code}; "
              f"falling back to standard token. Body: {resp.text[:160]}")
        return promote.get_access_token(cfg)
    return resp.json()["access_token"]


# --------------------------------------------------------------------------- #
# Watcher counts via Trading API GetMyeBaySelling (WatchCount per ItemArray)  #
# --------------------------------------------------------------------------- #
#
# The modern REST Sell Analytics traffic_report does NOT expose a per-listing
# watcher count metric (only impressions / CTR / sales conversion). The
# documented, supported source for live watcher counts is the legacy Trading
# API: GetMyeBaySelling returns SellingStatus/QuantityWatched for each
# ActiveList item. We use the user's existing eBay-auth-token (Trading API),
# not the REST OAuth bearer.
# --------------------------------------------------------------------------- #

TRADING_API_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS = "urn:ebay:apis:eBLBaseComponents"


def fetch_watcher_counts(ebay_cfg: dict, user_token: str | None = None) -> dict[str, int]:
    """
    Walk ActiveList pages of GetMyeBaySelling and return {item_id: watch_count}.
    The Trading API accepts the OAuth user-context bearer token as
    eBayAuthToken (same approach promote.fetch_listings uses).
    Returns {} if the call fails — caller treats unknown as 0 watchers.
    """
    if not user_token:
        user_token = (
            ebay_cfg.get("user_token")
            or ebay_cfg.get("auth_token")
            or promote.get_access_token(ebay_cfg)
        )
    if not user_token:
        print("  WARN: no usable token for Trading API; watcher counts unavailable")
        return {}

    counts: dict[str, int] = {}
    page = 1
    while True:
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{user_token}</eBayAuthToken></RequesterCredentials>
  <ActiveList>
    <Include>true</Include>
    <Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>
  </ActiveList>
  <DetailLevel>ReturnAll</DetailLevel>
  <ErrorLanguage>en_US</ErrorLanguage>
</GetMyeBaySellingRequest>"""
        headers = {
            "X-EBAY-API-SITEID":              "0",
            "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
            "X-EBAY-API-CALL-NAME":           "GetMyeBaySelling",
            "X-EBAY-API-APP-NAME":            ebay_cfg.get("client_id", ""),
            "X-EBAY-API-DEV-NAME":            ebay_cfg.get("dev_id", ""),
            "X-EBAY-API-CERT-NAME":           ebay_cfg.get("client_secret", ""),
            "Content-Type":                   "text/xml",
        }
        try:
            r = requests.post(TRADING_API_URL, headers=headers,
                              data=xml_body.encode(), timeout=30)
        except Exception as exc:
            print(f"  WARN: GetMyeBaySelling page {page} failed: {exc}")
            return counts
        if r.status_code != 200:
            print(f"  WARN: GetMyeBaySelling HTTP {r.status_code} on page {page}")
            return counts
        root = ET.fromstring(r.text)
        ns = {"e": EBAY_NS}
        ack = root.findtext("e:Ack", "", ns)
        if ack not in ("Success", "Warning"):
            err = root.find(".//e:Errors", ns)
            if err is not None:
                code = err.findtext("e:ErrorCode", "", ns)
                msg = err.findtext("e:ShortMessage", "", ns)
                print(f"  WARN: GetMyeBaySelling error [{code}] {msg}")
            return counts

        for it in root.findall(".//e:ActiveList/e:ItemArray/e:Item", ns):
            iid = (it.findtext("e:ItemID", "", ns) or "").strip()
            wc = (it.findtext("e:WatchCount", "", ns)
                  or it.findtext("e:SellingStatus/e:QuantityWatched", "", ns)
                  or "0")
            try:
                counts[iid] = int(wc)
            except (TypeError, ValueError):
                counts[iid] = 0

        pr = root.find(".//e:ActiveList/e:PaginationResult", ns)
        total_pages = 1
        if pr is not None:
            try:
                total_pages = int(pr.findtext("e:TotalNumberOfPages", "1", ns))
            except (TypeError, ValueError):
                total_pages = 1
        if page >= total_pages:
            break
        page += 1
    return counts


# --------------------------------------------------------------------------- #
# Decision engine                                                             #
# --------------------------------------------------------------------------- #

def _sold_median_for(listings_sold: list[dict], item_id: str) -> float | None:
    prices = [
        float(s.get("sale_price") or 0)
        for s in listings_sold
        if str(s.get("item_id") or "") == str(item_id)
        and float(s.get("sale_price") or 0) > 0
    ]
    if len(prices) >= 1:
        return statistics.median(prices)
    return None


def compute_floor(listing: dict, sold: list[dict], cfg: dict) -> float:
    try:
        current = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        current = 0.0
    floor = max(cfg["absolute_floor"], current * cfg["min_floor_multiplier"])
    sold_med = _sold_median_for(sold, listing["item_id"])
    if sold_med is not None:
        floor = max(floor, sold_med * cfg["sold_floor_multiplier"])
    return round(floor, 2)


def decide(listing: dict, watchers: int, sold: list[dict], recent: set[str],
           cfg: dict) -> dict:
    item_id = str(listing.get("item_id") or "")
    title = listing.get("title", "") or ""
    try:
        current = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        current = 0.0

    pct = float(cfg["discount_pct"])
    pct = min(pct, float(cfg["max_discount_pct"]))
    offer_price = round(current * (1 - pct), 2)
    floor = compute_floor(listing, sold, cfg)
    uplift = round((current - offer_price) * watchers * cfg["take_rate_baseline"], 2)

    decision = {
        "item_id":         item_id,
        "title":           title,
        "pic":             listing.get("pic", ""),
        "url":             listing.get("url", ""),
        "current_price":   current,
        "watchers":        watchers,
        "discount_pct":    round(pct * 100, 1),
        "offer_price":     offer_price,
        "floor_price":     floor,
        "expected_uplift": uplift,
        "decision":        "skip",
        "reasons":         [],
    }

    if current <= 0:
        decision["reasons"].append("no current price on listing")
        return decision
    if watchers < cfg["min_watchers_to_offer"]:
        decision["decision"] = "skip"
        decision["reasons"].append(f"watchers={watchers} < min_watchers_to_offer={cfg['min_watchers_to_offer']}")
        return decision
    if item_id in recent:
        decision["decision"] = "blocked"
        decision["reasons"].append(f"cooldown: offered within last {cfg['cooldown_days']}d")
        return decision
    if offer_price < floor:
        decision["decision"] = "blocked"
        decision["reasons"].append(f"offer ${offer_price:.2f} below floor ${floor:.2f}")
        return decision
    if offer_price < cfg["absolute_floor"]:
        decision["decision"] = "blocked"
        decision["reasons"].append(f"offer ${offer_price:.2f} below absolute floor ${cfg['absolute_floor']:.2f}")
        return decision

    decision["decision"] = "apply"
    decision["reasons"].append(
        f"{watchers} watcher(s) · {pct*100:.0f}% off ${current:.2f} → ${offer_price:.2f} (floor ${floor:.2f})"
    )
    return decision


# --------------------------------------------------------------------------- #
# eBay write path — REST sell/negotiation send_offer_to_interested_buyers     #
# --------------------------------------------------------------------------- #

NEGOTIATION_URL = (
    "https://api.ebay.com/sell/negotiation/v1/send_offer_to_interested_buyers"
)


def send_offer(item_id: str, discount_pct_int: int, message: str,
               duration_days: int, allow_counter: bool, token: str) -> dict:
    """POST a single send_offer_to_interested_buyers request."""
    body = {
        "offeredItems": [{
            "listingId":          item_id,
            "quantity":           1,
            "discountPercentage": str(discount_pct_int),
        }],
        "allowCounterOffer":   bool(allow_counter),
        "message":             message,
        "offerDuration": {
            "unit":  "DAY",
            "value": int(duration_days),
        },
    }
    headers = {
        "Authorization":            f"Bearer {token}",
        "Content-Type":             "application/json",
        "Accept":                   "application/json",
        "X-EBAY-C-MARKETPLACE-ID":  "EBAY_US",
    }
    try:
        r = requests.post(NEGOTIATION_URL, headers=headers,
                          data=json.dumps(body), timeout=30)
    except Exception as exc:
        return {"ok": False, "http": 0, "error": str(exc), "raw": ""}
    ok = r.status_code in (200, 201, 204)
    err = None
    if not ok:
        try:
            j = r.json()
            errs = j.get("errors") or []
            if errs:
                err = (errs[0].get("message") or "")[:200]
        except Exception:
            err = (r.text or "")[:200]
    return {"ok": ok, "http": r.status_code, "error": err, "raw": (r.text or "")[:400]}


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    return f"${n:,.2f}"


def _sparkline(values: list[int]) -> str:
    """Tiny inline SVG sparkline of cumulative offers over the last 30 days."""
    if not values:
        return ""
    w, h, pad = 240, 36, 2
    vmax = max(values) or 1
    n = len(values)
    pts = []
    for i, v in enumerate(values):
        x = pad + (i / max(1, n - 1)) * (w - pad * 2)
        y = h - pad - (v / vmax) * (h - pad * 2)
        pts.append(f"{x:.1f},{y:.1f}")
    poly = " ".join(pts)
    return (
        f'<svg viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true" '
        f'style="display:block">'
        f'<polyline fill="none" stroke="var(--gold)" stroke-width="1.8" points="{poly}"/>'
        f'</svg>'
    )


def _cumulative_30d(history: list[dict]) -> list[int]:
    """Cumulative offer count for each of the last 30 days, ending today."""
    today = datetime.now(timezone.utc).date()
    buckets = [0] * 30
    for h in history:
        ts = h.get("offered_at") or ""
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except (TypeError, ValueError):
            continue
        delta = (today - d).days
        if 0 <= delta < 30:
            buckets[29 - delta] += 1
    # Make cumulative
    running = 0
    cum = []
    for b in buckets:
        running += b
        cum.append(running)
    return cum


def build_report(plan: dict, history: list[dict], cfg: dict) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    decisions = plan.get("decisions", []) if isinstance(plan, dict) else (plan or [])

    by_dec: dict[str, list[dict]] = {"apply": [], "skip": [], "blocked": []}
    for d in decisions:
        by_dec.setdefault(d["decision"], []).append(d)

    total_uplift = sum(d.get("expected_uplift") or 0 for d in by_dec["apply"])
    total_watchers = sum(d.get("watchers") or 0 for d in by_dec["apply"])
    spark = _sparkline(_cumulative_30d(history))
    sent_total = len(history)
    sent_30d = sum(1 for h in history if _within_days(h.get("offered_at"), 30))

    def _row(d: dict) -> str:
        thumb = (
            f'<img src="{d.get("pic","")}" alt="" loading="lazy" '
            f'style="width:54px;height:54px;object-fit:cover;border-radius:6px;border:1px solid var(--border)">'
            if d.get("pic") else ""
        )
        reasons = "<br>".join(d.get("reasons", []) or [])
        return f"""
        <tr class="row-{d['decision']}">
          <td class="thumb">{thumb}</td>
          <td class="item">
            <a href="{d.get('url','#')}" target="_blank" rel="noopener">
              <span class="title">{(d.get('title') or '')[:90]}</span>
              <span class="item-id">{d['item_id']}</span>
            </a>
          </td>
          <td class="num">{d.get('watchers', 0)}</td>
          <td class="num">{_fmt_money(d.get('current_price'))}</td>
          <td class="num target">{_fmt_money(d.get('offer_price'))}</td>
          <td class="num">{d.get('discount_pct',0):.1f}%</td>
          <td class="num">{_fmt_money(d.get('floor_price'))}</td>
          <td class="num uplift">{_fmt_money(d.get('expected_uplift'))}</td>
          <td class="reasons">{reasons}</td>
          <td class="decision decision-{d['decision']}">{d['decision'].upper()}</td>
        </tr>"""

    def _section(title: str, items: list[dict]) -> str:
        if not items:
            return f"<h3>{title} <span class='count'>(0)</span></h3><p class='empty'>None.</p>"
        rows = "\n".join(_row(d) for d in items)
        return f"""
        <h3>{title} <span class='count'>({len(items)})</span></h3>
        <div class="tbl-wrap">
          <table class="watchers-tbl">
            <thead><tr>
              <th></th><th>Listing</th><th>Watch</th><th>Now</th><th>Offer</th>
              <th>%</th><th>Floor</th><th>Exp Uplift</th><th>Reasoning</th><th>Decision</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>"""

    recent_hist = list(reversed(history))[:50]
    hist_rows = "\n".join(
        f"<tr><td>{h.get('offered_at','')[:19]}</td>"
        f"<td><a href='{h.get('url','#')}' target='_blank'>{h.get('item_id')}</a></td>"
        f"<td>{h.get('watchers',0)}</td>"
        f"<td class='num'>{_fmt_money(h.get('current_price'))}</td>"
        f"<td class='num'>{_fmt_money(h.get('offer_price'))}</td>"
        f"<td>{h.get('discount_pct',0):.1f}%</td>"
        f"<td>{'OK' if h.get('ok') else 'FAIL: ' + (h.get('error') or '')[:60]}</td></tr>"
        for h in recent_hist
    )
    history_block = (
        f"<div class='tbl-wrap'><table class='watchers-tbl'>"
        f"<thead><tr><th>Sent</th><th>Item</th><th>Watch</th><th>Was</th>"
        f"<th>Offer</th><th>%</th><th>Result</th></tr></thead>"
        f"<tbody>{hist_rows}</tbody></table></div>"
        if recent_hist else "<p class='empty'>No offers sent yet.</p>"
    )

    body = f"""
<section class="hero">
  <h1>Watcher Offers</h1>
  <p class="sub">Last run: <code>{run_ts}</code> · Anyone who hits Watch is 80% sold — we close the other 20%.</p>
  <div class="stat-grid">
    <div class="stat"><div class="stat-n">{len(by_dec['apply'])}</div><div class="stat-l">offers queued</div></div>
    <div class="stat"><div class="stat-n">{total_watchers}</div><div class="stat-l">total watchers</div></div>
    <div class="stat"><div class="stat-n">{_fmt_money(total_uplift)}</div><div class="stat-l">expected uplift</div></div>
    <div class="stat"><div class="stat-n">{len(by_dec['blocked'])}</div><div class="stat-l">blocked</div></div>
  </div>
</section>

<section class="cfg">
  <h3>Active config</h3>
  <ul class="cfg-list">
    <li>Discount: {cfg['discount_pct']*100:.1f}% (max {cfg['max_discount_pct']*100:.1f}%)</li>
    <li>Floor multiplier: {cfg['min_floor_multiplier']*100:.0f}% of price · sold floor ×{cfg['sold_floor_multiplier']:.2f}</li>
    <li>Min watchers: {cfg['min_watchers_to_offer']} · Cooldown: {cfg['cooldown_days']}d</li>
    <li>Offer duration: {cfg['offer_duration_days']}d · Max per run: {cfg['max_offers_per_run']}</li>
    <li>Take-rate baseline: {cfg['take_rate_baseline']*100:.0f}%</li>
  </ul>
  <p class="hint">Edit <code>watcher_offers_config.json</code> at repo root. Run: <code>python watchers_offer_agent.py</code> (dry) or <code>--apply</code>.</p>
</section>

<section class="spark-card">
  <div class="spark-meta">
    <div class="spark-n">{sent_total}</div>
    <div class="spark-l">offers sent all-time · <strong>{sent_30d}</strong> in last 30d</div>
  </div>
  <div class="spark-svg">{spark}</div>
</section>

{_section('🎯 Will send', by_dec['apply'])}
{_section('⊝ Skipped (no watchers)', by_dec['skip'])}
{_section('⛔ Blocked', by_dec['blocked'])}

<section>
  <h3>Recent offer history</h3>
  {history_block}
</section>
"""

    extra_css = """
<style>
  .hero { padding: 24px 0 12px; }
  .hero h1 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 56px; letter-spacing: .02em; }
  .hero .sub { color: var(--text-muted); }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 18px 0; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 16px; }
  .stat-n { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: var(--gold); line-height: 1; }
  .stat-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; }
  .cfg { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .cfg h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .cfg-list { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 6px 18px; }
  .cfg .hint { color: var(--text-muted); font-size: 13px; margin: 10px 0 0; }
  .spark-card { display: flex; align-items: center; gap: 18px; background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .spark-n { font-family: 'Bebas Neue', sans-serif; font-size: 42px; color: var(--gold); line-height: 1; }
  .spark-l { color: var(--text-muted); font-size: 13px; margin-top: 2px; }
  .spark-svg { margin-left: auto; }
  h3 .count { color: var(--text-muted); font-weight: 400; font-size: .7em; }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.watchers-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .watchers-tbl th, .watchers-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .watchers-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .watchers-tbl tr:hover td { background: var(--surface-2); }
  .watchers-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .watchers-tbl .target { color: var(--gold); font-weight: 600; }
  .watchers-tbl .uplift { color: var(--success); font-weight: 600; }
  .watchers-tbl .thumb { width: 64px; }
  .watchers-tbl .item .title { display: block; color: var(--text); }
  .watchers-tbl .item .item-id { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .watchers-tbl .item a { text-decoration: none; }
  .watchers-tbl .item a:hover .title { color: var(--gold); }
  .watchers-tbl .reasons { color: var(--text-muted); font-size: 12px; max-width: 300px; }
  .decision { font-weight: 700; font-size: 11px; letter-spacing: .1em; }
  .decision-apply { color: var(--success); }
  .decision-skip { color: var(--text-muted); }
  .decision-blocked { color: var(--danger); }
  .row-apply { background: linear-gradient(to right, rgba(127,199,122,0.05), transparent); }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
</style>
"""
    html = promote.html_shell(
        "Watcher Offers · Harpua2001", body,
        extra_head=extra_css, active_page="watchers.html",
    )
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


def _within_days(ts: str | None, days: int) -> bool:
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return t >= datetime.now(timezone.utc) - timedelta(days=days)


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def _load_snapshot() -> list[dict]:
    """The snapshot file is a flat list of listing dicts."""
    if not SNAPSHOT_PATH.exists():
        return []
    try:
        d = json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return []
    if isinstance(d, list):
        return d
    if isinstance(d, dict) and isinstance(d.get("listings"), list):
        return d["listings"]
    return []


def gather_inputs(use_cache: bool) -> tuple[dict, list[dict], list[dict]]:
    """Returns (ebay_cfg, listings, sold_history)."""
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    if use_cache:
        listings = _load_snapshot()
        if listings:
            print(f"  Using cached snapshot ({len(listings)} listings)")
            sold = promote._load_sold_history()
            return ebay_cfg, listings, sold
    # Fresh fetch
    print("  Fetching access token + active listings...")
    token = promote.get_access_token(ebay_cfg)
    listings = promote.fetch_listings(token, ebay_cfg)
    sold = promote._load_sold_history()
    return ebay_cfg, listings, sold


def plan_all(listings: list[dict], watcher_map: dict[str, int],
             sold: list[dict], cfg: dict) -> list[dict]:
    history = load_history()
    recent = _recent_offer_ids(history, cfg["cooldown_days"])
    decisions: list[dict] = []
    for l in listings:
        item_id = str(l.get("item_id") or "")
        watchers = int(watcher_map.get(item_id, 0) or 0)
        decisions.append(decide(l, watchers, sold, recent, cfg))
    # Order: apply first (highest uplift), then blocked, then skip
    decisions.sort(
        key=lambda d: (
            {"apply": 0, "blocked": 1, "skip": 2}.get(d["decision"], 3),
            -(d.get("expected_uplift") or 0),
        )
    )
    return decisions


def apply_plan(plan: list[dict], ebay_cfg: dict, cfg: dict) -> list[dict]:
    token = get_marketing_token(ebay_cfg)
    to_send = [d for d in plan if d["decision"] == "apply"]
    cap = cfg["max_offers_per_run"]
    if len(to_send) > cap:
        print(f"  Capping run at {cap} of {len(to_send)} eligible offers")
        to_send = to_send[:cap]

    sent: list[dict] = []
    for d in to_send:
        pct_int = int(round(d["discount_pct"]))
        message = cfg["message"].format(pct=pct_int)
        print(f"  → {d['item_id']}: {d['watchers']}w · ${d['current_price']:.2f} → ${d['offer_price']:.2f} ({pct_int}%)")
        res = send_offer(
            item_id=d["item_id"],
            discount_pct_int=pct_int,
            message=message,
            duration_days=cfg["offer_duration_days"],
            allow_counter=cfg["allow_counter_offer"],
            token=token,
        )
        sent.append({
            "offered_at":    datetime.now(timezone.utc).isoformat(),
            "item_id":       d["item_id"],
            "title":         d["title"],
            "url":           d.get("url"),
            "watchers":      d["watchers"],
            "current_price": d["current_price"],
            "offer_price":   d["offer_price"],
            "discount_pct":  d["discount_pct"],
            "duration_days": cfg["offer_duration_days"],
            "ok":            res["ok"],
            "http":          res["http"],
            "error":         res.get("error"),
        })
        # eBay throttles negotiation endpoint; small pacing helps.
        time.sleep(0.6)
    return sent


def summarize(plan: list[dict]) -> None:
    buckets = {"apply": 0, "skip": 0, "blocked": 0}
    uplift = 0.0
    for d in plan:
        buckets[d["decision"]] = buckets.get(d["decision"], 0) + 1
        if d["decision"] == "apply":
            uplift += d.get("expected_uplift") or 0
    print(f"\n  Plan summary: "
          f"{buckets.get('apply',0)} to send · "
          f"{buckets.get('skip',0)} no-watchers · "
          f"{buckets.get('blocked',0)} blocked · "
          f"expected uplift ${uplift:.2f}")


def main() -> int:
    ap = argparse.ArgumentParser(description="Send-Offer-to-Watchers automation for Harpua2001.")
    ap.add_argument("--apply", action="store_true", help="Actually send offers via eBay (default: dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="Reuse cached listings snapshot")
    ap.add_argument("--report-only", action="store_true", help="Rebuild docs/watchers.html from last plan + history")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("enabled", True):
        print("Watchers agent disabled in watcher_offers_config.json.")
        return 0

    if args.report_only:
        plan = json.loads(PLAN_PATH.read_text()) if PLAN_PATH.exists() else {}
        path = build_report(plan, load_history(), cfg)
        print(f"  Wrote {path}")
        return 0

    ebay_cfg, listings, sold = gather_inputs(use_cache=args.no_fetch)
    print(f"  Loaded {len(listings)} active listings · {len(sold)} sold history records")

    print("  Fetching watcher counts (Trading API GetMyeBaySelling)...")
    try:
        trading_token = promote.get_access_token(ebay_cfg)
        watcher_map = fetch_watcher_counts(ebay_cfg, user_token=trading_token)
    except Exception as exc:
        print(f"  WARN: watcher fetch failed: {exc}")
        watcher_map = {}
    nonzero = sum(1 for v in watcher_map.values() if v > 0)
    print(f"  Got watcher counts for {len(watcher_map)} listings ({nonzero} with ≥1 watcher)")

    plan = plan_all(listings, watcher_map, sold, cfg)
    PLAN_PATH.parent.mkdir(exist_ok=True)
    plan_doc = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config":       cfg,
        "decisions":    plan,
    }
    PLAN_PATH.write_text(json.dumps(plan_doc, indent=2))
    summarize(plan)

    if args.apply:
        print("\n  Sending offers to eBay...")
        sent = apply_plan(plan, ebay_cfg, cfg)
        append_history(sent)
        ok = sum(1 for s in sent if s["ok"])
        print(f"\n  Result: {ok}/{len(sent)} offers sent successfully.")
    else:
        print("\n  Dry run only. Re-run with --apply to send offers.")

    path = build_report(plan_doc, load_history(), cfg)
    print(f"  Report: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
