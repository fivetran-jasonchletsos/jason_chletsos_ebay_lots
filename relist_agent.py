"""relist_agent.py — find unsold ended auctions and relist them as Fixed Price.

Pulls UnsoldList via Trading API GetMyeBaySelling, suggests a Fixed-Price
relist price, and (with --apply) calls RelistFixedPriceItem — the Trading
API call that takes a previous auction's ItemID and relists it as a
Fixed-Price item, preserving photos, store category, specifics, condition,
shipping and returns. Default is dry-run. Renders docs/relist.html.

Usage:
    python3 relist_agent.py                # dry run (default)
    python3 relist_agent.py --apply        # actually call RelistFixedPriceItem
    python3 relist_agent.py --days 30      # widen lookback (1–60)
    python3 relist_agent.py --item 12345   # single item only
"""

from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Mookie Wilson'
AGENT_ROLE = 'Relist'

import argparse
import json
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT    = Path(__file__).parent
OUTPUT_DIR   = REPO_ROOT / "output"
PLAN_PATH    = OUTPUT_DIR / "relist_plan.json"
HISTORY_PATH = OUTPUT_DIR / "relist_history.json"
REPORT_PATH  = promote.OUTPUT_DIR / "relist.html"

TRADING_URL  = "https://api.ebay.com/ws/api.dll"
EBAY_NS      = "urn:ebay:apis:eBLBaseComponents"
NS           = "{" + EBAY_NS + "}"
COMPAT       = "967"
SITE_ID      = "0"

MAX_RETRIES, BACKOFF_BASE_SEC, PACE_SEC = 3, 1.5, 0.4

def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))

def _append_history(entries: list[dict]) -> None:
    if not entries:
        return
    h = _read_json(HISTORY_PATH, [])
    h = h if isinstance(h, list) else []
    h.extend(entries)
    _write_json(HISTORY_PATH, h)

def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _trading_headers(call_name: str, ebay_cfg: dict) -> dict[str, str]:
    return {
        "X-EBAY-API-SITEID":              SITE_ID,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            ebay_cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME":            ebay_cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME":           ebay_cfg.get("client_secret", ""),
        "Content-Type":                   "text/xml",
    }

def _trading_post(call_name: str, xml_body: str, ebay_cfg: dict) -> ET.Element:
    headers = _trading_headers(call_name, ebay_cfg)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(TRADING_URL, headers=headers,
                              data=xml_body.encode("utf-8"), timeout=30)
            if 500 <= r.status_code < 600:
                raise RuntimeError(f"HTTP {r.status_code}")
            return ET.fromstring(r.text)
        except Exception as exc:
            last_err = exc
            sleep_s = BACKOFF_BASE_SEC * (2 ** attempt)
            print(f"  [{call_name}] attempt {attempt+1} failed: {exc} — "
                  f"sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"{call_name} failed after {MAX_RETRIES} retries: {last_err}")

def _to_float(s: str) -> float:
    try:
        return float(s) if s else 0.0
    except (TypeError, ValueError):
        return 0.0

def fetch_ended_unsold(token: str, ebay_cfg: dict, days_back: int = 14) -> list[dict]:
    """Fetch ended auctions that did not sell in the last `days_back` days
    via Trading API GetMyeBaySelling with UnsoldList.Include=true. Returns
    dicts with item_id, title, end_date, original_price, store_category,
    condition, photos[], specifics, listing_type."""
    days_back = max(1, min(int(days_back), 60))
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetMyeBaySellingRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <UnsoldList><Include>true</Include><DurationInDays>{days_back}</DurationInDays>'
        f'<IncludeNotes>false</IncludeNotes>'
        f'<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>'
        f'</UnsoldList>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'  <ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>\n'
        f'</GetMyeBaySellingRequest>'
    )
    try:
        root = _trading_post("GetMyeBaySelling", xml, ebay_cfg)
    except Exception as exc:
        print(f"  GetMyeBaySelling failed: {exc}")
        return []

    ack = root.findtext(f"{NS}Ack") or ""
    if ack not in ("Success", "Warning"):
        err = root.find(f".//{NS}Errors")
        if err is not None:
            print(f"  UnsoldList error: [{err.findtext(f'{NS}ErrorCode')}] "
                  f"{err.findtext(f'{NS}LongMessage', '')[:140]}")
        return []

    out: list[dict] = []
    for item in root.findall(f".//{NS}UnsoldList/{NS}ItemArray/{NS}Item"):
        start_f = _to_float(item.findtext(f"{NS}StartPrice", "") or "0")
        bin_f   = _to_float(item.findtext(f"{NS}BuyItNowPrice", "") or "")
        cur_f   = _to_float(item.findtext(f"{NS}SellingStatus/{NS}CurrentPrice", "") or "") or start_f
        photos: list[str] = [u.text.strip() for u in item.findall(f"{NS}PictureDetails/{NS}PictureURL") if u.text]
        gallery = item.findtext(f"{NS}PictureDetails/{NS}GalleryURL", "") or ""
        if gallery and gallery not in photos:
            photos.append(gallery.strip())
        specifics: dict[str, str] = {}
        for nv in item.findall(f".//{NS}ItemSpecifics/{NS}NameValueList"):
            name = nv.findtext(f"{NS}Name", "") or ""
            vals = [v.text or "" for v in nv.findall(f"{NS}Value")]
            if name and vals:
                specifics[name] = vals[0] if len(vals) == 1 else " | ".join(vals)
        out.append({
            "item_id":        item.findtext(f"{NS}ItemID", "") or "",
            "title":          item.findtext(f"{NS}Title", "") or "",
            "end_date":       item.findtext(f"{NS}ListingDetails/{NS}EndTime", "") or "",
            "original_price": bin_f if bin_f else start_f,
            "start_bid":      start_f,
            "bin_price":      bin_f,
            "current_price":  cur_f,
            "category":       item.findtext(f"{NS}PrimaryCategory/{NS}CategoryName", "") or "",
            "store_category": item.findtext(f"{NS}Storefront/{NS}StoreCategoryID", "") or "",
            "condition":      item.findtext(f"{NS}ConditionDisplayName", "") or "",
            "photos":         photos,
            "specifics":      specifics,
            "listing_type":   item.findtext(f"{NS}ListingType", "") or "",
        })
    return out

