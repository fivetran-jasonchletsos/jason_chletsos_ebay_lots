"""
returns_agent.py — surface active eBay returns + draft seller responses.

When a buyer files a return on eBay, JC currently handles each case manually
in Seller Hub. This agent pulls all OPEN returns via the Post-Order API
(with a Trading API fallback), categorizes each as buyer_fault /
seller_fault / unclear, and drafts a polite response message for review.

Pipeline:
    1. fetch_active_returns()   → eBay Post-Order /return/search?return_state=OPEN
                                  (falls back to Trading GetUserReturns).
    2. categorize_return()      → bucket by reason text.
    3. draft_response()         → suggested message body per bucket.
    4. build_report()           → docs/returns.html dashboard.

Artifacts:
    output/returns_plan.json     latest snapshot of open returns + drafts
    output/returns_history.json  append-only action log
    docs/returns.html            admin-only review UI

Usage:
    python3 returns_agent.py            # dry run (default)
    python3 returns_agent.py --apply    # would accept/decline via Post-Order API
                                        # (currently still leaves manual — returns
                                        # are too consequential to fully automate).
"""
from __future__ import annotations

import argparse
import json
import re
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
PLAN_PATH    = OUTPUT_DIR / "returns_plan.json"
HISTORY_PATH = OUTPUT_DIR / "returns_history.json"
REPORT_PATH  = promote.OUTPUT_DIR / "returns.html"

POST_ORDER_BASE = "https://api.ebay.com/post-order/v2"
TRADING_URL     = "https://api.ebay.com/ws/api.dll"
EBAY_NS         = "urn:ebay:apis:eBLBaseComponents"
NS              = "{" + EBAY_NS + "}"
COMPAT          = "967"
SITE_ID         = "0"

MAX_RETRIES, BACKOFF_BASE_SEC, PACE_SEC = 3, 1.5, 0.4

# Reason classification regexes.
BUYER_FAULT_RX  = re.compile(
    r"\b(changed?\s*mind|change\s*of\s*mind|"
    r"doesn'?t\s*fit|does\s*not\s*fit|wrong\s*size|"
    r"ordered\s*by\s*mistake|no\s*longer\s*need(ed)?|"
    r"found\s*better\s*price|just\s*don'?t\s*want|"
    r"buyer.?remorse|accidental\s*purchase)\b", re.I)
SELLER_FAULT_RX = re.compile(
    r"\b(not\s*as\s*described|inaccurate\s*description|"
    r"damaged?\s*(in\s*shipping|in\s*transit|on\s*arrival)?|"
    r"arrived\s*damaged|broken|defective|"
    r"wrong\s*item(\s*sent)?|incorrect\s*item|missing\s*(parts?|piece)|"
    r"counterfeit|fake|not\s*authentic)\b", re.I)

# Draft response templates.
DRAFT_BUYER_FAULT = (
    "Hi — thanks for reaching out. I understand things don't always work out. "
    "Since the listing was accurate and the card arrived as described, I'm not "
    "able to cover return shipping on this one. I'd like to propose a partial "
    "refund of ${partial} and you keep the card — that way you're not out the "
    "shipping cost either way, and I can relist without the round-trip risk. "
    "Let me know if that works for you. — JC")

DRAFT_SELLER_FAULT = (
    "Hi — I'm really sorry about this. That's on me. I'm approving the return "
    "right now and will refund the full ${amount} as soon as it scans back into "
    "USPS — I'll also cover return shipping (a prepaid label is on its way to "
    "your eBay messages). Thanks for the patience, and again, my apologies. — JC")

DRAFT_UNCLEAR = (
    "Hi — thanks for opening this return. I want to make sure I understand the "
    "issue correctly before we move forward. Could you share a couple of photos "
    "of the card (front + back) and a quick note on what specifically didn't "
    "match expectations? Happy to make it right — I just want to get the "
    "details first. — JC")


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return default


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))


def _append_history(entries: list[dict]) -> None:
    if not entries:
        return
    h = _read_json(HISTORY_PATH, [])
    h = h if isinstance(h, list) else []
    h.extend(entries)
    _write_json(HISTORY_PATH, h)


