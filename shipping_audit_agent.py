"""
shipping_audit_agent.py — read-only shipping-service audit for Harpua2001 listings.

The invariant: every active listing's shipping service/cost MUST match the
house default set in post_from_scan.py:

    SHIPPING_SERVICE          = "US_eBayStandardEnvelope"   ($1.32)
    SHIPPING_SERVICE_COST     = "1.32"
    LOT_SHIPPING_SERVICE      = "US_eBayStandardEnvelope"   ($1.32)
    LOT_SHIPPING_SERVICE_COST = "1.32"

This invariant exists because of a real incident (2026-08-02): several one-off
posting scripts hardcoded ShippingService=USPSFirstClass at a discounted
$0.99-1.29 buyer-facing rate. Real USPS First Class postage runs $4.50+, so
every sale under that service silently lost money on shipping. It affected
79 listings before a manual audit caught it. There was, and until this agent
existed still was, ZERO automated daily check for this class of bug.

This agent is the automated check. It is strictly report-only — no --apply,
no ReviseItem, no eBay writes of any kind. A human (or a future dedicated
fix-up agent) corrects any mismatch it finds.

How it works:
  1. Load output/listings_snapshot.json (tolerates both the bare-list shape
     and the {"listings": [...]} shape — the snapshot does NOT carry shipping
     fields at all, so shipping details must come from a live Trading API
     GetItem call, same as photo_audit_agent.py does for PictureURL/WatchCount).
  2. GetItem's <ShippingDetails><ShippingServiceOptions> block gives us the
     live ShippingService + ShippingServiceCost per item.
  3. Per-item_id results are cached (output/shipping_audit_cache.json) with a
     TTL, same pattern as specifics_agent.py's GetItem cache — a shipping
     service on an existing listing essentially never changes on its own, so
     re-checking a listing we already verified compliant every single day is
     wasted Trading API quota. Only uncached / stale / new item_ids trigger a
     live fetch on a given run.
  4. Any listing whose live service != house default, or whose cost differs
     by more than a cent, is flagged as a mismatch with found vs. expected.

Usage:
    python3 shipping_audit_agent.py              # audit (uses cache, fetches new/stale)
    python3 shipping_audit_agent.py --no-fetch    # cache-only, no Trading API calls
    python3 shipping_audit_agent.py --report-only # rebuild docs/shipping_audit.html from last plan

Artifacts:
    shipping_audit_config.json          tunable thresholds (created on 1st run)
    output/shipping_audit_cache.json    per-item_id GetItem cache (TTL-gated)
    output/shipping_audit_plan.json     latest audit result (every listing + mismatches)
    docs/shipping_audit.html            human-readable report
"""

from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Gary Carter'
AGENT_ROLE = 'Shipping Audit'

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

import promote
import post_from_scan as pfs

REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "shipping_audit_config.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
CACHE_PATH         = REPO_ROOT / "output" / "shipping_audit_cache.json"
PLAN_PATH          = REPO_ROOT / "output" / "shipping_audit_plan.json"
REPORT_PATH        = promote.OUTPUT_DIR / "shipping_audit.html"

EBAY_NS = "urn:ebay:apis:eBLBaseComponents"

# House defaults — single source of truth is post_from_scan.py. We import the
# constants (rather than re-hardcoding them here) so this agent can never drift
# from the values that actually get used when new listings are posted.
HOUSE_SINGLE_SERVICE = pfs.SHIPPING_SERVICE
HOUSE_SINGLE_COST     = float(pfs.SHIPPING_SERVICE_COST)
HOUSE_LOT_SERVICE     = pfs.LOT_SHIPPING_SERVICE
HOUSE_LOT_COST        = float(pfs.LOT_SHIPPING_SERVICE_COST)

# Non-card items with a DELIBERATE non-envelope shipping setup. These must
# never be "fixed" back to the card-envelope default -- a rigid/heavy item on
# US_eBayStandardEnvelope would be an undeliverable listing, the exact inverse
# of the bug this agent exists to catch.
SHIPPING_EXEMPT_ITEM_IDS = {
    "307125889435",  # Gorham sterling souvenir spoon (Easton PA) -- free
                     # USPSFirstClass/Ground Advantage, postage in price (2026-08-14)
    "307127235915",  # Watson DC Capitol sterling souvenir spoon -- same setup
    "307127251788",  # Weisgerber 1926 Sesquicentennial sterling spoon -- same setup
    "307141227697",  # Ray Lewis Ravens jersey -- free Ground Advantage (2026-08-22)
    "307141228251",  # Deion Sanders Cowboys jersey -- same setup
    "307141228329",  # Marion Barber Cowboys jersey -- same setup
    "307150460802",  # Saquon Electro Lights -- free Ground Advantage (2026-08-28)
    "307150460817",  # Myles Garrett Electro Lights -- same setup
}

DEFAULT_CONFIG: dict = {
    "cache_ttl_days":              7,      # re-check a compliant listing at most weekly
    "cost_tolerance_usd":          0.01,   # ignore sub-cent float noise
    "max_trading_calls_per_sec":   2.0,    # Trading API GetItem pacing
    "max_listings_to_audit":       2000,   # safety valve, well above current store size
}