def compute_new_price(unsold: dict, market_median: float | None = None) -> float:
    """FP relist price: BIN if set, else 2× start bid, else market median × 0.95,
    floored at $0.99. +$0.01 nudge so eBay accepts the relist (must differ)."""
    bin_p   = float(unsold.get("bin_price") or 0)
    start_b = float(unsold.get("start_bid") or 0)
    if bin_p > 0.99:
        price = bin_p
    elif start_b > 0:
        price = max(start_b * 2.0, 0.99)
    elif market_median and market_median > 0:
        price = market_median * 0.95
    else:
        price = 0.99
    return max(round(price + 0.01, 2), 0.99)

def relist_as_fixed_price(token: str, item_id: str, ebay_cfg: dict,
                          new_price: float | None = None,
                          dry_run: bool = True) -> dict:
    """Trading RelistFixedPriceItem — accepts the previous (auction) ItemID
    and creates a new FP item carrying over store category, photos, specifics,
    condition, shipping & returns. Returns {ok, new_item_id, fee, ack, error,
    dry_run, request_xml}."""
    price_str = f"{float(new_price):.2f}" if new_price is not None else ""
    price_block = (f'      <StartPrice currencyID="USD">{price_str}</StartPrice>\n'
                   if price_str else "")
    # A price cut on relist can drop the new price at/below a Best Offer
    # auto-accept/auto-decline threshold carried over from the original
    # listing, which eBay rejects outright (errors 22003/23004) -- that
    # rejection used to be invisible because the parser below only reported
    # the unrelated cosmetic "accept payment terms" Warning. Explicitly
    # disabling Best Offer on relist sidesteps recomputing valid thresholds
    # for an arbitrary new price; these are markdown backlog relists, not
    # negotiated sales, so Best Offer isn't needed here anyway.
    best_offer_block = ('<BestOfferDetails><BestOfferEnabled>false</BestOfferEnabled>'
                         '</BestOfferDetails>' if price_str else "")
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<RelistFixedPriceItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <Item><ItemID>{item_id}</ItemID>'
        f'<ListingType>FixedPriceItem</ListingType>'
        f'<ListingDuration>GTC</ListingDuration>'
        f'{price_block.strip()}{best_offer_block}</Item>\n'
        f'  <ErrorLanguage>en_US</ErrorLanguage><WarningLevel>High</WarningLevel>\n'
        f'</RelistFixedPriceItemRequest>'
    )
    if dry_run:
        return {"ok": True, "new_item_id": "", "fee": 0.0, "ack": "DryRun",
                "error": "", "dry_run": True, "request_xml": xml}
    try:
        root = _trading_post("RelistFixedPriceItem", xml, ebay_cfg)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "dry_run": False, "request_xml": xml}
    ack = root.findtext(f"{NS}Ack") or ""
    new_id = root.findtext(f"{NS}ItemID") or ""
    fee = 0.0
    for fee_node in root.findall(f".//{NS}Fees/{NS}Fee"):
        try:
            fee += float(fee_node.findtext(f"{NS}Fee", "0") or 0)
        except (TypeError, ValueError):
            pass
    err_msg = ""
    if ack not in ("Success", "Warning"):
        # eBay's RelistFixedPriceItem response nearly always carries a
        # SeverityCode=Warning "accept automatic payment terms" node
        # (ErrorCode 21919219) alongside the real, request-blocking
        # SeverityCode=Error node -- taking the first <Errors> blindly
        # reports that cosmetic warning as "the error" and hides the
        # actual cause (e.g. duplicate-listing, Best Offer threshold
        # violation) underneath it. Prefer Error severity; only fall back
        # to Warning if no Error-severity node is present.
        all_errs = root.findall(f".//{NS}Errors")
        err = next((e for e in all_errs
                    if (e.findtext(f"{NS}SeverityCode") or "") == "Error"), None)
        if err is None and all_errs:
            err = all_errs[0]
        if err is not None:
            err_msg = (f"[{err.findtext(f'{NS}ErrorCode')}] "
                       f"{err.findtext(f'{NS}LongMessage', '')[:200]}")
    return {"ok": ack in ("Success", "Warning") and bool(new_id),
            "new_item_id": new_id, "fee": fee, "ack": ack,
            "error": err_msg, "dry_run": False, "request_xml": xml}

