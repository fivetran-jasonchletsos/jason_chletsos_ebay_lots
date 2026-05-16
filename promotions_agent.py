"""
promotions_agent.py — stale-inventory markdown ladder + store-wide volume discount.

Two complementary revenue moves for the Harpua2001 lot store:

  (a) Stale-inventory markdown ladder. Items sitting beyond age thresholds get
      a programmatic markdown via eBay's Promotions Manager
      "Item Price Markdown" promotion (the one that paints the strikethrough
      price on the listing — great conversion UX). Tiers default to:
          61-120d  →  5%
          121-180d → 12%
          181d+    → 22% + flag_for_review (consider relist/delist)
      Respects a floor: max($1.00, sold_history.median * 0.75, price * 0.55).

  (b) Store-wide volume discount. One-shot idempotent setup of a single
      VOLUME_DISCOUNT item_promotion (Buy 2 save 5% · Buy 5 save 12% ·
      Buy 10 save 20%). Subsequent runs only reconcile drift.

Default = dry run. Use --apply to actually write to eBay.

Usage:
    python promotions_agent.py                 # dry run (default)
    python promotions_agent.py --apply         # write markdowns + ensure vol disc
    python promotions_agent.py --no-fetch      # reuse cached snapshot
    python promotions_agent.py --report-only   # rebuild docs/promotions.html
    python promotions_agent.py --markdowns-only
    python promotions_agent.py --volume-only

Artifacts:
    promotions_config.json            tunable settings
    output/promotions_plan.json       latest plan
    output/promotions_history.json    append-only application log
    output/listing_ages.json          per-item age cache (start_time)
    docs/promotions.html              human report
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

import promote

REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "promotions_config.json"
PLAN_PATH          = REPO_ROOT / "output" / "promotions_plan.json"
HISTORY_PATH       = REPO_ROOT / "output" / "promotions_history.json"
LISTING_AGES_PATH  = REPO_ROOT / "output" / "listing_ages.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
REPORT_PATH        = promote.OUTPUT_DIR / "promotions.html"

EBAY_NS  = "urn:ebay:apis:eBLBaseComponents"
MARKETING_BASE = "https://api.ebay.com/sell/marketing/v1"

DEFAULT_CONFIG: dict = {
    "enabled": True,
    "markdown_tiers": [
        {"min_age_days": 61,  "max_age_days": 120,  "pct": 0.05},
        {"min_age_days": 121, "max_age_days": 180,  "pct": 0.12},
        {"min_age_days": 181, "max_age_days": 9999, "pct": 0.22, "flag_for_review": True},
    ],
    "floor_multiplier":         0.55,
    "absolute_floor":           1.00,
    "sold_floor_multiplier":    0.75,
    "volume_discount": {
        "enabled":  True,
        "name":     "Harpua2001 Volume Discount",
        "tiers": [
            {"min_quantity": 2,  "discount_pct": 0.05},
            {"min_quantity": 5,  "discount_pct": 0.12},
            {"min_quantity": 10, "discount_pct": 0.20},
        ],
    },
    "skip_categories":          [],
    "skip_keywords":            [],
    "max_markdowns_per_run":    30,
    "dead_zone_cents":          5,
    "marketplace_id":           "EBAY_US",
    "promotion_status_when_creating": "SCHEDULED",
}

# Marketing API needs its own scope on the user OAuth token.
MARKETING_SCOPES = [
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
]


# --------------------------------------------------------------------------- #
# Config + history I/O                                                        #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return json.loads(json.dumps(DEFAULT_CONFIG))
    cfg = json.loads(CONFIG_PATH.read_text())
    # Shallow-fill missing top-level keys
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    cfg["volume_discount"] = {**DEFAULT_CONFIG["volume_discount"], **(cfg.get("volume_discount") or {})}
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


def load_listing_ages() -> dict:
    if not LISTING_AGES_PATH.exists():
        return {}
    try:
        return json.loads(LISTING_AGES_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_listing_ages(ages: dict) -> None:
    LISTING_AGES_PATH.parent.mkdir(exist_ok=True)
    LISTING_AGES_PATH.write_text(json.dumps(ages, indent=2))


# --------------------------------------------------------------------------- #
# OAuth                                                                       #
# --------------------------------------------------------------------------- #

def get_marketing_token(cfg: dict) -> str | None:
    """Refresh-token exchange with Marketing scopes. Returns None on failure."""
    import base64
    creds = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post(
        "https://api.ebay.com/identity/v1/oauth2/token",
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        data={
            "grant_type":    "refresh_token",
            "refresh_token": cfg["refresh_token"],
            "scope":         " ".join(MARKETING_SCOPES),
        },
        timeout=30,
    )
    if r.status_code != 200:
        print(f"  Marketing token error {r.status_code}: {r.text[:240]}")
        return None
    return r.json().get("access_token")


def get_trading_token(cfg: dict) -> str:
    """Standard refresh-token exchange (no Marketing scope). For Trading API."""
    return promote.get_access_token(cfg)


# --------------------------------------------------------------------------- #
# Listing age inference                                                       #
# --------------------------------------------------------------------------- #

def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def fetch_listing_ages(token: str, ebay_cfg: dict, item_ids: list[str],
                       cache: dict) -> dict:
    """For each item_id missing from cache, call GetItem to fetch StartTime.

    Trading API GetItem returns ListingDetails/StartTime in ISO format. We
    cache aggressively (start times don't change) and skip already-known ones.
    """
    missing = [iid for iid in item_ids if iid not in cache or not cache[iid].get("start_time")]
    if not missing:
        return cache
    print(f"  Fetching listing start times via Trading API GetItem for {len(missing)} item(s)...")
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "GetItem",
        "X-EBAY-API-APP-NAME":            ebay_cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            ebay_cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":           ebay_cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }
    for iid in missing:
        body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{iid}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""
        try:
            r = requests.post("https://api.ebay.com/ws/api.dll",
                              headers=headers, data=body.encode(), timeout=20)
            root = ET.fromstring(r.text)
            st = root.findtext(f".//{{{EBAY_NS}}}ListingDetails/{{{EBAY_NS}}}StartTime", "")
            cache[iid] = {"start_time": st, "fetched_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            cache[iid] = {"start_time": "", "error": str(exc),
                          "fetched_at": datetime.now(timezone.utc).isoformat()}
        time.sleep(0.3)  # gentle pacing
    save_listing_ages(cache)
    return cache


def _heuristic_age_days(item_id: str, all_item_ids: list[str]) -> int:
    """When real start times are unavailable, estimate age by item_id rank.

    eBay item_ids are roughly monotonically increasing. We rank the seller's
    own active listings: the lowest-numbered item is treated as the oldest
    (assume ~365d), the highest as newest (~0d), linear interpolation between.
    This is intentionally crude — used only when the network fetch is
    unavailable (e.g. dry-run on a fresh checkout).
    """
    if not item_id or not all_item_ids:
        return 0
    try:
        ordered = sorted(set(all_item_ids), key=lambda x: int(x))
    except ValueError:
        ordered = sorted(set(all_item_ids))
    if item_id not in ordered or len(ordered) < 2:
        return 0
    idx = ordered.index(item_id)
    # idx 0 = oldest. Map to age ∈ [0, 365] reversed.
    rank_pct = 1.0 - (idx / (len(ordered) - 1))
    return int(round(rank_pct * 365))


def age_for_listing(listing: dict, ages_cache: dict, all_item_ids: list[str]) -> tuple[int, str]:
    """Return (age_days, source). source ∈ {'start_time','heuristic'}."""
    iid = listing["item_id"]
    entry = ages_cache.get(iid) or {}
    st = entry.get("start_time")
    dt = _parse_iso(st) if st else None
    if dt:
        now = datetime.now(timezone.utc)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        days = max(0, int((now - dt).total_seconds() // 86400))
        return days, "start_time"
    return _heuristic_age_days(iid, all_item_ids), "heuristic"


# --------------------------------------------------------------------------- #
# Sold-history index for floors                                               #
# --------------------------------------------------------------------------- #

def _tokens(title: str) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-z0-9]+", (title or "").lower()) if len(t) > 2}


def sold_median_for(listing: dict, sold: list[dict]) -> float | None:
    """Crude title-token-overlap match against sold_history. Returns median sale_price
    of best-matched sales (>=3 token overlap), or None.
    """
    if not sold:
        return None
    target = _tokens(listing.get("title", ""))
    if len(target) < 3:
        return None
    matches: list[float] = []
    for s in sold:
        ot = _tokens(s.get("title", ""))
        overlap = target & ot
        if len(overlap) >= max(3, int(len(target) * 0.4)):
            try:
                matches.append(float(s.get("sale_price") or 0))
            except (TypeError, ValueError):
                continue
    matches = [m for m in matches if m > 0]
    if not matches:
        return None
    matches.sort()
    n = len(matches)
    if n % 2:
        return matches[n // 2]
    return (matches[n // 2 - 1] + matches[n // 2]) / 2


# --------------------------------------------------------------------------- #
# Markdown planning                                                            #
# --------------------------------------------------------------------------- #

def _tier_for_age(age_days: int, cfg: dict) -> dict | None:
    for tier in cfg["markdown_tiers"]:
        if tier["min_age_days"] <= age_days <= tier["max_age_days"]:
            return tier
    return None


def _round_psych(price: float) -> float:
    """End on .99 like the rest of the store, floor at $0.99."""
    if price <= 0:
        return 0.99
    if price < 1:
        return 0.99
    floor_d = int(price)
    if price - floor_d < 0.50:
        return max(0.99, round(floor_d - 0.01, 2))
    return round(floor_d + 0.99, 2)


def plan_markdown(listing: dict, age_days: int, age_source: str,
                  sold_median: float | None, cfg: dict) -> dict:
    iid = listing["item_id"]
    try:
        current = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        current = 0.0

    decision = {
        "item_id":           iid,
        "title":             listing.get("title", ""),
        "url":               listing.get("url", ""),
        "current_price":     round(current, 2),
        "age_days":          age_days,
        "age_source":        age_source,
        "tier":              None,
        "discount_pct":      None,
        "raw_target":        None,
        "target_price":      None,
        "floor":             None,
        "sold_median":       sold_median,
        "flag_for_review":   False,
        "decision":          "skip",
        "reasons":           [],
    }

    if current <= 0:
        decision["reasons"].append("no current price")
        return decision

    title_lower = (listing.get("title") or "").lower()
    for kw in cfg.get("skip_keywords", []):
        if kw and kw.lower() in title_lower:
            decision["decision"] = "blocked"
            decision["reasons"].append(f"skip_keyword:{kw}")
            return decision

    cat = (listing.get("category") or "").lower()
    for sc in cfg.get("skip_categories", []):
        if sc and sc.lower() in cat:
            decision["decision"] = "blocked"
            decision["reasons"].append(f"skip_category:{sc}")
            return decision

    tier = _tier_for_age(age_days, cfg)
    if not tier:
        decision["reasons"].append(f"age {age_days}d below first tier (61d)")
        return decision

    decision["tier"]            = f"{tier['min_age_days']}-{tier['max_age_days']}d"
    decision["discount_pct"]    = tier["pct"]
    decision["flag_for_review"] = bool(tier.get("flag_for_review"))

    raw_target = round(current * (1 - tier["pct"]), 2)
    decision["raw_target"] = raw_target

    # Floor: max(absolute_floor, sold_median * sold_floor_multiplier, current * floor_multiplier)
    floor_candidates = [cfg["absolute_floor"], round(current * cfg["floor_multiplier"], 2)]
    if sold_median and sold_median > 0:
        floor_candidates.append(round(sold_median * cfg["sold_floor_multiplier"], 2))
    floor = max(floor_candidates)
    decision["floor"] = floor

    target = max(raw_target, floor)
    target = _round_psych(target)
    # Make sure psych-rounding didn't push us back above pre-discount price.
    if target >= current:
        decision["decision"] = "skip"
        decision["reasons"].append(
            f"computed target ${target:.2f} >= current ${current:.2f} after floor/round"
        )
        return decision

    # Skip if discount on listing already at-or-below the sold floor for tier 1
    # (i.e. don't deepen markdowns past the sold-history floor).
    if sold_median and current <= round(sold_median * 0.95, 2) and tier["pct"] <= 0.06:
        decision["decision"] = "skip"
        decision["reasons"].append(
            f"current ${current:.2f} already at sold_median*0.95 floor (${sold_median*0.95:.2f})"
        )
        return decision

    # Dead zone: don't bother with sub-5¢ markdowns
    if (current - target) * 100 < cfg["dead_zone_cents"]:
        decision["decision"] = "skip"
        decision["reasons"].append(
            f"delta {(current-target)*100:.0f}¢ < dead_zone_cents={cfg['dead_zone_cents']}"
        )
        return decision

    decision["target_price"] = target
    decision["decision"]     = "apply"
    decision["reasons"].append(
        f"age {age_days}d ({age_source}) → tier {decision['tier']} @ {tier['pct']*100:.0f}% "
        f"→ ${target:.2f} (floor ${floor:.2f})"
    )
    if decision["flag_for_review"]:
        decision["reasons"].append("flagged for manual review — consider relist/delist")
    return decision


# --------------------------------------------------------------------------- #
# eBay Marketing API: Item Price Markdown                                     #
# --------------------------------------------------------------------------- #

def _markdown_payload(decision: dict, cfg: dict, marketplace_id: str) -> dict:
    """Build the POST body for /sell/marketing/v1/item_price_markdown.

    One promotion per listing is the simplest mapping. Discount is supplied as
    an absolute marked-down `priceDiscount.value`. eBay paints the
    strikethrough automatically.
    """
    discount_amount = round(decision["current_price"] - decision["target_price"], 2)
    now = datetime.now(timezone.utc)
    start_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    return {
        "name":                  f"Markdown {decision['item_id']} ({decision['tier']})",
        "marketplaceId":         marketplace_id,
        "promotionStatus":       cfg["promotion_status_when_creating"],
        "startDate":             start_iso,
        "applyMarkdownDiscount": True,
        "promotionType":         "MARKDOWN_SALE",
        "selectedInventoryDiscounts": [{
            "discountBenefit": {
                "amountOffItem": {"value": f"{discount_amount:.2f}", "currency": "USD"},
            },
            "ruleSelectionType": "INVENTORY_BY_VALUE",
            "inventoryCriterion": {
                "inventoryCriterionType": "INVENTORY_BY_VALUE",
                "listingIds": [decision["item_id"]],
            },
        }],
    }


def apply_markdown(token: str, decision: dict, cfg: dict) -> dict:
    """Create an item_price_markdown promotion for one listing."""
    url = f"{MARKETING_BASE}/item_price_markdown"
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "Content-Language": "en-US",
    }
    payload = _markdown_payload(decision, cfg, cfg.get("marketplace_id", "EBAY_US"))
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        return {"ok": False, "http": 0, "error": str(exc), "payload": payload}
    body = r.text
    try:
        data = r.json() if body else {}
    except json.JSONDecodeError:
        data = {"raw": body}
    ok = r.status_code in (200, 201, 204)
    return {
        "ok":     ok,
        "http":   r.status_code,
        "data":   data,
        "error":  None if ok else (data.get("errors") if isinstance(data, dict) else body)[:600] if not ok else None,
        "payload": payload,
    }


# --------------------------------------------------------------------------- #
# eBay Marketing API: Volume Discount item_promotion                          #
# --------------------------------------------------------------------------- #

def _volume_discount_payload(cfg: dict, marketplace_id: str) -> dict:
    """Build the body for POST /sell/marketing/v1/item_promotion (VOLUME_DISCOUNT).

    Applies to the entire store inventory (selectionRules: All) and stacks
    three buy-N-save-X thresholds.
    """
    vd = cfg["volume_discount"]
    now = datetime.now(timezone.utc)
    start_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    discount_rules = []
    for tier in vd["tiers"]:
        discount_rules.append({
            "discountBenefit": {
                "percentageOffOrder": f"{tier['discount_pct']*100:.2f}",
            },
            "discountSpecification": {
                "minQuantity": int(tier["min_quantity"]),
            },
        })
    return {
        "name":                  vd.get("name", "Store Volume Discount"),
        "description":           "Buy more, save more — store-wide volume discount.",
        "marketplaceId":         marketplace_id,
        "promotionStatus":       cfg["promotion_status_when_creating"],
        "promotionType":         "VOLUME_DISCOUNT",
        "startDate":             start_iso,
        "applyDiscountToSingleItemOnly": False,
        "selectionRules": [{
            "selectionType":      "ALL_INVENTORY_BY_SELLER",
        }],
        "discountRules":         discount_rules,
    }


def find_existing_volume_promotion(token: str, marketplace_id: str) -> dict | None:
    """GET /sell/marketing/v1/item_promotion?marketplace_id=...

    Returns the first VOLUME_DISCOUNT promotion if any, else None.
    """
    url = f"{MARKETING_BASE}/item_promotion"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers,
                         params={"marketplace_id": marketplace_id, "limit": 200},
                         timeout=30)
    except requests.RequestException as exc:
        print(f"    item_promotion GET failed: {exc}")
        return None
    if r.status_code != 200:
        print(f"    item_promotion GET HTTP {r.status_code}: {r.text[:240]}")
        return None
    try:
        data = r.json()
    except json.JSONDecodeError:
        return None
    for promo in (data.get("promotions") or []):
        if promo.get("promotionType") == "VOLUME_DISCOUNT":
            return promo
    return None


def _volume_drift(existing: dict, cfg: dict) -> list[str]:
    """Return human-readable drift descriptions between live promo and config."""
    drift: list[str] = []
    want = {t["min_quantity"]: round(t["discount_pct"] * 100, 2) for t in cfg["volume_discount"]["tiers"]}
    have_rules = existing.get("discountRules") or []
    have = {}
    for r in have_rules:
        try:
            mq = int(r.get("discountSpecification", {}).get("minQuantity", 0))
            pct = float(r.get("discountBenefit", {}).get("percentageOffOrder", 0))
            have[mq] = round(pct, 2)
        except (TypeError, ValueError):
            continue
    for mq, pct in want.items():
        if mq not in have:
            drift.append(f"missing tier: buy {mq} = {pct}%")
        elif abs(have[mq] - pct) > 0.01:
            drift.append(f"tier {mq}: live {have[mq]}% vs config {pct}%")
    for mq in have:
        if mq not in want:
            drift.append(f"extra live tier: buy {mq} = {have[mq]}%")
    if existing.get("promotionStatus") not in ("RUNNING", "SCHEDULED"):
        drift.append(f"status: {existing.get('promotionStatus')}")
    return drift


def ensure_volume_discount(token: str, cfg: dict, dry_run: bool) -> dict:
    """Idempotent: create the store-wide volume discount if missing; otherwise
    report drift (no auto-update — that requires PUT and is risky).
    """
    marketplace_id = cfg.get("marketplace_id", "EBAY_US")
    result = {
        "action":   "noop",
        "existing": None,
        "drift":    [],
        "created":  None,
        "error":    None,
    }
    existing = find_existing_volume_promotion(token, marketplace_id)
    if existing:
        result["existing"] = {
            "promotionId":     existing.get("promotionId"),
            "name":            existing.get("name"),
            "promotionStatus": existing.get("promotionStatus"),
            "discountRules":   existing.get("discountRules"),
        }
        result["drift"] = _volume_drift(existing, cfg)
        result["action"] = "drift_detected" if result["drift"] else "in_sync"
        return result

    # No existing promo — create one.
    if dry_run:
        result["action"] = "would_create"
        result["payload"] = _volume_discount_payload(cfg, marketplace_id)
        return result

    url = f"{MARKETING_BASE}/item_promotion"
    headers = {
        "Authorization":    f"Bearer {token}",
        "Content-Type":     "application/json",
        "Content-Language": "en-US",
    }
    payload = _volume_discount_payload(cfg, marketplace_id)
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
    except requests.RequestException as exc:
        result["error"] = str(exc)
        return result
    if r.status_code in (200, 201):
        try:
            result["created"] = r.json()
        except json.JSONDecodeError:
            result["created"] = {"raw": r.text}
        result["action"] = "created"
    else:
        result["error"] = f"HTTP {r.status_code}: {r.text[:400]}"
        result["action"] = "create_failed"
    return result


# --------------------------------------------------------------------------- #
# Idempotence: skip markdowns already in place                                #
# --------------------------------------------------------------------------- #

def existing_markdown_ids(token: str, marketplace_id: str) -> set[str]:
    """Return the set of listing IDs already covered by an active MARKDOWN_SALE."""
    url = f"{MARKETING_BASE}/item_price_markdown"
    headers = {"Authorization": f"Bearer {token}"}
    try:
        r = requests.get(url, headers=headers,
                         params={"marketplace_id": marketplace_id, "limit": 200},
                         timeout=30)
    except requests.RequestException as exc:
        print(f"    item_price_markdown GET failed: {exc}")
        return set()
    if r.status_code != 200:
        return set()
    try:
        data = r.json()
    except json.JSONDecodeError:
        return set()
    covered: set[str] = set()
    for promo in (data.get("promotions") or []):
        if promo.get("promotionStatus") not in ("RUNNING", "SCHEDULED"):
            continue
        for inv in (promo.get("selectedInventoryDiscounts") or []):
            for lid in (inv.get("inventoryCriterion", {}).get("listingIds") or []):
                covered.add(str(lid))
    return covered


# --------------------------------------------------------------------------- #
# HTML report                                                                  #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    try:
        return f"{float(n)*100:.1f}%"
    except (TypeError, ValueError):
        return "—"


def build_report(plan: dict, history: list[dict], cfg: dict) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    markdowns = plan.get("markdowns", [])
    by_decision: dict[str, list[dict]] = {"apply": [], "skip": [], "blocked": []}
    for d in markdowns:
        by_decision.setdefault(d["decision"], []).append(d)
    flagged = [d for d in markdowns if d.get("flag_for_review")]
    total_discount = sum(
        (d["current_price"] - d["target_price"]) for d in by_decision["apply"]
        if d.get("target_price") and d.get("current_price")
    )
    tier_counts = {"61-120d": 0, "121-180d": 0, "181-9999d": 0}
    for d in by_decision["apply"]:
        if d.get("tier") in tier_counts:
            tier_counts[d["tier"]] += 1

    vd = plan.get("volume_discount") or {}
    vd_action = vd.get("action", "unknown")
    vd_status_html = ""
    if vd_action == "in_sync":
        vd_status_html = "<span class='badge badge-ok'>In sync</span>"
    elif vd_action == "drift_detected":
        drift_lines = "".join(f"<li>{x}</li>" for x in vd.get("drift", []))
        vd_status_html = f"<span class='badge badge-warn'>Drift detected</span><ul class='drift'>{drift_lines}</ul>"
    elif vd_action == "would_create":
        vd_status_html = "<span class='badge badge-info'>Would create (dry run)</span>"
    elif vd_action == "created":
        vd_status_html = "<span class='badge badge-ok'>Created</span>"
    elif vd_action == "create_failed":
        vd_status_html = f"<span class='badge badge-err'>Create failed: {vd.get('error','')}</span>"
    elif vd_action == "skipped":
        vd_status_html = "<span class='badge badge-muted'>Skipped (disabled)</span>"
    else:
        vd_status_html = f"<span class='badge badge-muted'>{vd_action}</span>"

    vd_tiers = "".join(
        f"<li>Buy {t['min_quantity']}+ → save {t['discount_pct']*100:.0f}%</li>"
        for t in cfg["volume_discount"]["tiers"]
    )

    def _row(d: dict) -> str:
        delta_amt = (d.get("current_price") or 0) - (d.get("target_price") or 0)
        flag = "🚩" if d.get("flag_for_review") else ""
        reasons = "<br>".join(d.get("reasons", []) or [])
        return f"""
        <tr class='row-{d['decision']}'>
          <td class='item'>
            <a href='{d["url"]}' target='_blank' rel='noopener'>
              <span class='title'>{(d['title'] or '')[:90]}</span>
              <span class='item-id'>{d['item_id']}</span>
            </a>
          </td>
          <td class='num'>{d.get('age_days', '—')}d <small class='src'>{d.get('age_source','')}</small></td>
          <td class='band'>{d.get('tier') or '—'}</td>
          <td class='num'>{_fmt_money(d.get('current_price'))}</td>
          <td class='num target'>{_fmt_money(d.get('target_price'))}</td>
          <td class='num delta'>−{_fmt_money(delta_amt)}</td>
          <td class='num'>{_fmt_money(d.get('floor'))}</td>
          <td class='flag'>{flag}</td>
          <td class='reasons'>{reasons}</td>
          <td class='decision decision-{d['decision']}'>{d['decision'].upper()}</td>
        </tr>
        """

    def _section(title: str, items: list[dict]) -> str:
        if not items:
            return f"<h3>{title} <span class='count'>(0)</span></h3><p class='empty'>None.</p>"
        rows = "\n".join(_row(d) for d in items)
        return f"""
        <h3>{title} <span class='count'>({len(items)})</span></h3>
        <div class='tbl-wrap'>
          <table class='reprice-tbl'>
            <thead><tr>
              <th>Listing</th><th>Age</th><th>Band</th><th>Now</th><th>New</th>
              <th>Δ</th><th>Floor</th><th>Flag</th><th>Reasoning</th><th>Decision</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """

    recent = list(reversed(history))[:50]
    hist_rows = "\n".join(
        f"<tr><td>{h.get('applied_at','')}</td>"
        f"<td>{h.get('kind','')}</td>"
        f"<td><a href='{h.get('url','#')}' target='_blank'>{h.get('item_id','')}</a></td>"
        f"<td class='num'>{_fmt_money(h.get('from_price'))}</td>"
        f"<td class='num'>{_fmt_money(h.get('to_price'))}</td>"
        f"<td>{'OK' if h.get('ok') else 'FAIL: ' + str(h.get('error',''))[:120]}</td></tr>"
        for h in recent
    )
    history_block = (
        f"<div class='tbl-wrap'><table class='reprice-tbl'><thead><tr>"
        f"<th>Applied</th><th>Kind</th><th>Item</th><th>From</th><th>To</th><th>Result</th>"
        f"</tr></thead><tbody>{hist_rows}</tbody></table></div>"
        if recent else "<p class='empty'>No promotions applied yet.</p>"
    )

    flagged_block = (
        "<ul class='flagged'>" +
        "".join(
            f"<li><a href='{d['url']}' target='_blank'>{(d['title'] or '')[:90]}</a>"
            f" <code>{d['item_id']}</code> · {d.get('age_days','?')}d · "
            f"now {_fmt_money(d.get('current_price'))} → {_fmt_money(d.get('target_price'))}</li>"
            for d in flagged
        ) + "</ul>"
    ) if flagged else "<p class='empty'>Nothing flagged.</p>"

    body = f"""
<section class='hero'>
  <h1>Promotions Agent</h1>
  <p class='sub'>Last run: <code>{run_ts}</code> · Mode: <code>{plan.get('mode','dry-run')}</code></p>
  <div class='stat-grid'>
    <div class='stat'><div class='stat-n'>{len(by_decision['apply'])}</div><div class='stat-l'>markdowns to apply</div></div>
    <div class='stat'><div class='stat-n'>{tier_counts['61-120d']}</div><div class='stat-l'>tier 5%</div></div>
    <div class='stat'><div class='stat-n'>{tier_counts['121-180d']}</div><div class='stat-l'>tier 12%</div></div>
    <div class='stat'><div class='stat-n'>{tier_counts['181-9999d']}</div><div class='stat-l'>tier 22%</div></div>
    <div class='stat'><div class='stat-n'>{_fmt_money(total_discount)}</div><div class='stat-l'>total discount</div></div>
    <div class='stat'><div class='stat-n'>{len(flagged)}</div><div class='stat-l'>flagged for review</div></div>
  </div>
</section>

<section class='cfg'>
  <h3>Volume discount</h3>
  <p>{vd_status_html}</p>
  <ul class='cfg-list'>{vd_tiers}</ul>
  <p class='hint'>Volume discounts raise average order size 20–40% on a lot-style store. The Marketing API applies this store-wide as a single <code>VOLUME_DISCOUNT</code> item_promotion.</p>
</section>

<section class='cfg'>
  <h3>Markdown ladder</h3>
  <ul class='cfg-list'>
    {"".join(f"<li>{t['min_age_days']}–{t['max_age_days']}d → {t['pct']*100:.0f}%{' · flag' if t.get('flag_for_review') else ''}</li>" for t in cfg['markdown_tiers'])}
    <li>Floor: max($1.00, sold·0.75, price·0.55)</li>
    <li>Cap: {cfg['max_markdowns_per_run']}/run</li>
  </ul>
  <p class='hint'>Edit <code>promotions_config.json</code> to tune. Run: <code>python promotions_agent.py</code> (dry) or <code>--apply</code>.</p>
</section>

<section>
  <h3>🚩 Flagged for manual review</h3>
  {flagged_block}
</section>

{_section('🎯 Markdowns to apply', by_decision['apply'])}
{_section('⊝ Skipped', by_decision['skip'])}
{_section('⛔ Blocked', by_decision['blocked'])}

<section>
  <h3>Recent application history</h3>
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
  .cfg { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .cfg h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .cfg-list { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 6px 18px; }
  .cfg .hint { color: var(--text-muted); font-size: 13px; margin: 10px 0 0; }
  .badge { display: inline-block; padding: 3px 9px; border-radius: 999px; font-size: 12px; font-weight: 600; }
  .badge-ok { background: rgba(127,199,122,.15); color: var(--success); }
  .badge-warn { background: rgba(212,175,55,.15); color: var(--gold); }
  .badge-err { background: rgba(220,80,80,.15); color: var(--danger); }
  .badge-info { background: rgba(120,160,220,.15); color: var(--text); }
  .badge-muted { background: var(--surface); color: var(--text-muted); }
  .drift { margin: 8px 0 0 18px; color: var(--text-muted); }
  h3 .count { color: var(--text-muted); font-weight: 400; font-size: .7em; }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.reprice-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .reprice-tbl th, .reprice-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .reprice-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .reprice-tbl tr:hover td { background: var(--surface-2); }
  .reprice-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .reprice-tbl .target { color: var(--gold); font-weight: 600; }
  .reprice-tbl .delta { color: var(--danger); }
  .reprice-tbl .src { color: var(--text-dim); font-size: 10px; }
  .reprice-tbl .item .title { display: block; color: var(--text); }
  .reprice-tbl .item .item-id { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .reprice-tbl .item a { text-decoration: none; }
  .reprice-tbl .item a:hover .title { color: var(--gold); }
  .reprice-tbl .band { color: var(--text-muted); font-size: 12px; }
  .reprice-tbl .reasons { color: var(--text-muted); font-size: 12px; max-width: 320px; }
  .reprice-tbl .flag { font-size: 18px; }
  .decision { font-weight: 700; font-size: 11px; letter-spacing: .1em; }
  .decision-apply { color: var(--success); }
  .decision-skip { color: var(--text-muted); }
  .decision-blocked { color: var(--danger); }
  .row-apply { background: linear-gradient(to right, rgba(127,199,122,0.05), transparent); }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
  .flagged { list-style: none; padding: 0; margin: 8px 0; }
  .flagged li { padding: 8px 12px; border-bottom: 1px solid var(--border); }
  .flagged a { color: var(--text); }
  .flagged a:hover { color: var(--gold); }
  .flagged code { color: var(--text-dim); font-size: 11px; }
</style>
"""
    html = promote.html_shell("Promotions Agent · Harpua2001", body,
                              extra_head=extra_css, active_page="promotions.html")
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Nav registration                                                            #
# --------------------------------------------------------------------------- #

def ensure_nav_entry() -> None:
    """Append 'Promotions' to promote._NAV_ITEMS at runtime so the link
    appears in the rendered HTML shell. Does NOT modify promote.py on disk.
    """
    entry = ("promotions.html", "Promotions", False, "Insights")
    if entry not in promote._NAV_ITEMS:
        # Insert right after repricing.html for grouping
        items = list(promote._NAV_ITEMS)
        for idx, it in enumerate(items):
            if it[0] == "repricing.html":
                items.insert(idx + 1, entry)
                break
        else:
            items.append(entry)
        promote._NAV_ITEMS = items
        # _ADMIN_PAGES is a set; recompute
        promote._ADMIN_PAGES = {p for p, _, public, _ in items if not public}


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def _load_listings_from_snapshot() -> list[dict]:
    """Snapshot may be either:
       - a list[dict] (written by promote.build_site), OR
       - {"listings": [...], "market": {...}, "pricing": {...}, "sold": [...]}
         (written by repricing_agent).
    """
    if not LISTINGS_SNAPSHOT.exists():
        return []
    raw = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("listings") or []
    return []


def gather_inputs(use_cache: bool) -> tuple[dict, list[dict], list[dict]]:
    """Returns (ebay_cfg, listings, sold_history)."""
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    if use_cache:
        listings = _load_listings_from_snapshot()
        if listings:
            print(f"  Using cached snapshot ({len(listings)} listings)")
            sold = promote._load_sold_history()
            return ebay_cfg, listings, sold
        print("  No usable snapshot; falling through to live fetch...")
    print("  Getting eBay access token...")
    token = promote.get_access_token(ebay_cfg)
    print("  Fetching active listings...")
    listings = promote.fetch_listings(token, ebay_cfg)
    sold = promote._load_sold_history()
    return ebay_cfg, listings, sold


def run(args: argparse.Namespace) -> int:
    cfg = load_config()
    if not cfg.get("enabled", True):
        print("Promotions agent is disabled in promotions_config.json.")
        return 0

    ensure_nav_entry()

    if args.report_only:
        plan = json.loads(PLAN_PATH.read_text()) if PLAN_PATH.exists() else {}
        path = build_report(plan, load_history(), cfg)
        print(f"  Report: {path}")
        return 0

    ebay_cfg, listings, sold = gather_inputs(use_cache=args.no_fetch)
    print(f"  Loaded {len(listings)} active listings")

    # --- Listing age inference ----------------------------------------------- #
    ages_cache = load_listing_ages()
    if args.apply and not args.volume_only:
        # Only call GetItem when we need real ages to apply (avoids network on dry runs)
        try:
            trading_token = get_trading_token(ebay_cfg)
            ages_cache = fetch_listing_ages(trading_token, ebay_cfg,
                                            [l["item_id"] for l in listings], ages_cache)
        except Exception as exc:
            print(f"  Age fetch failed (will fall back to heuristic): {exc}")

    all_ids = [l["item_id"] for l in listings]

    # --- Markdown plan -------------------------------------------------------- #
    markdowns: list[dict] = []
    if not args.volume_only:
        for l in listings:
            age_days, src = age_for_listing(l, ages_cache, all_ids)
            sm = sold_median_for(l, sold)
            markdowns.append(plan_markdown(l, age_days, src, sm, cfg))

    # --- Volume-discount reconciliation -------------------------------------- #
    vd_result: dict = {"action": "skipped"}
    marketing_token: str | None = None
    if cfg["volume_discount"].get("enabled", True) and not args.markdowns_only:
        if args.apply:
            marketing_token = get_marketing_token(ebay_cfg)
            if marketing_token:
                vd_result = ensure_volume_discount(marketing_token, cfg, dry_run=False)
            else:
                vd_result = {"action": "create_failed",
                             "error": "could not obtain Marketing API token (check sell.marketing scope)"}
        else:
            # Dry run: best-effort GET to detect drift; if scope unavailable we just
            # emit "would_create" with the payload preview.
            try:
                marketing_token = get_marketing_token(ebay_cfg)
            except Exception as exc:
                marketing_token = None
                print(f"  Marketing token (read-only check) unavailable: {exc}")
            if marketing_token:
                vd_result = ensure_volume_discount(marketing_token, cfg, dry_run=True)
            else:
                vd_result = {
                    "action":  "would_create",
                    "payload": _volume_discount_payload(cfg, cfg.get("marketplace_id", "EBAY_US")),
                    "note":    "no Marketing API token available — payload preview only",
                }

    # --- Idempotence: skip listings that already have an active markdown ----- #
    already_covered: set[str] = set()
    if args.apply and not args.volume_only:
        if marketing_token is None:
            marketing_token = get_marketing_token(ebay_cfg)
        if marketing_token:
            already_covered = existing_markdown_ids(marketing_token, cfg.get("marketplace_id", "EBAY_US"))
            if already_covered:
                print(f"  Skipping {len(already_covered)} listing(s) with active markdowns already in place")
        for d in markdowns:
            if d["decision"] == "apply" and d["item_id"] in already_covered:
                d["decision"] = "skip"
                d["reasons"].append("already covered by an active item_price_markdown promotion")

    # --- Persist plan -------------------------------------------------------- #
    PLAN_PATH.parent.mkdir(exist_ok=True)
    plan_obj = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "mode":             "apply" if args.apply else "dry-run",
        "config":           cfg,
        "markdowns":        markdowns,
        "volume_discount":  vd_result,
    }
    PLAN_PATH.write_text(json.dumps(plan_obj, indent=2))

    # --- Summary ------------------------------------------------------------- #
    by = {"apply": 0, "skip": 0, "blocked": 0}
    tier_counts = {"61-120d": 0, "121-180d": 0, "181-9999d": 0}
    for d in markdowns:
        by[d["decision"]] = by.get(d["decision"], 0) + 1
        if d["decision"] == "apply" and d.get("tier") in tier_counts:
            tier_counts[d["tier"]] += 1
    print(f"\n  Markdown plan: {by['apply']} to apply · {by['skip']} skip · {by['blocked']} blocked")
    print(f"    tiers: 5%→{tier_counts['61-120d']} · 12%→{tier_counts['121-180d']} · 22%→{tier_counts['181-9999d']}")
    print(f"  Volume discount: {vd_result.get('action')}")
    if vd_result.get("drift"):
        for d in vd_result["drift"]:
            print(f"    drift: {d}")

    # --- Apply markdowns (if --apply) ---------------------------------------- #
    applied_entries: list[dict] = []
    if args.apply and not args.volume_only:
        if marketing_token is None:
            marketing_token = get_marketing_token(ebay_cfg)
        if not marketing_token:
            print("  Cannot apply markdowns — no Marketing API token.")
        else:
            to_apply = [d for d in markdowns if d["decision"] == "apply"]
            if args.item:
                to_apply = [d for d in to_apply if d["item_id"] == args.item]
            cap = cfg["max_markdowns_per_run"]
            if len(to_apply) > cap:
                print(f"  Capping run at {cap} of {len(to_apply)} eligible markdowns")
                to_apply = to_apply[:cap]
            print(f"\n  Applying {len(to_apply)} markdown(s) to eBay...")
            for d in to_apply:
                print(f"    → {d['item_id']}: ${d['current_price']:.2f} → ${d['target_price']:.2f} ({d['tier']})")
                res = apply_markdown(marketing_token, d, cfg)
                applied_entries.append({
                    "applied_at":  datetime.now(timezone.utc).isoformat(),
                    "kind":        "markdown",
                    "item_id":     d["item_id"],
                    "title":       d["title"],
                    "from_price":  d["current_price"],
                    "to_price":    d["target_price"],
                    "tier":        d["tier"],
                    "ok":          res["ok"],
                    "http":        res["http"],
                    "error":       res.get("error"),
                    "url":         d.get("url"),
                })
                time.sleep(0.5)
        # Add the volume discount action to history if it created anything
        if vd_result.get("action") == "created":
            applied_entries.append({
                "applied_at":  datetime.now(timezone.utc).isoformat(),
                "kind":        "volume_discount",
                "item_id":     "(store-wide)",
                "title":       cfg["volume_discount"].get("name", "Volume Discount"),
                "from_price":  None,
                "to_price":    None,
                "ok":          True,
                "http":        201,
                "error":       None,
                "url":         "",
            })
        append_history(applied_entries)
        ok_count = sum(1 for e in applied_entries if e["ok"])
        print(f"\n  Result: {ok_count}/{len(applied_entries)} applied successfully.")
    else:
        print("\n  Dry run only. Re-run with --apply to push changes.")

    report = build_report(plan_obj, load_history(), cfg)
    print(f"  Report: {report}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Stale-inventory markdown ladder + volume discount agent.")
    ap.add_argument("--apply", action="store_true", help="Actually push changes to eBay (default: dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="Reuse cached listings snapshot")
    ap.add_argument("--item", help="Limit markdown apply to a single item_id")
    ap.add_argument("--report-only", action="store_true", help="Rebuild docs/promotions.html only")
    ap.add_argument("--markdowns-only", action="store_true", help="Skip volume-discount setup")
    ap.add_argument("--volume-only", action="store_true", help="Only reconcile volume discount; skip markdowns")
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
