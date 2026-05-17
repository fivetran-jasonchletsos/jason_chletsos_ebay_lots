"""
tracking_responder_agent.py — auto-respond to "where's my order?" buyer
messages by pre-building the tracking lookup and drafting a reply.

Pipeline:
    1. fetch_recent_orders()       Trading GetOrders (last N days) → index by
                                   buyer_user_id with shipping + tracking detail.
    2. fetch_unanswered_messages() GetMyMessages (ReturnHeaders → ReturnMessages),
                                   filtered to tracking-related keywords.
    3. match_message_to_order()    pair each message with the buyer's most
                                   relevant recent order.
    4. draft_tracking_reply()      compose a reply with carrier + tracking
                                   number + carrier-specific tracking URL.
    5. send_reply()                AddMemberMessageAAQToPartner (dry-run by
                                   default; --apply sends).

Artifacts:
    output/tracking_plan.json      latest drafted replies
    output/tracking_history.json   append-only send log
    docs/tracking.html             admin review UI with editable drafts

Usage:
    python3 tracking_responder_agent.py            # dry run (default)
    python3 tracking_responder_agent.py --apply    # send via Trading API
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT    = Path(__file__).parent
OUTPUT_DIR   = REPO_ROOT / "output"
PLAN_PATH    = OUTPUT_DIR / "tracking_plan.json"
HISTORY_PATH = OUTPUT_DIR / "tracking_history.json"
REPORT_PATH  = promote.OUTPUT_DIR / "tracking.html"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT, SITE_ID = "967", "0"
DEFAULT_DAYS_BACK = 30
PACE_SEC, MAX_RETRIES, BACKOFF_BASE_SEC = 0.4, 3, 1.5

TRACKING_KEYWORDS = ("track", "tracking", "where", "shipped", "ship", "order",
                     "package", "delivery", "arrived", "received", "lost")
TRACKING_RX = re.compile(
    r"\b(track(ing)?|where('?s| is)?|shipp?ed|shipping|order|package|"
    r"deliver(y|ed)?|arriv(e|ed|al)|receiv(e|ed)|lost|stuck|missing)\b", re.I)

# Carrier → tracking URL template. Normalize carrier (lowercase, strip non-alnum)
# before matching the longest prefix.
CARRIER_URLS = {
    "usps":  "https://tools.usps.com/go/TrackConfirmAction?qtc_tLabels1={tracking}",
    "ups":   "https://www.ups.com/track?tracknum={tracking}",
    "fedex": "https://www.fedex.com/fedextrack/?trknbr={tracking}",
    "dhl":   "https://www.dhl.com/en/express/tracking.html?AWB={tracking}",
    "ontrac":"https://www.ontrac.com/tracking?number={tracking}",
}

_PAGE_CSS = (".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
    ".trk-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0 28px}.trk-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}.trk-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}.trk-kpi .n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1}.trk-kpi .l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}"
    ".trk-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 24px}.trk-note h3{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}.trk-note ul{margin:0;padding-left:18px;color:var(--text)}"
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}table.trk-tbl{width:100%;border-collapse:collapse;font-size:13px}.trk-tbl th,.trk-tbl td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}.trk-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
    ".trk-tbl .from{width:180px}.trk-tbl .from .sender{color:var(--text);font-weight:600}.trk-tbl .from .recv{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px}.trk-tbl .msg .subj{color:var(--text);font-weight:600;margin-bottom:6px}.trk-tbl .msg .excerpt{color:var(--text-muted);white-space:pre-wrap;line-height:1.45}"
    ".trk-tbl .ord{width:240px}.trk-tbl .ord .title{color:var(--text);font-weight:600;margin-bottom:4px}.trk-tbl .ord .meta{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;line-height:1.55}.trk-tbl .ord a{color:var(--gold);text-decoration:none}.trk-tbl .ord a:hover{text-decoration:underline}"
    ".badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:.08em}.badge.matched{background:rgba(34,197,94,.12);color:var(--success,#22c55e);border:1px solid rgba(34,197,94,.4)}.badge.unmatched{background:rgba(234,179,8,.12);color:var(--gold,#facc15);border:1px solid rgba(234,179,8,.4)}"
    ".trk-tbl .reply{width:36%}.trk-tbl textarea{width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 12px;font-family:inherit;font-size:13px;line-height:1.5;resize:vertical}.row-actions{display:flex;align-items:center;gap:10px;margin-top:8px}.row-actions .hint{color:var(--text-dim);font-size:11px}.btn-send{background:var(--gold);color:#111;border:0;border-radius:var(--r-sm);padding:8px 14px;font-weight:700;cursor:pointer;text-transform:uppercase;letter-spacing:.06em;font-size:12px}.btn-send:hover{filter:brightness(1.08)}.btn-send:disabled{opacity:.6;cursor:default}"
    ".empty{color:var(--text-muted);padding:28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}")
_PAGE_JS = ("document.addEventListener('click',function(e){var b=e.target.closest('.btn-send');if(!b)return;var id=b.getAttribute('data-msg-id');var t=document.querySelector('textarea[data-msg-id=\"'+id+'\"]');if(!t)return;b.disabled=true;b.textContent='Sending…';fetch('/ebay/send-reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:id,body:t.value})}).then(function(r){return r.json();}).then(function(d){b.textContent=d&&d.ok?'Sent ✓':'Failed';}).catch(function(){b.disabled=false;b.textContent='Send via eBay';});});")
_PAGE_HEAD = f"<style>{_PAGE_CSS}</style><script>{_PAGE_JS}</script>"

def _read_json(path: Path, default):
    if not path.exists(): return default
    try: return json.loads(path.read_text())
    except json.JSONDecodeError: return default

def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))

def _append_history(entries: list[dict]) -> None:
    if not entries: return
    h = _read_json(HISTORY_PATH, [])
    h = h if isinstance(h, list) else []
    h.extend(entries)
    _write_json(HISTORY_PATH, h)

def _trading_headers(call_name: str, ebay_cfg: dict) -> dict[str, str]:
    return {"X-EBAY-API-SITEID": SITE_ID, "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
            "X-EBAY-API-CALL-NAME": call_name,
            "X-EBAY-API-APP-NAME":  ebay_cfg.get("client_id", ""),
            "X-EBAY-API-DEV-NAME":  ebay_cfg.get("dev_id", ""),
            "X-EBAY-API-CERT-NAME": ebay_cfg.get("client_secret", ""),
            "Content-Type": "text/xml"}

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
            print(f"  [{call_name}] attempt {attempt+1} failed: {exc} — sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"{call_name} failed after {MAX_RETRIES} retries: {last_err}")

def _parse_errors(root: ET.Element) -> list[dict]:
    return [{"code": err.findtext(f"{NS}ErrorCode", "") or "",
             "severity": err.findtext(f"{NS}SeverityCode", "") or "",
             "msg": err.findtext(f"{NS}ShortMessage", "") or ""}
            for err in root.findall(f".//{NS}Errors")]

def _carrier_url(carrier: str, tracking: str) -> str:
    """Build a one-click tracking URL based on the carrier name."""
    if not tracking: return ""
    key = re.sub(r"[^a-z0-9]", "", (carrier or "").lower())
    # Order matters: longest/most-specific keys first.
    for k in ("fedex", "ontrac", "usps", "ups", "dhl"):
        if k in key:
            return CARRIER_URLS[k].format(tracking=tracking)
    # Default to USPS — dominant carrier for trading-card shipments.
    return CARRIER_URLS["usps"].format(tracking=tracking)

def fetch_recent_orders(token: str, ebay_cfg: dict,
                        days_back: int = DEFAULT_DAYS_BACK) -> dict[str, list[dict]]:
    """Trading GetOrders → dict keyed by buyer_user_id → list of orders.

    Each order: order_id, item_id, item_title, ship_carrier, tracking_number,
    shipped_at, expected_delivery, current_status, paid_at, created_at, buyer.
    """
    days_back = min(max(int(days_back), 1), 90)
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    by_buyer: dict[str, list[dict]] = {}
    page = 1
    while True:
        xml_body = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            f'<GetOrdersRequest xmlns="{EBAY_NS}">\n'
            f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
            f'  <CreateTimeFrom>{start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeFrom>\n'
            f'  <CreateTimeTo>{end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeTo>\n'
            f'  <OrderRole>Seller</OrderRole><OrderStatus>All</OrderStatus>\n'
            f'  <Pagination><EntriesPerPage>100</EntriesPerPage><PageNumber>{page}</PageNumber></Pagination>\n'
            f'  <DetailLevel>ReturnAll</DetailLevel>\n'
            f'</GetOrdersRequest>')
        root = _trading_post("GetOrders", xml_body, ebay_cfg)
        fatal = [e for e in _parse_errors(root) if e["severity"] == "Error"]
        if fatal:
            print(f"  GetOrders errors: {fatal[:2]}")
            break
        for order in root.findall(f".//{NS}Order"):
            order_id = order.findtext(f"{NS}OrderID", "") or ""
            buyer    = order.findtext(f"{NS}BuyerUserID", "") or ""
            status   = order.findtext(f"{NS}OrderStatus", "") or ""
            created  = order.findtext(f"{NS}CreatedTime", "") or ""
            paid     = order.findtext(f"{NS}PaidTime", "") or ""
            shipped  = order.findtext(f"{NS}ShippedTime", "") or ""
            # Carrier + tracking from ShippingDetails.ShipmentTrackingDetails.
            carrier, tracking = "", ""
            sd = order.find(f"{NS}ShippingDetails")
            if sd is not None:
                std = sd.find(f"{NS}ShipmentTrackingDetails")
                if std is not None:
                    carrier  = std.findtext(f"{NS}ShippingCarrierUsed", "") or ""
                    tracking = std.findtext(f"{NS}ShipmentTrackingNumber", "") or ""
            ship_svc = order.findtext(f"{NS}ShippingServiceSelected/{NS}ShippingService", "") or ""
            if not carrier and ship_svc:
                carrier = ship_svc
            # eBay estimated delivery window (max preferred).
            expected = (order.findtext(f"{NS}ShippingServiceSelected/{NS}ShippingPackageInfo/{NS}EstimatedDeliveryTimeMax", "")
                        or order.findtext(f"{NS}ShippingServiceSelected/{NS}ShippingPackageInfo/{NS}EstimatedDeliveryTimeMin", ""))
            for trans in order.findall(f".//{NS}Transaction"):
                item = trans.find(f"{NS}Item")
                if item is None: continue
                rec = {
                    "order_id": order_id,
                    "item_id":  item.findtext(f"{NS}ItemID", "") or "",
                    "item_title": item.findtext(f"{NS}Title", "") or "",
                    "ship_carrier": carrier, "tracking_number": tracking,
                    "shipped_at": shipped, "expected_delivery": expected,
                    "current_status": status, "paid_at": paid,
                    "created_at": created, "buyer": buyer,
                }
                by_buyer.setdefault(buyer, []).append(rec)
        pr = root.find(f".//{NS}PaginationResult")
        total_pages = int(pr.findtext(f"{NS}TotalNumberOfPages", "1")) if pr is not None else 1
        if page >= total_pages: break
        page += 1
        time.sleep(PACE_SEC)
    for lst in by_buyer.values():
        lst.sort(key=lambda o: o.get("paid_at") or o.get("created_at") or "", reverse=True)
    return by_buyer

def _xml_get_headers(token: str, days_back: int) -> str:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<GetMyMessagesRequest xmlns="{EBAY_NS}">\n'
            f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
            f'  <DetailLevel>ReturnHeaders</DetailLevel>\n'
            f'  <StartTime>{start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</StartTime>\n'
            f'  <EndTime>{end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</EndTime>\n'
            f'</GetMyMessagesRequest>')

def _xml_get_bodies(token: str, ids: list[str]) -> str:
    ids_xml = "".join(f"<MessageID>{i}</MessageID>" for i in ids)
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<GetMyMessagesRequest xmlns="{EBAY_NS}">\n'
            f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
            f'  <DetailLevel>ReturnMessages</DetailLevel>\n'
            f'  <MessageIDs>{ids_xml}</MessageIDs>\n'
            f'</GetMyMessagesRequest>')

def fetch_unanswered_messages(token: str, ebay_cfg: dict,
                              days_back: int = DEFAULT_DAYS_BACK) -> list[dict]:
    """Return unanswered messages whose text matches tracking keywords.

    Two-call pattern: ReturnHeaders first (to learn unanswered MessageIDs),
    then ReturnMessages with those IDs to fetch bodies.
    """
    root = _trading_post("GetMyMessages", _xml_get_headers(token, days_back), ebay_cfg)
    fatal = [e for e in _parse_errors(root) if e["severity"] == "Error"]
    if fatal:
        print(f"  GetMyMessages (headers) errors: {fatal}")
        return []
    ids: list[str] = []
    for m in root.findall(f".//{NS}Messages/{NS}Message"):
        if (m.findtext(f"{NS}Responded") or "").lower() == "true":
            continue
        mid = m.findtext(f"{NS}MessageID", "") or ""
        if mid: ids.append(mid)
    if not ids: return []
    root = _trading_post("GetMyMessages", _xml_get_bodies(token, ids), ebay_cfg)
    out: list[dict] = []
    for m in root.findall(f".//{NS}Messages/{NS}Message"):
        body    = (m.findtext(f"{NS}Text") or m.findtext(f"{NS}Content") or "")
        subject = m.findtext(f"{NS}Subject", "") or ""
        if not TRACKING_RX.search(f"{subject}\n{body}".lower()):
            continue
        out.append({
            "message_id":  m.findtext(f"{NS}MessageID", "") or "",
            "ebay_msg_id": m.findtext(f"{NS}ExternalMessageID", "") or "",
            "sender":      m.findtext(f"{NS}Sender", "") or "",
            "recipient":   m.findtext(f"{NS}RecipientUserID", "") or "",
            "item_id":     m.findtext(f"{NS}ItemID", "") or "",
            "subject":     subject, "body": body,
            "received_at": m.findtext(f"{NS}ReceiveDate", "") or "",
        })
    return out

def match_message_to_order(msg: dict, orders_by_buyer: dict[str, list[dict]]) -> dict | None:
    """Find the most-relevant recent order for the message's sender."""
    sender = (msg.get("sender") or "").strip()
    if not sender: return None
    candidates = orders_by_buyer.get(sender) or []
    if not candidates:
        for k, lst in orders_by_buyer.items():
            if k.lower() == sender.lower():
                candidates = lst
                break
    if not candidates: return None
    item_id = (msg.get("item_id") or "").strip()
    if item_id:
        for o in candidates:
            if o.get("item_id") == item_id:
                return o
    return candidates[0]  # already sorted newest-first