# --------------------------------------------------------------------------- #
# Config + snapshot + cache I/O                                               #
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


def _load_listings() -> list[dict]:
    """Tolerate both snapshot shapes used in this repo:
       - bare list (current shape)
       - dict with a 'listings' key (repricing-agent shape)
    """
    if not LISTINGS_SNAPSHOT.exists():
        raise FileNotFoundError(
            f"Missing {LISTINGS_SNAPSHOT}. Run promote.py or repricing_agent.py first."
        )
    data = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "listings" in data:
        return data["listings"]
    raise ValueError(f"Unrecognized listings_snapshot.json shape: {type(data)}")


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        return json.loads(CACHE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_cache(cache: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, indent=2))


def expected_for(listing: dict) -> tuple[str, float]:
    """Lot listings and single-card listings both currently point at the same
    house default in post_from_scan.py, but they're tracked as separate
    constants there (SHIPPING_SERVICE vs LOT_SHIPPING_SERVICE) in case a lot-
    specific rate is introduced later. We mirror that split here rather than
    collapsing to one constant, so this agent keeps working correctly if the
    two ever diverge.
    """
    category = str(listing.get("category") or "")
    title = str(listing.get("title") or "")
    is_lot = "lot" in category.lower() or "lot" in title.lower()
    if is_lot:
        return HOUSE_LOT_SERVICE, HOUSE_LOT_COST
    return HOUSE_SINGLE_SERVICE, HOUSE_SINGLE_COST


# --------------------------------------------------------------------------- #
# eBay Trading API: GetItem → ShippingDetails                                 #
# --------------------------------------------------------------------------- #

def _ebay_headers(call_name: str, cfg: dict) -> dict:
    return {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }


def get_item_shipping(item_id: str, token: str, ebay_cfg: dict) -> dict | None:
    """Trading API GetItem — returns live ShippingService + ShippingServiceCost.

    Returns None on any network/parse/API failure (caller falls back to
    listing-only info rather than crashing the whole audit run).
    """
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <ItemID>{item_id}</ItemID>
  <DetailLevel>ReturnAll</DetailLevel>