def _days_ago(iso_dt: str) -> int:
    if not iso_dt:
        return 0
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(iso_dt.split("+")[0], fmt)
            return max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - dt).days)
        except ValueError:
            continue
    return 0


def main() -> int:
    print(f"  Mookie Wilson (Relist) reporting in.")
    ap = argparse.ArgumentParser(
        description="Find unsold ended auctions and relist them as Fixed-Price.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually call RelistFixedPriceItem (default: dry-run).")
    ap.add_argument("--days", type=int, default=14,
                    help="UnsoldList lookback window in days (1–60, default 14).")
    ap.add_argument("--item", default="",
                    help="Operate on a single ItemID only (skips fetch).")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    token: str | None = None
    try:
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Could not get access token ({exc}); rendering empty state.")

    unsold: list[dict] = []
    if token and not args.item:
        try:
            print(f"  Fetching UnsoldList (last {args.days} days)...")
            unsold = fetch_ended_unsold(token, ebay_cfg, days_back=args.days)
        except Exception as exc:
            print(f"  fetch_ended_unsold failed: {exc}")
    elif args.item:
        # Single-item mode: minimal stub so compute_new_price can run; the
        # actual relist call only needs the ItemID anyway.
        unsold = [{"item_id": args.item, "title": f"Item {args.item}",
                   "end_date": "", "original_price": 0.0, "start_bid": 0.0,
                   "bin_price": 0.0, "photos": [], "specifics": {},
                   "category": "", "store_category": "", "condition": "",
                   "listing_type": "Chinese"}]

    print(f"  Found {len(unsold)} unsold listing(s).")

    plans: list[dict] = []
    for u in unsold:
        suggested = compute_new_price(u)
        plans.append({**u, "suggested_price": suggested})

    # Cam Ward Pink Refractor ghost — only the real listing (306939333836)
    # may exist; never relist the duplicate. See repo memory.
    GHOST_IDS = {"306965305227"}
    _before = len(plans)
    plans = [p for p in plans if str(p.get("item_id") or "") not in GHOST_IDS]
    if len(plans) != _before:
        print(f"  Excluded Cam Ward ghost from relist ({_before} -> {len(plans)}).")

    # NEVER relist a card that has already SOLD. When a sold card's duplicate
    # listing is ended (EndingReason NotAvailable), eBay files it under
    # UnsoldList — relisting it re-creates an oversell. Exclude by title match
    # against sold history + a fresh SoldList. (Root cause: CollX re-list churn,
    # 2026-06-26.) See memory project_cdp_inventory_removal_delists_ebay.
    try:
        import re as _re
        from pathlib import Path as _Path
        _norm = lambda t: _re.sub(r"[^a-z0-9]", "", (t or "").lower())
        _sold_titles: set[str] = set()
        _sh = _Path(__file__).parent / "sold_history.json"
        if _sh.exists():
            for _s in json.loads(_sh.read_text()):
                if _s.get("title"):
                    _sold_titles.add(_norm(_s["title"]))
        if token:  # fresh SoldList (90d) on top of history
            try:
                _x = (f'<?xml version="1.0" encoding="utf-8"?><GetMyeBaySellingRequest xmlns="{EBAY_NS}">'
                      f'<RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>'
                      f'<SoldList><Include>true</Include><DurationInDays>90</DurationInDays>'
                      f'<Pagination><EntriesPerPage>200</EntriesPerPage><PageNumber>1</PageNumber></Pagination>'
                      f'</SoldList></GetMyeBaySellingRequest>')
                _root = _trading_post("GetMyeBaySelling", _x, ebay_cfg)
                for _t in _root.findall(f".//{NS}SoldList//{NS}Item/{NS}Title"):
                    if _t.text:
                        _sold_titles.add(_norm(_t.text))
            except Exception:
                pass
        _b2 = len(plans)
        plans = [p for p in plans
                 if not (len(_norm(p.get("title"))) > 14 and _norm(p.get("title")) in _sold_titles)]
        if len(plans) != _b2:
            print(f"  GUARD: excluded {_b2 - len(plans)} already-SOLD card(s) from relist.")
    except Exception as _e:
        print(f"  sold-exclusion guard failed (not relisting to be safe): {_e}")
        plans = []

    # NEVER relist a card that is ALREADY ACTIVE. When we end a duplicate
    # listing for inventory hygiene (oversell_guard), it lands in UnsoldList
    # and relist_agent would re-create a second copy on top of the still-live
    # original. Guard: cross-reference by normalized title against the active
    # listings snapshot.
    try:
        import re as _re2
        _norm2 = lambda t: _re2.sub(r"[^a-z0-9]", "", (t or "").lower())
        _snap_path = OUTPUT_DIR / "listings_snapshot.json"
        _active_titles: set[str] = set()
        if _snap_path.exists():
            _snap = json.loads(_snap_path.read_text())
            _snp_list = _snap.get("listings", []) if isinstance(_snap, dict) else _snap
            for _l in _snp_list:
                if isinstance(_l, dict) and _l.get("title"):
                    _active_titles.add(_norm2(_l["title"]))
        _b3 = len(plans)
        plans = [p for p in plans
                 if not (len(_norm2(p.get("title", ""))) > 14
                         and _norm2(p.get("title", "")) in _active_titles)]
        if len(plans) != _b3:
            print(f"  GUARD: excluded {_b3 - len(plans)} already-ACTIVE card(s) from relist (dup prevention).")
    except Exception as _e:
        print(f"  active-dup guard error (safe, continuing): {_e}")

    # NEVER relist (a) an ended LOT listing or (b) a card that is a component of
    # a player lot. Lot components' single-titles don't match the lot's title,
    # so the active-dup guard above misses them. build_lot_listing.py records
    # every ended lot-component id in output/do_not_relist.json, and any title
    # containing the word "lot" is a (superseded) lot listing. Root cause:
    # 2026-06-29 relist resurrected ~40 lot components + 6 ended lots as dupes.
    try:
        import re as _re3
        _dnr = set(str(x) for x in _read_json(OUTPUT_DIR / "do_not_relist.json", []))
        _b4 = len(plans)
        plans = [p for p in plans
                 if str(p.get("item_id") or "") not in _dnr
                 and not _re3.search(r"\blot\b", (p.get("title", "") or "").lower())]
        if len(plans) != _b4:
            print(f"  GUARD: excluded {_b4 - len(plans)} lot / lot-component listing(s) from relist.")
    except Exception as _e:
        print(f"  lot-guard error (safe, continuing): {_e}")

    history_entries: list[dict] = []
    if args.apply and token:
        for plan in plans:
            iid = plan.get("item_id") or ""
            price = float(plan.get("suggested_price") or 0)
            print(f"  Relisting {iid} as FP at ${price:.2f}...")
            res = relist_as_fixed_price(token, iid, ebay_cfg,
                                        new_price=price, dry_run=False)
            plan["relist_result"] = {k: v for k, v in res.items()
                                     if k not in ("request_xml", "response_xml")}
            history_entries.append({
                "ts":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "action":      "relist_fp",
                "item_id":     iid,
                "new_item_id": res.get("new_item_id", ""),
                "price":       price,
                "ok":          bool(res.get("ok")),
                "error":       res.get("error", ""),
            })
            time.sleep(PACE_SEC)
    elif args.apply and not token:
        print("  --apply given but no token available; skipping.")
    else:
        for plan in plans:
            iid = plan.get("item_id") or ""
            price = float(plan.get("suggested_price") or 0)
            print(f"  [dry-run] would relist {iid} as FP at ${price:.2f}")

    _write_json(PLAN_PATH, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days":  args.days,
        "count":        len(plans),
        "applied":      bool(args.apply),
        "plans":        plans,
    })
    _append_history(history_entries)

    print(f"  Plan:   {PLAN_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