def _fmt_date(iso: str) -> str:
    if not iso: return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %d, %Y")
    except Exception:
        return iso[:10]

def draft_tracking_reply(msg: dict, order: dict | None) -> dict:
    """Generate a tracking-aware reply tied to the matched order (or a holding
    note if no order matched)."""
    sender = msg.get("sender") or "there"
    base = {"message_id": msg.get("message_id"), "sender": msg.get("sender"),
            "item_id": msg.get("item_id"), "subject": msg.get("subject"),
            "body": msg.get("body"), "received_at": msg.get("received_at")}
    if not order:
        base.update(matched=False, order=None, draft_reply=(
            f"Hi {sender} — thanks for reaching out about your order. I'm "
            "pulling up the shipment details now and will follow up with "
            "your tracking info within the next few hours. Apologies for "
            "the wait! — JC"))
        return base
    title    = (order.get("item_title") or "your order")[:120]
    carrier  = order.get("ship_carrier") or "USPS"
    tracking = order.get("tracking_number") or ""
    shipped  = _fmt_date(order.get("shipped_at") or "")
    expected = _fmt_date(order.get("expected_delivery") or "")
    url      = _carrier_url(carrier, tracking)
    parts: list[str] = [f"Hi {sender}!"]
    if tracking and shipped:
        parts.append(f"Your order for \"{title}\" shipped on {shipped} via {carrier}, "
                     f"tracking number {tracking}.")
    elif tracking:
        parts.append(f"Your order for \"{title}\" shipped via {carrier}, "
                     f"tracking number {tracking}.")
    elif shipped:
        parts.append(f"Your order for \"{title}\" shipped on {shipped} via {carrier}.")
    else:
        parts.append(f"Your order for \"{title}\" is being processed — I'll "
                     "have a tracking number posted as soon as it goes out.")
    if expected: parts.append(f"Expected delivery: {expected}.")
    if url:      parts.append(f"Track it here: {url}")
    parts.append("Let me know if you don't see movement in the next 24-48 hours "
                 "and I'll dig in. Thanks! — JC")
    base.update(matched=True, order=order, carrier_url=url,
                draft_reply=" ".join(parts))
    return base

