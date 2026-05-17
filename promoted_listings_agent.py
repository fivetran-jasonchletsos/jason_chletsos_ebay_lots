"""
promoted_listings_agent.py — variable Promoted Listings ad rates per listing.

Most amateur sellers leave the eBay default 12% ad rate on every listing. That
crushes margin on items that were going to sell anyway and underspends on slow
movers that need visibility. This agent classifies each active listing into one
of five ad-rate tiers (NO_AD / LOW / STANDARD / AGGRESSIVE / MAX) and pushes
per-item bid percentages via the eBay Marketing API.

Usage:
    python promoted_listings_agent.py                 # dry run — no eBay writes
    python promoted_listings_agent.py --apply         # push bid % via Marketing API
    python promoted_listings_agent.py --apply --create-campaign  # also bootstrap a campaign if none exists
    python promoted_listings_agent.py --report-only   # rebuild docs/promoted_listings.html

Artifacts:
    output/promoted_listings_plan.json     latest plan with reasoning per listing
    promoted_listings_history.json         append-only log of bid changes
    docs/promoted_listings.html            human-readable tier breakdown report
    promoted_listings_config.json          tunable tier definitions + caps
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from statistics import median

import requests

import promote

REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "promoted_listings_config.json"
HISTORY_PATH       = REPO_ROOT / "promoted_listings_history.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
MARKET_HISTORY     = REPO_ROOT / "market_history.json"
PLAN_PATH          = REPO_ROOT / "output" / "promoted_listings_plan.json"
REPORT_PATH        = promote.OUTPUT_DIR / "promoted_listings.html"

EBAY_TOKEN_URL     = "https://api.ebay.com/identity/v1/oauth2/token"
EBAY_MARKETING_BASE = "https://api.ebay.com/sell/marketing/v1"

# eBay quotes a 4-12% sales lift from Promoted Listings on its help docs;
# we use a midpoint scaled by bid intensity for our incremental revenue estimate.
EBAY_LIFT_MIN = 0.04
EBAY_LIFT_MAX = 0.12

DEFAULT_CONFIG: dict = {
    "enabled":   True,
    "tiers": {
        "no_ad":      {"rate": 0.0,  "label": "NO_AD",
                       "criteria": "sold_in_7d_count >= 1 OR (watchers >= 3 AND age_days < 30)"},
        "low":        {"rate": 0.03, "label": "LOW",
                       "criteria": "age_days <= 30 AND watchers == 0"},
        "standard":   {"rate": 0.08, "label": "STANDARD",
                       "criteria": "age_days <= 60"},
        "aggressive": {"rate": 0.15, "label": "AGGRESSIVE",
                       "criteria": "age_days > 60 AND age_days <= 120 AND watchers == 0"},
        "max":        {"rate": 0.20, "label": "MAX",
                       "criteria": "age_days > 120"},
    },
    # Don't promote a listing whose margin would dip below this fraction of list
    # price after fees + the ad bid would eat the rest. Lowered 2026-05-17 from
    # 0.15 to 0.0 to match eBay's "promote 62% of your listings" recommendation
    # for harpua2001 Trading Card Lots. Negative-margin items still skip ads.
    "min_margin_pct_to_promote": 0.0,
    # eBay leaf categoryIds to entirely skip. (e.g. high-fee categories.)
    "skip_categories":           [],
    # Hard cap on projected 30-day ad spend across the catalog. Tier rates are
    # capped down to keep the projection under this number; over-budget items
    # are reported.
    "max_total_30d_ad_spend_usd": 200,
    # Assumed monthly sell-through used to project ad spend when sold-history
    # data is thin. 0.25 = 25% of listings move in 30d (rough catalog average).
    "default_30d_sellthrough":   0.25,
    # If we have no age signal at all, fall back to this tier key.
    "unknown_age_default_tier":  "standard",
    # Auto-create one campaign on --apply if none exists.
    "default_campaign": {
        "name":          "Harpua2001 Auto-Optimized",
        "funding_model": "COST_PER_SALE",
        "daily_budget":  10.00,
        "marketplace":   "EBAY_US",
        "duration_days": 30,
    },
}


# --------------------------------------------------------------------------- #
# Config + history I/O                                                        #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(CONFIG_PATH.read_text())
    # Shallow-merge top level + tier defaults so older configs pick up new keys.
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    for tk, tv in DEFAULT_CONFIG["tiers"].items():
        cfg["tiers"].setdefault(tk, tv)
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
    hist = load_history()
    hist.extend(entries)
    HISTORY_PATH.write_text(json.dumps(hist, indent=2))


# --------------------------------------------------------------------------- #
# Inputs                                                                      #
# --------------------------------------------------------------------------- #

def _load_listings() -> list[dict]:
    """The site exports either a flat list of listings or a wrapper dict."""
    if not LISTINGS_SNAPSHOT.exists():
        return []
    raw = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict) and "listings" in raw:
        return raw["listings"]
    return []


def _load_market_segments() -> dict:
    """Latest market segment medians from market_history.json."""
    if not MARKET_HISTORY.exists():
        return {}
    try:
        hist = json.loads(MARKET_HISTORY.read_text())
    except Exception:
        return {}
    if not hist:
        return {}
    last = hist[-1] if isinstance(hist, list) else hist
    return last.get("segments", {}) if isinstance(last, dict) else {}


def _sold_index_by_item_id(sold: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for s in sold:
        item_id = s.get("item_id")
        if item_id:
            out.setdefault(str(item_id), []).append(s)
    return out


def _parse_sold_date(s: dict) -> datetime | None:
    raw = s.get("sold_date") or s.get("saledate")
    if not raw:
        return None
    try:
        # Trailing 'Z' -> UTC ISO
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Per-listing signals                                                         #
# --------------------------------------------------------------------------- #

def _listing_age_days(listing: dict, snapshot_mtime: datetime) -> int | None:
    """
    Best-effort listing age. The snapshot doesn't carry a StartTime field
    today, so we accept any of {start_time, listed_at, created_at, age_days}
    if a future fetch adds them. Otherwise return None (treated as 'unknown').
    """
    for key in ("age_days", "listing_age_days"):
        if listing.get(key) is not None:
            try:
                return int(listing[key])
            except (TypeError, ValueError):
                pass
    for key in ("start_time", "listed_at", "created_at", "StartTime"):
        raw = listing.get(key)
        if not raw:
            continue
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except Exception:
            continue
        return max(0, (snapshot_mtime - dt).days)
    return None


def _watcher_count(listing: dict) -> int:
    for key in ("watchers", "watch_count", "WatchCount"):
        if listing.get(key) is not None:
            try:
                return int(listing[key])
            except (TypeError, ValueError):
                pass
    return 0


def _sold_in_window(item_id: str, sold_idx: dict[str, list[dict]],
                    days: int, now: datetime) -> int:
    rows = sold_idx.get(str(item_id), [])
    if not rows:
        return 0
    cutoff = now.timestamp() - days * 86400
    n = 0
    for s in rows:
        d = _parse_sold_date(s)
        if d and d.timestamp() >= cutoff:
            n += 1
    return n


def _avg_days_to_sell(sold_idx: dict[str, list[dict]]) -> float | None:
    """
    Aggregate signal across the catalog — typical days between list and sell.
    We use the median of (now - sold_date) for items with both dates.
    """
    now = datetime.now(timezone.utc)
    deltas = []
    for rows in sold_idx.values():
        for s in rows:
            d = _parse_sold_date(s)
            if d:
                deltas.append((now - d).days)
    if not deltas:
        return None
    return float(median(deltas))


# --------------------------------------------------------------------------- #
# Tier decision                                                               #
# --------------------------------------------------------------------------- #

TIER_ORDER = ["no_ad", "low", "standard", "aggressive", "max"]


def classify(listing: dict, *, age_days: int | None, watchers: int,
             sold_7d: int, market_median: float | None,
             cfg: dict) -> tuple[str, list[str]]:
    """
    Returns (tier_key, reasons[]). See README in this file for the full ladder.
    """
    reasons: list[str] = []

    # NO_AD — proven mover.
    if sold_7d >= 1:
        reasons.append(f"sold {sold_7d}x in last 7d — no ad spend needed")
        return "no_ad", reasons
    if watchers >= 3 and age_days is not None and age_days < 30:
        reasons.append(f"{watchers} watchers + age {age_days}d < 30 — moves itself")
        return "no_ad", reasons

    # Unknown age — punt to configured fallback.
    if age_days is None:
        fallback = cfg.get("unknown_age_default_tier", "standard")
        reasons.append(f"no age signal available — defaulting to {fallback}")
        return fallback, reasons

    # LOW — fresh, no traction yet but not stale either.
    if age_days <= 30 and watchers == 0:
        reasons.append(f"fresh listing ({age_days}d) with no watchers — light push")
        return "low", reasons

    # STANDARD — moving but unremarkable.
    if age_days <= 60:
        reasons.append(f"{age_days}d old — default push")
        return "standard", reasons

    # AGGRESSIVE — stale, no watcher heat, market may be soft.
    if age_days <= 120 and watchers == 0:
        if market_median is not None:
            try:
                price = float(listing.get("price") or 0)
                if price > market_median:
                    reasons.append(
                        f"{age_days}d old · listed ${price:.2f} above segment median ${market_median:.2f} — needs visibility"
                    )
                else:
                    reasons.append(f"{age_days}d old · zero watchers — needs visibility")
            except (TypeError, ValueError):
                reasons.append(f"{age_days}d old · zero watchers")
        else:
            reasons.append(f"{age_days}d old · zero watchers — needs visibility")
        return "aggressive", reasons

    # MAX — last-resort push before considering pulling the listing.
    if age_days > 120:
        reasons.append(f"{age_days}d old — last-resort push, consider delisting")
        return "max", reasons

    # Fallthrough — shouldn't happen with the above coverage.
    reasons.append("no tier matched — defaulting to standard")
    return "standard", reasons


def _est_margin_pct(listing: dict) -> float | None:
    """
    We don't carry a cost-basis on each listing, so use the eBay net-after-fees
    ratio (net / list price) as a proxy. If that's below the threshold the
    listing is already too thin to give 10%+ to ads.
    """
    try:
        price = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        return None
    if price <= 0:
        return None
    ship_cost = (
        promote.DEFAULT_SHIP_COST_HIGH
        if "lot" in (listing.get("title") or "").lower()
        else promote.DEFAULT_SHIP_COST_LOW
    )
    try:
        net = promote._ebay_net(price, ship_cost).get("net", 0.0)
    except Exception:
        return None
    # Return raw margin (may be negative). The caller uses the sign + threshold
    # to decide; zero-clamping here was hiding the real signal.
    return net / price


def build_decision(listing: dict, sold_idx: dict[str, list[dict]],
                   market_segments: dict, snapshot_mtime: datetime,
                   cfg: dict) -> dict:
    item_id  = str(listing.get("item_id") or "")
    title    = listing.get("title") or ""
    try:
        price = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        price = 0.0
    age      = _listing_age_days(listing, snapshot_mtime)
    watchers = _watcher_count(listing)
    sold_7d  = _sold_in_window(item_id, sold_idx, 7,  datetime.now(timezone.utc))
    sold_30d = _sold_in_window(item_id, sold_idx, 30, datetime.now(timezone.utc))

    # Pick a market median from whichever segment we can match crudely on title.
    market_median = _segment_median_for_title(title, market_segments)

    decision = {
        "item_id":      item_id,
        "title":        title,
        "price":        price,
        "url":          listing.get("url", ""),
        "category":     listing.get("category") or "",
        "age_days":     age,
        "watchers":     watchers,
        "sold_7d":      sold_7d,
        "sold_30d":     sold_30d,
        "market_median": market_median,
        "tier":         None,
        "rate":         0.0,
        "reasons":      [],
        "blocked":      False,
        "blocked_reason": None,
        "margin_pct":   None,
        "projected_30d_spend": 0.0,
        "projected_30d_lift_usd": 0.0,
    }

    # Hard blocks.
    cat = str(decision["category"])
    if cat and cat in {str(x) for x in cfg.get("skip_categories", [])}:
        decision["blocked"] = True
        decision["blocked_reason"] = f"category {cat} in skip_categories"
        decision["tier"] = "no_ad"
        decision["reasons"].append(decision["blocked_reason"])
        return decision

    if price <= 0:
        decision["blocked"] = True
        decision["blocked_reason"] = "no current price on listing"
        decision["tier"] = "no_ad"
        decision["reasons"].append(decision["blocked_reason"])
        return decision

    margin = _est_margin_pct(listing)
    decision["margin_pct"] = round(margin, 4) if margin is not None else None

    tier_key, reasons = classify(
        listing,
        age_days=age,
        watchers=watchers,
        sold_7d=sold_7d,
        market_median=market_median,
        cfg=cfg,
    )
    rate = cfg["tiers"][tier_key]["rate"]

    # Margin guard — never promote a listing that's already too thin.
    min_margin = cfg.get("min_margin_pct_to_promote", 0.15)
    if rate > 0 and margin is not None and margin < min_margin:
        reasons.append(
            f"margin proxy {margin*100:.0f}% < min {min_margin*100:.0f}% — forcing NO_AD"
        )
        tier_key = "no_ad"
        rate = 0.0

    decision["tier"] = tier_key
    decision["rate"] = rate
    decision["reasons"].extend(reasons)

    # Project 30-day ad spend = price × rate × prob(sells in 30d).
    p_sell_30d = 1.0 if sold_30d >= 1 else cfg.get("default_30d_sellthrough", 0.25)
    decision["projected_30d_spend"] = round(price * rate * p_sell_30d, 4)

    # Rough lift: bid rate already implies aggressiveness; map linearly into the
    # 4–12% lift band eBay publishes for Promoted Listings.
    lift_pct = EBAY_LIFT_MIN + (EBAY_LIFT_MAX - EBAY_LIFT_MIN) * min(1.0, rate / 0.20)
    decision["projected_30d_lift_usd"] = round(price * lift_pct * p_sell_30d, 4)

    return decision


def _segment_median_for_title(title: str, segments: dict) -> float | None:
    if not segments:
        return None
    t = (title or "").lower()
    # Crude but deterministic — same buckets used elsewhere in the site.
    if "pokemon" in t or "pokémon" in t:
        bucket = "Pokemon"
    elif "marvel" in t or "psa 10" in t:
        bucket = "Marvel PSA 10"
    elif any(k in t for k in ("basketball", "nba", "lebron", "jordan")):
        bucket = "Basketball Singles"
    elif any(k in t for k in ("baseball", "mlb")):
        bucket = "Baseball Singles"
    else:
        bucket = "Football Singles"
    seg = segments.get(bucket)
    if isinstance(seg, dict):
        m = seg.get("median")
        try:
            return float(m) if m is not None else None
        except (TypeError, ValueError):
            return None
    return None


# --------------------------------------------------------------------------- #
# Budget cap                                                                  #
# --------------------------------------------------------------------------- #

def apply_budget_cap(plan: list[dict], cap_usd: float) -> tuple[list[dict], list[str]]:
    """
    If projected 30-day ad spend exceeds the cap, demote the highest-rate items
    one tier at a time until we fit. Returns (plan, demoted_item_ids[]).
    Demotion order: max → aggressive → standard → low → no_ad.
    """
    demoted: list[str] = []
    if cap_usd is None or cap_usd <= 0:
        return plan, demoted

    def total() -> float:
        return sum(d.get("projected_30d_spend", 0.0) for d in plan)

    # Iteratively pick the most expensive non-NO_AD decision and step it down a tier.
    demote_to = {
        "max":        ("aggressive", 0.15),
        "aggressive": ("standard",   0.08),
        "standard":   ("low",        0.03),
        "low":        ("no_ad",      0.0),
    }
    guard = 0
    while total() > cap_usd and guard < 10_000:
        guard += 1
        candidates = [d for d in plan if d["tier"] in demote_to and not d["blocked"]]
        if not candidates:
            break
        # Pick the single largest projected spend
        worst = max(candidates, key=lambda d: d["projected_30d_spend"])
        new_tier, new_rate = demote_to[worst["tier"]]
        worst["reasons"].append(
            f"budget cap ${cap_usd:.0f} hit — demoted {worst['tier']} → {new_tier}"
        )
        worst["tier"] = new_tier
        worst["rate"] = new_rate
        # Recompute spend.
        p_sell = 1.0 if worst["sold_30d"] >= 1 else 0.25
        worst["projected_30d_spend"] = round(worst["price"] * new_rate * p_sell, 4)
        if worst["item_id"] not in demoted:
            demoted.append(worst["item_id"])
    return plan, demoted


# --------------------------------------------------------------------------- #
# eBay Marketing API                                                          #
# --------------------------------------------------------------------------- #

def get_marketing_token(cfg: dict) -> str:
    """
    Mint an access token with the full Marketing scope. The repricing_agent
    reuses promote.get_access_token (inventory + fulfillment scopes); we need
    sell.marketing here, so we make our own token request from the same
    refresh_token. This mirrors connector.py.
    """
    credentials = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    scopes = " ".join([
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/sell.marketing",
        "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    ])
    resp = requests.post(
        EBAY_TOKEN_URL,
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
    resp.raise_for_status()
    return resp.json()["access_token"]


def _marketing_headers(token: str) -> dict:
    return {
        "Authorization":          f"Bearer {token}",
        "Content-Type":           "application/json",
        "Accept":                 "application/json",
        "Content-Language":       "en-US",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }


def list_campaigns(token: str) -> list[dict]:
    url = f"{EBAY_MARKETING_BASE}/ad_campaign"
    out: list[dict] = []
    params = {"limit": 50}
    while True:
        r = requests.get(url, headers=_marketing_headers(token), params=params, timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"list_campaigns failed: {r.status_code} {r.text[:300]}")
        body = r.json()
        out.extend(body.get("campaigns", []) or [])
        nxt = body.get("next")
        if not nxt:
            break
        url, params = nxt, None
    return out


def create_campaign(token: str, cfg_default: dict) -> dict:
    """POST /sell/marketing/v1/ad_campaign — minimal bootstrap.

    Two gotchas eBay docs hide:
      1. endDate must be strictly AFTER startDate (the old +month-via-replace
         arithmetic produced end == start → HTTP 400 errorId 35024).
      2. CPS funding model REJECTS a `budget` block (HTTP 409 errorId 36156).
         Only include budget for fundingModels that take one (none today).
    """
    start = datetime.now(timezone.utc).replace(microsecond=0)
    days  = int(cfg_default.get("duration_days", 30))
    end   = start + timedelta(days=days)
    body = {
        "campaignName":     cfg_default.get("name", "Auto-Optimized"),
        "marketplaceId":    cfg_default.get("marketplace", "EBAY_US"),
        "startDate":        start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "endDate":          end.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "fundingStrategy": {
            "fundingModel":          cfg_default.get("funding_model", "COST_PER_SALE"),
            "bidPercentage":         "8.0",
        },
    }
    r = requests.post(
        f"{EBAY_MARKETING_BASE}/ad_campaign",
        headers=_marketing_headers(token),
        json=body, timeout=30,
    )
    if r.status_code not in (201, 200):
        raise RuntimeError(f"create_campaign failed: {r.status_code} {r.text[:500]}")
    # eBay returns the new campaignId in the Location header.
    loc = r.headers.get("Location", "")
    campaign_id = loc.rsplit("/", 1)[-1] if loc else r.json().get("campaignId", "")
    return {"campaignId": campaign_id, "raw": r.text}


def bulk_set_bids(token: str, campaign_id: str,
                  decisions: list[dict]) -> list[dict]:
    """
    POST /sell/marketing/v1/ad_campaign/{campaignId}/bulk_create_listings_by_inventory_reference
    to set per-listing bid percentages.

    eBay expects bid percentages as strings like "3.0" not floats.
    Returns the API responses (one per chunked call), plus per-listing results.
    """
    if not decisions:
        return []
    results: list[dict] = []
    # eBay caps bulk operations at 500 per call; we chunk conservatively.
    CHUNK = 200
    for i in range(0, len(decisions), CHUNK):
        chunk = decisions[i:i + CHUNK]
        body = {
            "requests": [
                {
                    "listingId":    d["item_id"],
                    "bidPercentage": f"{d['rate'] * 100:.1f}",
                }
                for d in chunk
            ],
        }
        # Correct endpoint name (the docs example renamed; old name 404s).
        url = (f"{EBAY_MARKETING_BASE}/ad_campaign/{campaign_id}"
               f"/bulk_create_ads_by_listing_id")
        r = requests.post(url, headers=_marketing_headers(token), json=body, timeout=60)
        ok = r.status_code in (200, 201, 207)
        try:
            payload = r.json()
        except Exception:
            payload = {"raw": r.text[:1000]}
        results.append({
            "http":    r.status_code,
            "ok":      ok,
            "payload": payload,
            "chunk_size": len(chunk),
        })
        time.sleep(0.5)
    return results


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    return f"${n:,.2f}"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    return f"{n * 100:.1f}%"


TIER_DISPLAY = {
    "no_ad":      ("NO_AD",      "tier-no-ad"),
    "low":        ("LOW",        "tier-low"),
    "standard":   ("STANDARD",   "tier-standard"),
    "aggressive": ("AGGRESSIVE", "tier-aggressive"),
    "max":        ("MAX",        "tier-max"),
}


def build_report(plan: list[dict], history: list[dict], cfg: dict,
                 demoted_ids: list[str]) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    by_tier: dict[str, list[dict]] = {k: [] for k in TIER_ORDER}
    for d in plan:
        by_tier.setdefault(d["tier"] or "no_ad", []).append(d)

    total_spend = sum(d.get("projected_30d_spend", 0.0) for d in plan)
    total_lift  = sum(d.get("projected_30d_lift_usd", 0.0) for d in plan)
    cap_usd     = cfg.get("max_total_30d_ad_spend_usd")

    # Tier summary table
    summary_rows = []
    for tier in TIER_ORDER:
        items = by_tier.get(tier, [])
        rate = cfg["tiers"][tier]["rate"]
        tier_spend = sum(d.get("projected_30d_spend", 0.0) for d in items)
        tier_lift  = sum(d.get("projected_30d_lift_usd", 0.0) for d in items)
        label, klass = TIER_DISPLAY[tier]
        summary_rows.append(f"""
        <tr class="{klass}">
          <td class="tier-label">{label}</td>
          <td class="num">{_fmt_pct(rate)}</td>
          <td class="num">{len(items)}</td>
          <td class="num">{_fmt_money(tier_spend)}</td>
          <td class="num gold">{_fmt_money(tier_lift)}</td>
          <td class="criteria">{cfg['tiers'][tier]['criteria']}</td>
        </tr>""")

    def _row(d: dict) -> str:
        label, klass = TIER_DISPLAY.get(d["tier"], ("?", ""))
        reasons = "<br>".join(d.get("reasons", []) or [])
        age = d.get("age_days")
        age_str = f"{age}d" if age is not None else "—"
        return f"""
        <tr class="row-{klass}">
          <td class="item">
            <a href="{d['url']}" target="_blank" rel="noopener">
              <span class="title">{(d['title'] or '')[:90]}</span>
              <span class="item-id">{d['item_id']}</span>
            </a>
          </td>
          <td class="num">{_fmt_money(d['price'])}</td>
          <td class="num">{age_str}</td>
          <td class="num">{d.get('watchers', 0)}</td>
          <td class="num">{d.get('sold_30d', 0)}</td>
          <td class="tier-cell {klass}">{label}</td>
          <td class="num gold">{_fmt_pct(d['rate'])}</td>
          <td class="num">{_fmt_money(d.get('projected_30d_spend'))}</td>
          <td class="reasons">{reasons}</td>
        </tr>"""

    detail_rows = "\n".join(_row(d) for d in plan)

    recent_history = list(reversed(history))[:50]
    hist_rows = "\n".join(
        f"<tr><td>{h.get('applied_at','')}</td>"
        f"<td><a href='{h.get('url','#')}' target='_blank'>{h.get('item_id')}</a></td>"
        f"<td>{h.get('tier','')}</td>"
        f"<td class='num'>{_fmt_pct(h.get('rate', 0))}</td>"
        f"<td>{'OK' if h.get('ok') else 'FAIL'}</td></tr>"
        for h in recent_history
    )
    history_block = (
        f"<div class='tbl-wrap'><table class='promo-tbl'>"
        f"<thead><tr><th>Applied</th><th>Item</th><th>Tier</th><th>Rate</th><th>Result</th></tr></thead>"
        f"<tbody>{hist_rows}</tbody></table></div>"
        if recent_history else "<p class='empty'>No bid changes applied yet.</p>"
    )

    cap_note = ""
    if cap_usd:
        over = total_spend > cap_usd
        cap_note = (
            f"<div class='cap-note {'cap-hit' if over else 'cap-ok'}'>"
            f"Projected 30d ad spend: <b>{_fmt_money(total_spend)}</b> of cap "
            f"<b>{_fmt_money(cap_usd)}</b>. "
            f"{'Cap was hit — demoted items below.' if demoted_ids else 'Within cap.'}"
            f"</div>"
        )

    demoted_block = ""
    if demoted_ids:
        items = [d for d in plan if d["item_id"] in set(demoted_ids)]
        rows = "\n".join(
            f"<li><a href='{d['url']}' target='_blank'>{d['item_id']}</a> — "
            f"{(d['title'] or '')[:80]} (now {TIER_DISPLAY[d['tier']][0]})</li>"
            for d in items
        )
        demoted_block = (
            "<section><h3>Demoted to fit budget cap</h3>"
            f"<ul class='demoted'>{rows}</ul></section>"
        )

    body = f"""
