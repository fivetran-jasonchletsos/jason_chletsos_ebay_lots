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


_PAGE_HEAD = "<style>" + (
    ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)} "
    ".ret-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:18px 0 28px} "
    ".ret-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden} "
    ".ret-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7} "
    ".ret-kpi.bad::before{background:#ef4444} .ret-kpi.ok::before{background:#22c55e} .ret-kpi.warn::before{background:#facc15} "
    ".ret-kpi .n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1} "
    ".ret-kpi .l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px} "
    ".ret-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 24px} "
    ".ret-note h3{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)} "
    ".ret-note ul{margin:0;padding-left:18px;color:var(--text)} "
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px} "
    "table.ret-tbl{width:100%;border-collapse:collapse;font-size:13px} "
    ".ret-tbl th,.ret-tbl td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top} "
    ".ret-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em} "
    ".ret-tbl .item{width:240px} .ret-tbl .item img{width:64px;height:64px;object-fit:cover;border-radius:var(--r-sm);border:1px solid var(--border);float:left;margin-right:10px;background:var(--surface-2)} "
    ".ret-tbl .item .title{color:var(--text);font-weight:600;font-size:13px;line-height:1.35} "
    ".ret-tbl .item .iid{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px} "
    ".ret-tbl .who .b{color:var(--text);font-weight:600} .ret-tbl .who .d{color:var(--text-dim);font-size:11px;margin-top:2px} "
    ".ret-tbl .reason{max-width:260px;color:var(--text-muted);white-space:pre-wrap;line-height:1.45} "
    ".ret-tbl .amt{font-family:'JetBrains Mono',monospace;color:var(--text);font-weight:600} "
    ".ret-tbl .age{font-family:'JetBrains Mono',monospace;color:var(--text)} .ret-tbl .age.old{color:#ef4444} "
    ".badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px} "
    ".badge.buyer{background:rgba(34,197,94,.12);color:#22c55e;border:1px solid rgba(34,197,94,.4)} "
    ".badge.seller{background:rgba(239,68,68,.12);color:#ef4444;border:1px solid rgba(239,68,68,.4)} "
    ".badge.unclear{background:rgba(234,179,8,.12);color:#facc15;border:1px solid rgba(234,179,8,.4)} "
    ".ret-tbl .draft{width:34%} "
    ".ret-tbl textarea{width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 12px;font-family:inherit;font-size:13px;line-height:1.5;resize:vertical} "
    ".row-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px} "
    ".btn{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:7px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;cursor:pointer;text-decoration:none;display:inline-block} "
    ".btn:hover{filter:brightness(1.1)} "
    ".btn.ok{background:#22c55e;color:#0a0a0a;border-color:#22c55e} "
    ".btn.no{background:#ef4444;color:#fff;border-color:#ef4444} "
    ".btn.gold{background:var(--gold);color:#0a0a0a;border-color:var(--gold)} "
    ".empty{color:var(--text-muted);padding:36px 28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md);font-size:15px} "
    ".empty .big{font-family:'Bebas Neue',sans-serif;font-size:36px;color:var(--gold);display:block;margin-bottom:6px}"
) + "</style><script>" + (
    "document.addEventListener('click',function(e){var b=e.target.closest('.btn[data-action]');if(!b)return;"
    "var act=b.getAttribute('data-action');var rid=b.getAttribute('data-return-id');"
    "if(!confirm('Confirm '+act+' on return '+rid+'?'))return;"
    "b.disabled=true;b.textContent='…';"
    "var payload={return_id:rid,action:act};"
    "if(act==='send'){var t=document.querySelector('textarea[data-return-id=\"'+rid+'\"]');if(t)payload.body=t.value;}"
    "fetch('/ebay/returns-action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})"
    ".then(function(r){return r.json();}).then(function(d){b.textContent=d&&d.ok?'Done ✓':'Failed';})"
    ".catch(function(){b.disabled=false;b.textContent=act;});});"
) + "</script>"


