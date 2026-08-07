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
from datetime import datetime, timedelta, timezone
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
    "promotion_duration_days":  30,
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
                       cache: dict, max_fetch: int = 40) -> dict:
    """For each item_id missing from cache, call GetItem to fetch StartTime.

    Trading API GetItem returns ListingDetails/StartTime in ISO format. We
    cache aggressively (start times don't change) and skip already-known ones.

    Bounded by max_fetch: GetItem is a serial per-item Trading call, so fetching
    hundreds at once both hangs the run and burns the daily call quota (eBay 518).
    Start times are immutable, so the cache fills in over successive runs; any
    items left unfetched this run fall back to the heuristic age (same basis the
    dry-run uses). Pass max_fetch=0 to skip the network entirely.
    """
    missing = [iid for iid in item_ids if iid not in cache or not cache[iid].get("start_time")]
    if not missing or max_fetch <= 0:
        if missing:
            print(f"  {len(missing)} listing(s) missing start time — using heuristic age (cache fills over future runs)")
        return cache
    if len(missing) > max_fetch:
        print(f"  {len(missing)} missing start times; fetching {max_fetch} this run (rest use heuristic age, cache fills over future runs)")
        missing = missing[:max_fetch]
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
    # eBay applies the markdown as an INTEGER percentageOffItem. Round the
    # discount DOWN (truncate) so the price eBay actually applies never dips
    # below the floor-protected target_price. Record the real applied price so
    # the report/history match what the buyer sees (the prior code sent the raw
    # tier pct and logged target_price, so it silently sold below the floor).
    pct_off_int = int((current - target) / current * 100)  # truncate = floor for positive
    # eBay's item_price_markdown (MARKDOWN_SALE) rejects percentageOffItem
    # below 5 (errorId 38248, allowedValues 5-75) — a floor-protected discount
    # that truncates to 1-4% isn't a "small markdown", it's an API call eBay
    # will always reject, so skip it here instead of failing on every run.
    if pct_off_int < 5:
        decision["decision"] = "skip"
        decision["reasons"].append(
            f"discount {(current - target) / current * 100:.1f}% rounds to {pct_off_int}%, "
            "below eBay's 5% minimum for a markdown promotion — not representable "
            "without breaching the floor"
        )
        return decision
    applied_price = round(current * (1 - pct_off_int / 100.0), 2)
    decision["markdown_pct"]  = pct_off_int
    decision["applied_price"] = applied_price
    decision["decision"]      = "apply"
    decision["reasons"].append(
        f"age {age_days}d ({age_source}) → tier {decision['tier']} @ {tier['pct']*100:.0f}% "
        f"→ {pct_off_int}% off = ${applied_price:.2f} (target ${target:.2f}, floor ${floor:.2f})"
    )
    if decision["flag_for_review"]:
        decision["reasons"].append("flagged for manual review — consider relist/delist")
    return decision


# --------------------------------------------------------------------------- #
# eBay Marketing API: Item Price Markdown                                     #
# --------------------------------------------------------------------------- #