def _xml_send_reply(token: str, item_id: str, recipient: str,
                    parent_msg_id: str, body: str) -> str:
    safe = body.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    parent_block = f"<ParentMessageID>{parent_msg_id}</ParentMessageID>" if parent_msg_id else ""
    return ('<?xml version="1.0" encoding="utf-8"?>\n'
            f'<AddMemberMessageAAQToPartnerRequest xmlns="{EBAY_NS}">\n'
            f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
            f'  <ItemID>{item_id}</ItemID>\n'
            f'  <MemberMessage>\n'
            f'    <Subject>Re: your order tracking</Subject>\n'
            f'    <Body>{safe}</Body>\n'
            f'    <RecipientID>{recipient}</RecipientID>\n'
            f'    <QuestionType>General</QuestionType>\n'
            f'    {parent_block}\n'
            f'  </MemberMessage>\n'
            f'</AddMemberMessageAAQToPartnerRequest>')

def send_reply(token: str, msg: dict, body: str, ebay_cfg: dict,
               dry_run: bool = True) -> dict:
    """Send a single tracking reply via AddMemberMessageAAQToPartner."""
    record: dict = {"sent_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "message_id": msg.get("message_id"), "recipient": msg.get("sender"),
                    "item_id": msg.get("item_id"), "body": body,
                    "dry_run": dry_run, "ok": None, "ack": None, "errors": []}
    if dry_run:
        record["ok"], record["ack"] = True, "DryRun"
        return record
    xml = _xml_send_reply(token, msg.get("item_id") or "", msg.get("sender") or "",
                          msg.get("message_id") or "", body)
    try:
        root = _trading_post("AddMemberMessageAAQToPartner", xml, ebay_cfg)
        ack  = root.findtext(f"{NS}Ack", "") or ""
        record["ack"], record["errors"] = ack, _parse_errors(root)
        record["ok"] = ack in ("Success", "Warning")
    except Exception as exc:
        record["ok"] = False
        record["errors"] = [{"code": "EXC", "severity": "Error", "msg": str(exc)}]
    time.sleep(PACE_SEC)
    return record