</GetItemRequest>"""
    try:
        r = requests.post("https://api.ebay.com/ws/api.dll",
                          headers=_ebay_headers("GetItem", ebay_cfg),
                          data=xml_body.encode(), timeout=30)
    except requests.RequestException as e:
        print(f"    GetItem network error for {item_id}: {e}")
        return None
    if r.status_code != 200:
        print(f"    GetItem HTTP {r.status_code} for {item_id}")
        return None
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError as e:
        print(f"    GetItem parse error for {item_id}: {e}")
        return None

    ack = root.findtext(f".//{{{EBAY_NS}}}Ack", "")
    if ack not in ("Success", "Warning"):
        msg_el = root.find(f".//{{{EBAY_NS}}}Errors/{{{EBAY_NS}}}ShortMessage")
        msg = msg_el.text if msg_el is not None else "unknown error"
        print(f"    GetItem failed {item_id}: {msg}")
        return None

    opt = root.find(f".//{{{EBAY_NS}}}ShippingDetails/{{{EBAY_NS}}}ShippingServiceOptions")
    service = (opt.findtext(f"{{{EBAY_NS}}}ShippingService", "") if opt is not None else "") or None
    cost_txt = (opt.findtext(f"{{{EBAY_NS}}}ShippingServiceCost", "") if opt is not None else "")
    try:
        cost = float(cost_txt) if cost_txt else None
    except ValueError:
        cost = None

    return {
        "item_id":    item_id,
        "service":    service,
        "cost":       cost,
        "fetched_at": int(time.time()),
        "ok":         True,
    }


# --------------------------------------------------------------------------- #
# Auditing                                                                    #
# --------------------------------------------------------------------------- #

def audit_listing(listing: dict, ship: dict, cfg: dict) -> dict:
    """Compare one listing's live shipping detail to the house default it
    should be using. `ship` may be None if we never got live data at all."""
    item_id = str(listing.get("item_id"))
    exp_service, exp_cost = expected_for(listing)

    found_service = ship.get("service") if ship else None
    found_cost    = ship.get("cost") if ship else None
    data_missing  = ship is None or (found_service is None and found_cost is None)

    if item_id in SHIPPING_EXEMPT_ITEM_IDS:
        # Deliberate non-card shipping setup -- report as compliant as-is.
        exp_service, exp_cost = found_service, (found_cost if found_cost is not None else exp_cost)

    service_mismatch = (not data_missing) and found_service != exp_service
    cost_mismatch = (
        not data_missing
        and found_cost is not None
        and abs(found_cost - exp_cost) > cfg["cost_tolerance_usd"]
    )

    if service_mismatch and cost_mismatch:
        mismatch_type = "service+cost"
    elif service_mismatch:
        mismatch_type = "service"
    elif cost_mismatch:
        mismatch_type = "cost"
    elif data_missing:
        mismatch_type = "no_data"
    else:
        mismatch_type = None

    return {
        "item_id":         item_id,
        "title":           listing.get("title"),
        "url":             listing.get("url"),
        "category":        listing.get("category"),
        "price":           listing.get("price"),
        "expected_service": exp_service,
        "expected_cost":    exp_cost,
        "found_service":    found_service,
        "found_cost":       found_cost,
        "mismatch_type":    mismatch_type,
        "fetched_at":       ship.get("fetched_at") if ship else None,
    }


def audit_all(listings: list[dict], cache: dict, cfg: dict, token: str | None,
              ebay_cfg: dict, use_cache_only: bool = False) -> list[dict]:
    ttl_seconds = cfg["cache_ttl_days"] * 24 * 3600
    now = int(time.time())
    min_interval = 1.0 / cfg["max_trading_calls_per_sec"] if cfg["max_trading_calls_per_sec"] > 0 else 0
    last_call = 0.0

    results: list[dict] = []
    for i, l in enumerate(listings, 1):
        item_id = str(l.get("item_id"))
        if not item_id or item_id == "None":
            continue

        cached = cache.get(item_id)
        is_fresh = cached and (now - cached.get("fetched_at", 0)) < ttl_seconds and cached.get("ok")

        if is_fresh:
            ship = cached
        elif use_cache_only or not token:
            ship = cached  # possibly stale, possibly None — best we can do offline
        else:
            gap = time.monotonic() - last_call
            if min_interval and gap < min_interval:
                time.sleep(min_interval - gap)
            print(f"  [{i}/{len(listings)}] GetItem {item_id} ...")
            ship = get_item_shipping(item_id, token, ebay_cfg)
            last_call = time.monotonic()
            if ship is not None:
                cache[item_id] = ship
                if i % 20 == 0:
                    save_cache(cache)  # persist incrementally — GetItem is expensive

        results.append(audit_listing(l, ship, cfg))

    save_cache(cache)
    return results


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Entry point                                                                 #
# --------------------------------------------------------------------------- #

def main() -> int:
    print(f'  {AGENT_NAME} ({AGENT_ROLE}) reporting in.')
    ap = argparse.ArgumentParser(description="Read-only shipping-service audit for Harpua2001.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Cache-only — skip all Trading API GetItem calls.")
    ap.add_argument("--report-only", action="store_true",
                    help="Rebuild docs/shipping_audit.html from output/shipping_audit_plan.json.")
    args = ap.parse_args()

    cfg = load_config()

    if args.report_only:
        if not PLAN_PATH.exists():
            print(f"  No cached plan at {PLAN_PATH} — run without --report-only first.")
            return 1
        json.loads(PLAN_PATH.read_text())
        print(f"  Plan already at {PLAN_PATH} (HTML report generation removed).")
        return 0

    listings = _load_listings()
    cap = cfg["max_listings_to_audit"]
    if len(listings) > cap:
        print(f"  Capping audit at {cap} of {len(listings)} listings")
        listings = listings[:cap]
    print(f"  Loaded {len(listings)} active listings from snapshot")

    cache = load_cache()

    ttl_seconds = cfg["cache_ttl_days"] * 24 * 3600
    now = int(time.time())
    need_fetch = any(
        not cache.get(str(l.get("item_id")))
        or (now - cache[str(l.get("item_id"))].get("fetched_at", 0)) >= ttl_seconds
        or not cache[str(l.get("item_id"))].get("ok")
        for l in listings if l.get("item_id")
    )

    token = None
    if not args.no_fetch and need_fetch:
        ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
        try:
            print("  Getting eBay access token...")
            token = promote.get_access_token(ebay_cfg)
        except Exception as e:
            print(f"  Could not get eBay token ({e}); falling back to cache-only mode")
            token = None
    else:
        ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    t0 = time.monotonic()
    results = audit_all(listings, cache, cfg, token, ebay_cfg,
                        use_cache_only=(args.no_fetch or token is None))
    elapsed = time.monotonic() - t0

    payload = {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "house_default": {"service": HOUSE_SINGLE_SERVICE, "cost": HOUSE_SINGLE_COST},
        "config":        cfg,
        "results":       results,
    }
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(payload, indent=2))

    mismatches = [r for r in results if r["mismatch_type"] and r["mismatch_type"] != "no_data"]
    no_data = [r for r in results if r["mismatch_type"] == "no_data"]

    print(f"\n  Audited {len(results)} listings in {elapsed:.1f}s.")
    if mismatches:
        print(f"  MISMATCHES: {len(mismatches)} listing(s) not on the house shipping default.")
        for r in mismatches[:15]:
            print(f"    {r['item_id']}  service={r['found_service']!r} (want {r['expected_service']!r})  "
                  f"cost={r['found_cost']}  (want {r['expected_cost']})  {(r['title'] or '')[:60]}")
    else:
        print(f"  Clean: 0 shipping mismatches across {len(results)} audited listings.")
    if no_data:
        print(f"  {len(no_data)} listing(s) had no shipping data (GetItem failure or no ShippingServiceOptions).")

    print(f"\n  Plan:   {PLAN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
