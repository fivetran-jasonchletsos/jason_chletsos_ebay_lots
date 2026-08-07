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

# --- Roster ---
AGENT_NAME = 'Patrick Ewing'
AGENT_ROLE = 'Watchers Offer'

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
    "offer_duration_days":    4,
    "allow_counter_offer":    False,  # eBay rejects true on this endpoint
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
    """Return item_ids that received a SUCCESSFUL offer within cooldown window.

    Failed offers do not count — they didn't reach the buyer, so the listing
    is not actually in cooldown. Skipping h.get("ok") == False here was the
    bug that locked out 12 of 15 eligible items in the 2026-05-20 run.
    """
    if not history:
        return set()
    cutoff = datetime.now(timezone.utc) - timedelta(days=cooldown_days)
    recent: set[str] = set()
    for h in history:
        if not h.get("ok"):
            continue
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
    Refresh-token grant scoped to sell.negotiation — the only scope the
    send_offer_to_interested_buyers endpoint actually requires. The previous
    version asked for six scopes at once and would 400 if ANY of them was
    missing from the refresh token's allow-list. Falls back to
    promote.get_access_token if negotiation isn't authorized either.
    """
    import base64
    credentials = base64.b64encode(
        f"{cfg['client_id']}:{cfg['client_secret']}".encode()
    ).decode()
    # eBay's Negotiation API send_offer_to_interested_buyers needs the
    # sell.marketing scope (granted on this keyset). HOWEVER, even with
    # a valid sell.marketing token the endpoint returns HTTP 403
    # "Access denied" — because the Negotiation feature itself is a
    # license-gated capability on developer.ebay.com that this app
    # has not been granted. The OAuth Scopes page notes: "Some
    # Sandbox capabilities and OAuth scopes are only available with
    # additional licenses or contracts in Production."
    #
    # API docs confirm the Negotiation API requires sell.inventory scope,
    # not sell.marketing. sell.inventory is already granted on this keyset.
    scopes = " ".join([
        "https://api.ebay.com/oauth/api_scope",
        "https://api.ebay.com/oauth/api_scope/sell.inventory",
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

NEGOTIATION_URL       = "https://api.ebay.com/sell/negotiation/v1/send_offer_to_interested_buyers"
FIND_ELIGIBLE_URL     = "https://api.ebay.com/sell/negotiation/v1/find_eligible_items"


def fetch_eligible_listing_ids(token: str) -> set[str]:
    """Call findEligibleItems to get eBay-confirmed eligible listing IDs."""
    eligible = set()
    offset = 0
    while True:
        try:
            resp = requests.get(
                FIND_ELIGIBLE_URL,
                headers={
                    "Authorization":           f"Bearer {token}",
                    "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
                },
                params={"limit": "200", "offset": str(offset)},
                timeout=15,
            )
            if resp.status_code == 204:  # no eligible items
                break
            if resp.status_code != 200:
                print(f"  WARNING: findEligibleItems HTTP {resp.status_code}: {resp.text[:200]}")
                break
            data = resp.json()
            items = data.get("eligibleItems") or []
            for item in items:
                eligible.add(str(item.get("listingId", "")))
            total = data.get("total", 0)
            offset += len(items)
            if offset >= total or not items:
                break
        except Exception as exc:
            print(f"  WARNING: findEligibleItems request failed: {exc}")
            break
    return eligible


def send_offer(item_id: str, discount_pct_int: int, message: str,
               duration_days: int, allow_counter: bool, token: str) -> dict:
    """POST a single send_offer_to_interested_buyers request."""
    body = {
        "offeredItems": [{
            "listingId":          item_id,
            "quantity":           1,
            "discountPercentage": str(discount_pct_int),
        }],
        # eBay's sendOfferToInterestedBuyers rejects allowCounterOffer=true with
        # HTTP 400 "Invalid value for allowCounterOffer" — must always be False.
        "allowCounterOffer":   False,
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

    # Cross-reference with eBay's findEligibleItems — only send to listings
    # that eBay confirms have interested buyers (watchers alone isn't enough).
    print("  Checking findEligibleItems for eBay-confirmed eligible listings...")
    eligible_ids = fetch_eligible_listing_ids(token)
    print(f"  eBay reports {len(eligible_ids)} listing(s) with eligible buyers.")

    to_send = [d for d in plan if d["decision"] == "apply"
               and str(d["item_id"]) in eligible_ids]
    if not to_send:
        print("  No listings overlap between watcher plan and eBay eligible set.")
        return []
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
        if not res["ok"]:
            print(f"    FAILED [http {res['http']}] {str(res.get('error'))[:200]}")
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
    print(f"  Patrick Ewing (Watchers Offer) reporting in.")
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
        print("  --report-only is a no-op: the docs/watchers.html report was retired.")
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

    return 0


if __name__ == "__main__":
    sys.exit(main())