def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _row_html(d: dict) -> str:
    mid   = _esc(d.get("message_id") or "")
    order = d.get("order") or {}
    badge = ("<span class='badge matched'>matched</span>" if d.get("matched")
             else "<span class='badge unmatched'>no order found</span>")
    url   = d.get("carrier_url") or ""
    track = (f"<a href='{_esc(url)}' target='_blank' rel='noopener'>"
             f"{_esc(order.get('tracking_number') or '')}</a>" if url
             else _esc(order.get('tracking_number') or '—'))
    ord_block = (
        f"<div class='title'>{_esc((order.get('item_title') or '')[:90])}</div>"
        f"<div class='meta'>order {_esc(order.get('order_id') or '—')}<br>"
        f"carrier {_esc(order.get('ship_carrier') or '—')}<br>"
        f"tracking {track}<br>"
        f"shipped {_esc(_fmt_date(order.get('shipped_at') or '') or '—')}<br>"
        f"status {_esc(order.get('current_status') or '—')}</div>"
    ) if order else "<div class='meta'>No matching recent order for this buyer.</div>"
    return (
        f"<tr><td class='from'><div class='sender'>{_esc(d.get('sender') or '')}</div>"
        f"<div class='recv'>{_esc(d.get('received_at') or '')}</div></td>"
        f"<td class='msg'><div class='subj'>{_esc(d.get('subject') or '(no subject)')}</div>"
        f"<div class='excerpt'>{_esc((d.get('body') or '')[:280])}</div>"
        f"<div style='margin-top:8px'>{badge}</div></td>"
        f"<td class='ord'>{ord_block}</td>"
        f"<td class='reply'><textarea data-msg-id=\"{mid}\" rows='7'>"
        f"{_esc(d.get('draft_reply') or '')}</textarea>"
        f"<div class='row-actions'><button class='btn-send' data-msg-id=\"{mid}\">"
        f"Send via eBay</button><span class='hint'>Stub — wire to /ebay/send-reply Lambda.</span>"
        f"</div></td></tr>")