def _markdown_payload(decision: dict, cfg: dict, marketplace_id: str, image_url: str = "") -> dict:
    """Build the POST body for /sell/marketing/v1/item_price_markdown.

    One promotion per listing is the simplest mapping. Discount is supplied as
    an absolute marked-down `priceDiscount.value`. eBay paints the
    strikethrough automatically.
    """
    now = datetime.now(timezone.utc)
    duration_days = int(cfg.get("promotion_duration_days", 30))
    start_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = (now + timedelta(days=duration_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # eBay MARKDOWN_SALE requires: a short description (<=50 chars), a hosted
    # promotionImageUrl (the listing's own EPS image works), and the discount as
    # an INTEGER percentageOffItem (amountOffItem rejects decimals). Use the
    # floor-protected markdown_pct computed in decide() (rounded DOWN so the
    # applied price never breaches the floor); fall back to deriving it from the
    # current/target prices if absent.
    pct_int = decision.get("markdown_pct")
    if pct_int is None:
        cur = float(decision.get("current_price") or 0)
        tgt = float(decision.get("target_price") or 0)
        pct_int = int((cur - tgt) / cur * 100) if cur > 0 and tgt > 0 else 0
    pct_int = max(0, int(pct_int))
    return {
        "name":                  f"MD-{decision['item_id']}"[:50],
        "description":           "Markdown sale",
        "promotionImageUrl":     image_url or "",
        "marketplaceId":         marketplace_id,
        "promotionStatus":       cfg["promotion_status_when_creating"],
        "startDate":             start_iso,
        "endDate":               end_iso,
        "applyMarkdownDiscount": True,
        "promotionType":         "MARKDOWN_SALE",
        "selectedInventoryDiscounts": [{
            "discountBenefit": {"percentageOffItem": str(pct_int)},
            "ruleSelectionType": "INVENTORY_BY_VALUE",
            "inventoryCriterion": {
                "inventoryCriterionType": "INVENTORY_BY_VALUE",
                "listingIds": [decision["item_id"]],
            },
        }],
    }


def apply_markdown(token: str, decision: dict, cfg: dict, image_url: str = "") -> dict:
    """Create an item_price_markdown promotion for one listing."""
    url = f"{MARKETING_BASE}/item_price_markdown"
    headers = {
        "Authorization":  f"Bearer {token}",
        "Content-Type":   "application/json",
        "Content-Language": "en-US",
    }
    payload = _markdown_payload(decision, cfg, cfg.get("marketplace_id", "EBAY_US"), image_url)
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
    if ok:
        err = None
    elif isinstance(data, dict) and data.get("errors"):
        err = json.dumps(data["errors"])[:600]
    else:
        err = (body or "")[:600]
    return {
        "ok":     ok,
        "http":   r.status_code,
        "data":   data,
        "error":  err,
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
    duration_days = int(cfg.get("promotion_duration_days", 30))
    start_iso = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_iso = (now + timedelta(days=duration_days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # VOLUME_DISCOUNT rules: eBay requires a baseline rule (minQuantity 1, 0% off,
    # ruleOrder 1) followed by the real tiers, and EVERY rule must carry a
    # ruleOrder. Only percentageOffOrder + minQuantity are valid for volume
    # pricing. Omitting ruleOrder / the baseline makes eBay report
    # "discountBenefit is missing" (errorId 38238).
    discount_rules = [{
        "discountBenefit": {"percentageOffOrder": "0"},
        "discountSpecification": {"minQuantity": 1},
        "ruleOrder": 1,
    }]
    for i, tier in enumerate(vd["tiers"], start=2):
        discount_rules.append({
            "discountBenefit": {
                "percentageOffOrder": f"{tier['discount_pct']*100:g}",
            },
            "discountSpecification": {
                "minQuantity": int(tier["min_quantity"]),
            },
            "ruleOrder": i,
        })
    return {
        "name":                  vd.get("name", "Store Volume Discount"),
        "description":           "Buy more, save more — store-wide volume discount.",
        "marketplaceId":         marketplace_id,
        "promotionStatus":       cfg["promotion_status_when_creating"],
        "promotionType":         "VOLUME_DISCOUNT",
        "startDate":             start_iso,
        "endDate":               end_iso,
        "applyDiscountToSingleItemOnly": False,
        "inventoryCriterion": {
            "inventoryCriterionType": "INVENTORY_ANY",
        },
        "discountRules":         discount_rules,
    }


def find_existing_volume_promotion(token: str, marketplace_id: str) -> dict | None:
    """GET /sell/marketing/v1/item_promotion?marketplace_id=...

    Returns the first VOLUME_DISCOUNT promotion if any, else None.
    """
    # NOTE: the LIST endpoint is /promotion (getPromotions). /item_promotion is
    # only for create (POST) and get-by-id (GET /item_promotion/{id}); calling it
    # for a list query returns HTTP 400.
    url = f"{MARKETING_BASE}/promotion"
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
        if mq == 1:
            continue  # baseline rule (buy 1 = 0%) is required by eBay, not drift
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
        print("  --report-only: HTML report generation has been removed; nothing to rebuild.")
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
    tier_pcts = {f"{t['min_age_days']}-{t['max_age_days']}d": t["pct"] for t in cfg["markdown_tiers"]}
    print(f"\n  Markdown plan: {by['apply']} to apply · {by['skip']} skip · {by['blocked']} blocked")
    print("    tiers: " + " · ".join(
        f"{tier_pcts.get(k, 0) * 100:.0f}%→{v}" for k, v in tier_counts.items()
    ))
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
            # MARKDOWN_SALE requires a hosted promotionImageUrl — use each
            # listing's own EPS image (i.ebayimg.com s-l500 works fine).
            image_by_id = {
                str(l.get("item_id")): (l.get("pic") or l.get("galleryURL") or l.get("imageUrl") or "")
                for l in listings
            }
            print(f"\n  Applying {len(to_apply)} markdown(s) to eBay...")
            for d in to_apply:
                # applied_price is the real eBay result (floor-safe integer pct);
                # target_price is the ideal. Report/record the applied price.
                applied = d.get("applied_price", d["target_price"])
                print(f"    → {d['item_id']}: ${d['current_price']:.2f} → ${applied:.2f} ({d['tier']})")
                res = apply_markdown(marketing_token, d, cfg, image_by_id.get(str(d["item_id"]), ""))
                # 38272 = auction-style listing, not eligible for markdown — skip quietly.
                err_str = json.dumps(res.get("error") or "")
                if not res["ok"] and "38272" in err_str:
                    res["error"] = "skipped: auction-style listing (not markdown-eligible)"
                applied_entries.append({
                    "applied_at":  datetime.now(timezone.utc).isoformat(),
                    "kind":        "markdown",
                    "item_id":     d["item_id"],
                    "title":       d["title"],
                    "from_price":  d["current_price"],
                    "to_price":    applied,
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