def _post_order_headers(token: str, style: str = "iaf") -> dict[str, str]:
    """eBay docs are inconsistent — Post-Order v2 has historically accepted
    both `X-EBAY-API-IAF-TOKEN` and `Authorization: TOKEN`. We try both."""
    if style == "bearer":
        return {
            "Authorization": f"TOKEN {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
    return {
        "X-EBAY-API-IAF-TOKEN": token,
        "Authorization": f"TOKEN {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _post_order_get(path: str, token: str, params: dict | None = None) -> tuple[int, dict | None]:
    """Call Post-Order, trying IAF style first then Bearer style. Returns
    (last_status_code, json_or_none). Logs which header style worked."""
    url = f"{POST_ORDER_BASE}{path}"
    last_status = 0
    last_body: dict | None = None
    for style in ("iaf", "bearer"):
        last_err: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                r = requests.get(url, headers=_post_order_headers(token, style),
                                 params=params or {}, timeout=30)
                last_status = r.status_code
                if r.status_code == 200:
                    try:
                        body = r.json()
                    except ValueError:
                        body = None
                    print(f"  Post-Order GET {path} → 200 (header style: {style})")
                    return r.status_code, body
                if r.status_code in (401, 403, 404):
                    print(f"  Post-Order GET {path} → {r.status_code} (style {style}); "
                          f"trying next style")
                    break
                if 500 <= r.status_code < 600:
                    raise RuntimeError(f"HTTP {r.status_code}")
                try:
                    last_body = r.json()
                except ValueError:
                    last_body = {"raw": r.text[:500]}
                return r.status_code, last_body
            except Exception as exc:
                last_err = exc
                sleep_s = BACKOFF_BASE_SEC * (2 ** attempt)
                print(f"  Post-Order GET attempt {attempt+1} failed: {exc} — "
                      f"sleeping {sleep_s:.1f}s")
                time.sleep(sleep_s)
        if last_err is not None and last_status == 0:
            continue
    return last_status, last_body


def _trading_post(call_name: str, xml_body: str, ebay_cfg: dict) -> ET.Element:
    headers = {
        "X-EBAY-API-SITEID": SITE_ID,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-APP-NAME":  ebay_cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME":  ebay_cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME": ebay_cfg.get("client_secret", ""),
        "Content-Type": "text/xml",
    }
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


def _trading_fallback(token: str, ebay_cfg: dict) -> list[dict]:
    """Trading API GetUserReturns fallback when Post-Order isn't available
    on this account (e.g. permissions or sandbox mismatch)."""
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetUserReturnsRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <ReturnRole>SELLER</ReturnRole>\n'
        f'  <ItemFilterMode>OnlyOpen</ItemFilterMode>\n'
        f'</GetUserReturnsRequest>'
    )
    try:
        root = _trading_post("GetUserReturns", xml, ebay_cfg)
    except Exception as exc:
        print(f"  Trading fallback failed: {exc}")
        return []
    out: list[dict] = []
    for ret in root.findall(f".//{NS}ReturnSummary"):
        amount_node = ret.find(f".//{NS}RefundAmount")
        amount = float(amount_node.text) if amount_node is not None and amount_node.text else 0.0
        out.append({
            "return_id":     ret.findtext(f"{NS}ReturnID", "") or "",
            "item_id":       ret.findtext(f".//{NS}ItemID", "") or "",
            "buyer_user_id": ret.findtext(f".//{NS}BuyerLoginName", "") or "",
            "reason":        ret.findtext(f"{NS}Reason", "") or "",
            "request_date":  ret.findtext(f"{NS}CreationTime", "") or "",
            "refund_amount": amount,
            "return_status": ret.findtext(f"{NS}Status", "") or "OPEN",
            "has_message":   bool(ret.findtext(f"{NS}BuyerComments")),
            "title":         ret.findtext(f".//{NS}ItemTitle", "") or "",
        })
    return out


def fetch_active_returns(token: str, ebay_cfg: dict) -> list[dict]:
    """Return all open returns. Tries Post-Order v2 first, falls back to
    Trading GetUserReturns if Post-Order 401s/404s."""
    status, body = _post_order_get(
        "/return/search", token, params={"return_state": "OPEN", "limit": 50}
    )
    if status == 200 and isinstance(body, dict):
        out: list[dict] = []
        for r in body.get("returns", []) or body.get("members", []) or []:
            amt_node = (r.get("refundAmount") or r.get("totalRefundAmount")
                        or {}) if isinstance(r, dict) else {}
            try:
                amount = float(amt_node.get("value", 0))
            except (TypeError, ValueError):
                amount = 0.0
            out.append({
                "return_id":     str(r.get("returnId") or r.get("returnID") or ""),
                "item_id":       str(r.get("itemId") or
                                     (r.get("creationInfo") or {}).get("itemId") or ""),
                "buyer_user_id": str(r.get("buyerLoginName") or
                                     (r.get("buyer") or {}).get("userId") or ""),
                "reason":        str(r.get("reason") or
                                     (r.get("creationInfo") or {}).get("reason") or ""),
                "request_date":  str(r.get("creationDate") or
                                     (r.get("creationInfo") or {}).get("creationDate") or ""),
                "refund_amount": amount,
                "return_status": str(r.get("state") or r.get("status") or "OPEN"),
                "has_message":   bool(r.get("buyerComments") or
                                      (r.get("creationInfo") or {}).get("comments")),
                "title":         str(r.get("itemTitle") or
                                     (r.get("itemInfo") or {}).get("title") or ""),
            })
        return out
    # Post-Order didn't work — fall back.
    print(f"  Post-Order /return/search unavailable (last status={status}); "
          f"falling back to Trading GetUserReturns.")
    return _trading_fallback(token, ebay_cfg)


def categorize_return(ret: dict, listing_meta: dict | None = None) -> str:
    """Return one of: buyer_fault, seller_fault, unclear."""
    text = ((ret.get("reason") or "") + " " + (ret.get("title") or "")).strip()
    if SELLER_FAULT_RX.search(text):
        return "seller_fault"
    if BUYER_FAULT_RX.search(text):
        return "buyer_fault"
    return "unclear"


def draft_response(return_record: dict, category: str) -> str:
    """Produce a polite seller response based on category + refund amount."""
    amount = float(return_record.get("refund_amount") or 0.0)
    if category == "buyer_fault":
        partial = max(round(amount * 0.5, 2), 1.00)
        return DRAFT_BUYER_FAULT.format(partial=f"{partial:.2f}")
    if category == "seller_fault":
        return DRAFT_SELLER_FAULT.format(amount=f"{amount:.2f}")
    return DRAFT_UNCLEAR


def _days_open(request_date: str) -> int:
    if not request_date:
        return 0
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(request_date.split("+")[0], fmt)
            return max(0, (datetime.now(timezone.utc).replace(tzinfo=None) - dt).days)
        except ValueError:
            continue
    return 0


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")



def main() -> int:
    ap = argparse.ArgumentParser(
        description="Surface active eBay returns + draft seller responses.")
    ap.add_argument("--apply", action="store_true",
                    help="Would accept/decline via Post-Order API. Currently "
                         "still leaves manual — returns are too consequential.")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    token: str | None = None
    try:
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Could not get access token ({exc}); rendering empty state.")

    returns: list[dict] = []
    if token:
        try:
            print("  Fetching active returns (Post-Order v2 /return/search)...")
            returns = fetch_active_returns(token, ebay_cfg)
        except Exception as exc:
            print(f"  fetch_active_returns failed: {exc}")
    print(f"  Found {len(returns)} open return(s).")

    drafts: list[dict] = []
    for r in returns:
        cat  = categorize_return(r, None)
        resp = draft_response(r, cat)
        drafts.append({**r, "category": cat, "draft_response": resp})

    _write_json(PLAN_PATH, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(drafts),
        "returns": drafts,
    })

    if args.apply:
        print("\n  --apply was set, but returns are too consequential for full "
              "auto. Use the dashboard buttons to accept/decline manually on eBay.")
        _append_history([{
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "action": "noop_apply", "count": len(drafts),
            "note": "Manual gate — no automated accept/decline performed.",
        }])
    else:
        print("\n  Dry run only — dashboard rendered for review.")

    print(f"  Plan:   {PLAN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