def build_report(drafts: list[dict], order_count: int) -> Path:
    run_ts  = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total   = len(drafts)
    matched = sum(1 for d in drafts if d.get("matched"))
    pending = total - matched
    if not drafts:
        rows_html = ("<p class='empty'>No tracking-related buyer messages in the "
                     "last 30 days. When a buyer asks \"where's my order?\" their "
                     "message will appear here with the tracking lookup pre-filled.</p>")
    else:
        rows_html = ("<div class='tbl-wrap'><table class='trk-tbl'><thead><tr>"
                     "<th>From</th><th>Message</th><th>Matched Order</th>"
                     "<th>Drafted Reply</th></tr></thead>"
                     f"<tbody>{''.join(_row_html(d) for d in drafts)}</tbody></table></div>")
    body = (
        f"<section class='hero'><h1>Order Tracking Replies</h1>"
        f"<p class='sub'>Last run: <code>{run_ts}</code> · "
        f"{order_count} order(s) indexed from the last 30 days</p>"
        f"<div class='trk-kpis'>"
        f"<div class='trk-kpi'><div class='n'>{total}</div><div class='l'>Tracking msgs</div></div>"
        f"<div class='trk-kpi'><div class='n'>{matched}</div><div class='l'>Auto-matched</div></div>"
        f"<div class='trk-kpi'><div class='n'>{pending}</div><div class='l'>Need lookup</div></div>"
        f"<div class='trk-kpi'><div class='n'>{order_count}</div><div class='l'>Orders indexed</div></div>"
        f"</div></section>"
        f"<section class='trk-note'><h3>How this works</h3><ul>"
        f"<li>Pulls recent orders via GetOrders (last 30 days) keyed by buyer.</li>"
        f"<li>Filters unanswered messages to tracking keywords "
        f"(<code>track</code>, <code>where</code>, <code>shipped</code>, "
        f"<code>delivery</code>, <code>lost</code>, …).</li>"
        f"<li>Matches each message to the buyer's most recent order, then "
        f"drafts a reply with carrier + tracking number + a one-click "
        f"carrier tracking link.</li>"
        f"<li>Review the draft, edit if needed, click Send via eBay.</li>"
        f"</ul></section>{rows_html}")
    html = promote.html_shell("Order Tracking · Harpua2001", body,
                              extra_head=_PAGE_HEAD, active_page="tracking.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Auto-respond to where's-my-order messages with tracking info.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually send replies (default: dry run).")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK,
                    help=f"How far back to scan (default {DEFAULT_DAYS_BACK}).")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    token: str | None = None
    try:
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Could not get access token ({exc}); rendering empty state.")

    orders_by_buyer: dict[str, list[dict]] = {}
    messages: list[dict] = []
    if token:
        try:
            print(f"  Fetching recent orders (last {args.days} days)...")
            orders_by_buyer = fetch_recent_orders(token, ebay_cfg, days_back=args.days)
        except Exception as exc:
            print(f"  GetOrders failed: {exc}")
        try:
            print(f"  Fetching unanswered tracking messages (last {args.days} days)...")
            messages = fetch_unanswered_messages(token, ebay_cfg, days_back=args.days)
        except Exception as exc:
            print(f"  GetMyMessages failed: {exc}")

    order_count = sum(len(v) for v in orders_by_buyer.values())
    print(f"  GetOrders indexed {order_count} order(s) across "
          f"{len(orders_by_buyer)} buyer(s).")
    print(f"  Tracking-related unanswered messages: {len(messages)}")

    drafts = [draft_tracking_reply(m, match_message_to_order(m, orders_by_buyer))
              for m in messages]
    _write_json(PLAN_PATH, {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "order_count":   order_count,
        "buyer_count":   len(orders_by_buyer),
        "message_count": len(messages),
        "drafts":        drafts})

    if args.apply and drafts:
        if token is None:
            token = promote.get_access_token(ebay_cfg)
        print(f"\n  Sending {len(drafts)} tracking replies via Trading API...")
        sent: list[dict] = []
        for d in drafts:
            if not d.get("matched"):
                print(f"  → {d['message_id']}: skipped (no matched order)")
                continue
            stub = {"message_id": d["message_id"], "sender": d["sender"],
                    "item_id": d["item_id"]}
            rec = send_reply(token, stub, d["draft_reply"], ebay_cfg, dry_run=False)
            sent.append(rec)
            print(f"  → {d['message_id']}: ack={rec.get('ack')}")
        _append_history(sent)
    elif args.apply:
        print("\n  No tracking drafts to send.")
    else:
        print("\n  Dry run only. Re-run with --apply to send replies.")

    report = build_report(drafts, order_count)
    print(f"  Report: {report}")
    print(f"  Plan:   {PLAN_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