<section class="hero">
  <h1>Promoted Listings Agent</h1>
  <p class="sub">Last run: <code>{run_ts}</code> · {len(plan)} listings classified</p>
  <div class="stat-grid">
    <div class="stat"><div class="stat-n">{len([d for d in plan if d['rate'] > 0])}</div><div class="stat-l">Promoted</div></div>
    <div class="stat"><div class="stat-n">{len(by_tier.get('no_ad', []))}</div><div class="stat-l">Self-selling</div></div>
    <div class="stat"><div class="stat-n">{_fmt_money(total_spend)}</div><div class="stat-l">30d ad spend</div></div>
    <div class="stat"><div class="stat-n">{_fmt_money(total_lift)}</div><div class="stat-l">Est. lift</div></div>
  </div>
  {cap_note}
</section>

<section class="cfg">
  <h3>Tier breakdown</h3>
  <div class="tbl-wrap">
    <table class="promo-tbl summary">
      <thead><tr><th>Tier</th><th>Rate</th><th>Listings</th><th>30d spend</th><th>Est. lift</th><th>Criteria</th></tr></thead>
      <tbody>{''.join(summary_rows)}</tbody>
    </table>
  </div>
  <p class='hint'>Edit <code>promoted_listings_config.json</code> to retune. Run with <code>--apply</code> to push bids via the Marketing API.</p>