def build_report(drafts: list[dict]) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total       = len(drafts)
    liability   = sum(float(d.get("refund_amount") or 0) for d in drafts)
    buyer_n     = sum(1 for d in drafts if d.get("category") == "buyer_fault")
    seller_n    = sum(1 for d in drafts if d.get("category") == "seller_fault")
    unclear_n   = sum(1 for d in drafts if d.get("category") == "unclear")

    if not drafts:
        rows_html = (
            "<div class='empty'><span class='big'>Zero open returns</span>"
            "No active returns to handle right now — buyers are happy.<br>"
            "New returns from eBay will appear here automatically.</div>"
        )
    else:
        def _row(d: dict) -> str:
            rid    = _esc(d.get("return_id") or "")
            iid    = _esc(d.get("item_id") or "")
            cat    = d.get("category") or "unclear"
            badge_cls = {"buyer_fault": "buyer", "seller_fault": "seller"}.get(cat, "unclear")
            badge_lbl = {"buyer_fault": "Buyer fault — partial offer",
                         "seller_fault": "Seller fault — accept return",
                         "unclear": "Unclear — manual review"}[cat]
            age = _days_open(d.get("request_date") or "")
            age_cls = "old" if age >= 7 else ""
            thumb = (f"https://i.ebayimg.com/images/g/{iid}/s-l64.jpg"
                     if iid else "")
            view_url = f"https://www.ebay.com/mesh/ord/returns-details?returnId={rid}"
            return (
                f"<tr>"
                f"<td class='item'>"
                f"{('<img src=\"' + thumb + '\" alt=\"\" loading=\"lazy\">' ) if thumb else ''}"
                f"<div class='title'>{_esc(d.get('title') or '(no title)')}</div>"
                f"<div class='iid'>item {iid or '—'} · ret {rid or '—'}</div>"
                f"</td>"
                f"<td class='who'>"
                f"<div class='b'>{_esc(d.get('buyer_user_id') or '—')}</div>"
                f"<div class='d'>{_esc((d.get('request_date') or '')[:10])}</div>"
                f"</td>"
                f"<td class='reason'>{_esc(d.get('reason') or '(no reason given)')}"
                f"<div><span class='badge {badge_cls}'>{badge_lbl}</span></div>"
                f"</td>"
                f"<td class='amt'>${float(d.get('refund_amount') or 0):.2f}</td>"
                f"<td class='age {age_cls}'>{age}d</td>"
                f"<td class='draft'>"
                f"<textarea data-return-id=\"{rid}\" rows='7'>"
                f"{_esc(d.get('draft_response') or '')}</textarea>"
                f"<div class='row-actions'>"
                f"<button class='btn ok'    data-action='accept'  data-return-id=\"{rid}\">Accept return</button>"
                f"<button class='btn no'    data-action='decline' data-return-id=\"{rid}\">Decline</button>"
                f"<button class='btn gold'  data-action='send'    data-return-id=\"{rid}\">Send response</button>"
                f"<a class='btn' href='{view_url}' target='_blank' rel='noopener'>View on eBay</a>"
                f"</div>"
                f"</td>"
                f"</tr>"
            )
        rows_html = (
            "<div class='tbl-wrap'><table class='ret-tbl'><thead><tr>"
            "<th>Item</th><th>Buyer</th><th>Reason</th><th>Refund</th><th>Days</th>"
            "<th>Drafted response + actions</th></tr></thead>"
            f"<tbody>{''.join(_row(d) for d in drafts)}</tbody></table></div>"
        )

    body = (
        f"<section class='hero'><h1>Returns</h1>"
        f"<p class='sub'>Last run: <code>{run_ts}</code></p>"
        f"<div class='ret-kpis'>"
        f"<div class='ret-kpi {'bad' if total else 'ok'}'><div class='n'>{total}</div>"
        f"<div class='l'>Open returns</div></div>"
        f"<div class='ret-kpi {'warn' if liability else 'ok'}'><div class='n'>${liability:,.2f}</div>"
        f"<div class='l'>Total refund liability</div></div>"
        f"<div class='ret-kpi'><div class='n'>{buyer_n}</div>"
        f"<div class='l'>Buyer-fault</div></div>"
        f"<div class='ret-kpi'><div class='n'>{seller_n}</div>"
        f"<div class='l'>Seller-fault</div></div>"
        f"<div class='ret-kpi {'warn' if unclear_n else ''}'><div class='n'>{unclear_n}</div>"
        f"<div class='l'>Unclear</div></div>"
        f"</div></section>"
        f"<section class='ret-note'><h3>How this works</h3><ul>"
        f"<li>Pulls all OPEN returns via the eBay Post-Order v2 API "
        f"(Trading <code>GetUserReturns</code> fallback if Post-Order is unavailable).</li>"
        f"<li>Buckets each by reason: <b>buyer fault</b> (changed mind, ordered by mistake) "
        f"→ propose partial refund + buyer keeps; <b>seller fault</b> (not as described, "
        f"damaged, wrong item) → accept + full refund; <b>unclear</b> → flag for review.</li>"
        f"<li>Drafts a polite response per case. Action buttons are stubs — actual "
        f"accept/decline still happens manually on eBay (returns are too consequential "
        f"for full auto).</li>"
        f"</ul></section>"
        f"{rows_html}"
    )

    html = promote.html_shell("Returns · Harpua2001", body,
                              extra_head=_PAGE_HEAD, active_page="returns.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


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

    report = build_report(drafts)
    print(f"  Report: {report}")
    print(f"  Plan:   {PLAN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