</section>

{demoted_block}

<section>
  <h3>Per-listing decisions</h3>
  <div class='tbl-wrap'>
    <table class='promo-tbl'>
      <thead><tr>
        <th>Listing</th><th>Price</th><th>Age</th><th>Watchers</th>
        <th>Sold 30d</th><th>Tier</th><th>Bid %</th><th>30d $</th><th>Reasoning</th>
      </tr></thead>
      <tbody>{detail_rows}</tbody>
    </table>
  </div>
</section>

<section>
  <h3>Recent applied bid changes</h3>
  {history_block}
</section>
"""

    extra_css = """
<style>
  .hero { padding: 24px 0 12px; }
  .hero h1 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 56px; letter-spacing: .02em; }
  .hero .sub { color: var(--text-muted); }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 18px 0; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 16px; }
  .stat-n { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: var(--gold); line-height: 1; }
  .stat-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; }
  .cap-note { padding: 10px 14px; border-radius: var(--r-md); margin: 10px 0; }
  .cap-ok { background: rgba(127,199,122,0.07); border: 1px solid rgba(127,199,122,0.25); color: var(--text); }
  .cap-hit { background: rgba(220,89,89,0.08); border: 1px solid rgba(220,89,89,0.30); color: var(--text); }
  .cfg { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .cfg h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .cfg .hint { color: var(--text-muted); font-size: 13px; margin: 10px 0 0; }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.promo-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .promo-tbl th, .promo-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .promo-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .promo-tbl tr:hover td { background: var(--surface-2); }
  .promo-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .promo-tbl .gold { color: var(--gold); font-weight: 600; }
  .promo-tbl .item .title { display: block; color: var(--text); }
  .promo-tbl .item .item-id { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .promo-tbl .item a { text-decoration: none; }
  .promo-tbl .item a:hover .title { color: var(--gold); }
  .promo-tbl .reasons { color: var(--text-muted); font-size: 12px; max-width: 360px; }
  .promo-tbl .criteria { color: var(--text-dim); font-size: 12px; font-family: 'JetBrains Mono', monospace; }
  .tier-label, .tier-cell { font-weight: 700; font-size: 11px; letter-spacing: .1em; }
  .tier-no-ad      { color: var(--text-muted); }
  .tier-low        { color: #79b9ff; }
  .tier-standard   { color: var(--gold); }
  .tier-aggressive { color: #ffae5e; }
  .tier-max        { color: var(--danger); }
  .row-tier-aggressive td { background: linear-gradient(to right, rgba(255,174,94,0.05), transparent); }
  .row-tier-max td { background: linear-gradient(to right, rgba(220,89,89,0.07), transparent); }
  .demoted { color: var(--text-muted); font-size: 13px; }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
</style>
"""

    html = promote.html_shell(
        "Promoted Listings Agent · Harpua2001",
        body,
        extra_head=extra_css,
        active_page="promoted_listings.html",
    )
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def plan_all(cfg: dict) -> tuple[list[dict], list[str]]:
    listings = _load_listings()
    sold     = promote._load_sold_history()
    sold_idx = _sold_index_by_item_id(sold)
    segments = _load_market_segments()

    try:
        snapshot_mtime = datetime.fromtimestamp(LISTINGS_SNAPSHOT.stat().st_mtime, timezone.utc)
    except FileNotFoundError:
        snapshot_mtime = datetime.now(timezone.utc)

    plan = [
        build_decision(l, sold_idx, segments, snapshot_mtime, cfg)
        for l in listings
    ]
    cap = cfg.get("max_total_30d_ad_spend_usd")
    plan, demoted = apply_budget_cap(plan, cap)
    return plan, demoted


def summarize(plan: list[dict]) -> None:
    counts = {k: 0 for k in TIER_ORDER}
    for d in plan:
        counts[d["tier"]] = counts.get(d["tier"], 0) + 1
    total_spend = sum(d.get("projected_30d_spend", 0.0) for d in plan)
    print(f"\n  Tier breakdown across {len(plan)} listings:")
    for tier in TIER_ORDER:
        label, _ = TIER_DISPLAY[tier]
        print(f"    {label:>10s} ({counts[tier]:>3d})")
    print(f"  Projected 30-day ad spend: ${total_spend:,.2f}")


def apply_plan(plan: list[dict], ebay_cfg: dict, cfg: dict,
               create_campaign_if_missing: bool) -> list[dict]:
    """Push every non-zero bid through the Marketing API."""
    token = get_marketing_token(ebay_cfg)
    campaigns = list_campaigns(token)
    campaign_id = None
    if campaigns:
        campaign_id = campaigns[0].get("campaignId")
        print(f"  Using existing campaign {campaign_id} "
              f"({campaigns[0].get('campaignName', '')})")
    elif create_campaign_if_missing:
        print("  No campaigns found — creating one with defaults...")
        created = create_campaign(token, cfg["default_campaign"])
        campaign_id = created["campaignId"]
        print(f"  Created campaign {campaign_id}")
    else:
        print("  No campaigns exist. Re-run with --create-campaign to bootstrap one.")
        return []

    # Only push items that should actually run an ad.
    to_push = [d for d in plan if d["rate"] > 0 and not d["blocked"]]
    print(f"  Pushing {len(to_push)} per-listing bid percentages...")
    api_results = bulk_set_bids(token, campaign_id, to_push)

    # Flatten per-listing results into history records.
    now_iso = datetime.now(timezone.utc).isoformat()
    by_listing_status: dict[str, dict] = {}
    for resp in api_results:
        payload = resp.get("payload") or {}
        for row in (payload.get("responses") or []):
            lid = row.get("listingId") or row.get("inventoryReference")
            if lid:
                by_listing_status[str(lid)] = {
                    "ok":     200 <= int(row.get("statusCode") or 0) < 300,
                    "status": row.get("statusCode"),
                    "errors": row.get("errors") or [],
                }

    history: list[dict] = []
    for d in to_push:
        st = by_listing_status.get(d["item_id"])
        ok = bool(st["ok"]) if st else any(r["ok"] for r in api_results)
        history.append({
            "applied_at": now_iso,
            "item_id":    d["item_id"],
            "title":      d["title"],
            "tier":       d["tier"],
            "rate":       d["rate"],
            "campaign_id": campaign_id,
            "ok":          ok,
            "status":      st.get("status") if st else None,
            "errors":      st.get("errors") if st else None,
            "url":         d.get("url"),
        })
    ok_count = sum(1 for h in history if h["ok"])
    print(f"  Result: {ok_count}/{len(history)} bids accepted.")
    return history


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Per-listing Promoted Listings ad rates for Harpua2001 eBay store."
    )
    ap.add_argument("--apply", action="store_true",
                    help="Actually push bid changes to eBay (default: dry run).")
    ap.add_argument("--create-campaign", action="store_true",
                    help="If no campaign exists, bootstrap one before applying.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild docs/promoted_listings.html from the last plan.")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("enabled", True):
        print("Promoted Listings agent disabled in promoted_listings_config.json.")
        return 0

    if args.report_only:
        plan = []
        if PLAN_PATH.exists():
            try:
                plan = json.loads(PLAN_PATH.read_text()).get("decisions", [])
            except Exception:
                plan = []
        path = build_report(plan, load_history(), cfg, [])
        print(f"  Wrote {path}")
        return 0

    plan, demoted = plan_all(cfg)
    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config":       cfg,
        "demoted_for_budget_cap": demoted,
        "decisions":    plan,
    }, indent=2))
    summarize(plan)
    if demoted:
        print(f"  {len(demoted)} listings demoted to stay under "
              f"${cfg['max_total_30d_ad_spend_usd']:.0f} budget cap.")

    if args.apply:
        print("\n  Applying bid changes to eBay Marketing API...")
        ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
        applied = apply_plan(plan, ebay_cfg, cfg,
                             create_campaign_if_missing=args.create_campaign)
        append_history(applied)
    else:
        print("\n  Dry run only. Re-run with --apply to push bids to eBay.")

    report = build_report(plan, load_history(), cfg, demoted)
    print(f"  Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
