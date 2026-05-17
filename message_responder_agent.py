"""
message_responder_agent.py — surface unanswered buyer messages from eBay and
draft suggested replies via simple FAQ pattern matching.

Pipeline:
    1. fetch_messages()  → Trading API GetMyMessages (MessageStatus=Unanswered)
    2. draft_reply()     → FAQ classifier produces a suggested response,
                           pulling listing-specific facts from
                           output/specifics_plan.json when relevant.
    3. send_reply()      → Trading API AddMemberMessageAAQToPartner
                           (dry-run by default; --apply actually sends).

Artifacts:
    output/messages_plan.json     latest drafted replies
    output/messages_history.json  append-only send log
    docs/messages.html            admin-only review UI with editable drafts

Usage:
    python3 message_responder_agent.py            # dry run (default)
    python3 message_responder_agent.py --apply    # send via Trading API
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

REPO_ROOT      = Path(__file__).parent
OUTPUT_DIR     = REPO_ROOT / "output"
PLAN_PATH      = OUTPUT_DIR / "messages_plan.json"
HISTORY_PATH   = OUTPUT_DIR / "messages_history.json"
SPECIFICS_PATH = OUTPUT_DIR / "specifics_plan.json"
REPORT_PATH    = promote.OUTPUT_DIR / "messages.html"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT      = "967"
SITE_ID     = "0"

DEFAULT_DAYS_BACK = 30
PACE_SEC, MAX_RETRIES, BACKOFF_BASE_SEC = 0.4, 3, 1.5

# Canned FAQ snippets.
REPLY_SHIPPING = ("Thanks for reaching out! Ships within 1 business day via USPS "
                  "First-Class. Tracking is always provided. Combined shipping is "
                  "available — buy 2+ items and shipping caps at $5 total.")
REPLY_COMBINED = ("Yes — I offer combined shipping at $0.50 per additional item, "
                  "capped at $5 total. Add items to your cart and request a "
                  "combined invoice, or buy now and I'll refund any overage.")
REPLY_FALLBACK = ("Thanks for your message! I'll review and get back to you "
                  "shortly with details. — JC")
REPLY_RETURNS  = ("30-day returns accepted, buyer pays return shipping. Cards "
                  "ship in penny sleeves + top loaders inside a rigid mailer.")
REPLY_PAYMENT  = ("Payment is handled by eBay's managed payments — all standard "
                  "methods work. I ship as soon as payment clears.")

_PAGE_HEAD = "<style>" + (
    ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)} "
    ".msg-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:14px;margin:18px 0 28px} "
    ".msg-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden} "
    ".msg-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7} "
    ".msg-kpi .n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1} .msg-kpi .l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px} "
    ".msg-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 24px} .msg-note h3{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)} .msg-note ul{margin:0;padding-left:18px;color:var(--text)} "
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px} table.msg-tbl{width:100%;border-collapse:collapse;font-size:13px} "
    ".msg-tbl th,.msg-tbl td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top} .msg-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em} "
    ".msg-tbl .from{width:200px} .msg-tbl .from .sender{color:var(--text);font-weight:600} .msg-tbl .from .recv,.msg-tbl .from .iid{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px} "
    ".msg-tbl .msg .subj{color:var(--text);font-weight:600;margin-bottom:6px} .msg-tbl .msg .excerpt{color:var(--text-muted);white-space:pre-wrap;line-height:1.45} .msg-tbl .msg .cat{margin-top:8px} "
    ".badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:.08em} .badge.auto{background:rgba(34,197,94,.12);color:var(--success,#22c55e);border:1px solid rgba(34,197,94,.4)} .badge.manual{background:rgba(234,179,8,.12);color:var(--gold,#facc15);border:1px solid rgba(234,179,8,.4)} "
    ".msg-tbl .reply{width:38%} .msg-tbl textarea{width:100%;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 12px;font-family:inherit;font-size:13px;line-height:1.5;resize:vertical} "
    ".row-actions{display:flex;align-items:center;gap:10px;margin-top:8px} .row-actions .hint{color:var(--text-dim);font-size:11px} "
    ".btn-send{background:var(--gold);color:#111;border:0;border-radius:var(--r-sm);padding:8px 14px;font-weight:700;cursor:pointer;text-transform:uppercase;letter-spacing:.06em;font-size:12px} .btn-send:hover{filter:brightness(1.08)} "
    ".empty{color:var(--text-muted);padding:28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}"
) + "</style><script>" + (
    "document.addEventListener('click',function(e){var b=e.target.closest('.btn-send');if(!b)return;"
    "var id=b.getAttribute('data-msg-id');var t=document.querySelector('textarea[data-msg-id=\"'+id+'\"]');if(!t)return;"
    "b.disabled=true;b.textContent='Sending…';fetch('/ebay/send-reply',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({message_id:id,body:t.value})})"
    ".then(function(r){return r.json();}).then(function(d){b.textContent=d&&d.ok?'Sent ✓':'Failed';}).catch(function(){b.disabled=false;b.textContent='Send via eBay';});});"
) + "</script>"

def _read_json(path: Path, default):
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

def _load_specifics_index() -> dict[str, dict]:
    """item_id -> {current_specifics, title, url} from specifics_plan.json."""
    raw = _read_json(SPECIFICS_PATH, None)
    if not raw or not isinstance(raw, dict):
        return {}
    idx: dict[str, dict] = {}
    for p in raw.get("plans", []) or []:
        iid = str(p.get("item_id") or "")
        if iid:
            idx[iid] = {"title": p.get("title") or "",
                        "url": p.get("url") or "",
                        "current_specifics": p.get("current_specifics") or {}}
    return idx

def _trading_headers(call_name: str, ebay_cfg: dict) -> dict[str, str]:
    return {
        "X-EBAY-API-SITEID": SITE_ID, "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-APP-NAME":  ebay_cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME":  ebay_cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME": ebay_cfg.get("client_secret", ""),
        "Content-Type": "text/xml",
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

def _parse_errors(root: ET.Element) -> list[dict]:
    return [{
        "code":     err.findtext(f"{NS}ErrorCode", "") or "",
        "severity": err.findtext(f"{NS}SeverityCode", "") or "",
        "msg":      err.findtext(f"{NS}ShortMessage", "") or "",
    } for err in root.findall(f".//{NS}Errors")]

def _xml_get_headers(token: str, days_back: int) -> str:
    end   = datetime.now(timezone.utc)
    start = end - timedelta(days=days_back)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetMyMessagesRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <DetailLevel>ReturnHeaders</DetailLevel>\n'
        f'  <StartTime>{start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</StartTime>\n'
        f'  <EndTime>{end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</EndTime>\n'
        f'</GetMyMessagesRequest>'
    )

def _xml_get_bodies(token: str, ids: list[str]) -> str:
    ids_xml = "".join(f"<MessageID>{i}</MessageID>" for i in ids)
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetMyMessagesRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <DetailLevel>ReturnMessages</DetailLevel>\n'
        f'  <MessageIDs>{ids_xml}</MessageIDs>\n'
        f'</GetMyMessagesRequest>'
    )

def fetch_messages(token: str, ebay_cfg: dict,
                   days_back: int = DEFAULT_DAYS_BACK) -> list[dict]:
    """Return unanswered buyer messages from the last `days_back` days.

    Two-call pattern: GetMyMessages requires ReturnHeaders first, then a
    follow-up with MessageIDs to retrieve bodies.
    """
    root = _trading_post("GetMyMessages",
                         _xml_get_headers(token, days_back), ebay_cfg)
    fatal = [e for e in _parse_errors(root) if e["severity"] == "Error"]
    if fatal:
        print(f"  GetMyMessages (headers) errors: {fatal}")
        return []
    ids: list[str] = []
    for m in root.findall(f".//{NS}Messages/{NS}Message"):
        responded = (m.findtext(f"{NS}Responded") or "").lower() == "true"
        if responded:
            continue
        mid = m.findtext(f"{NS}MessageID", "") or ""
        if mid:
            ids.append(mid)
    if not ids:
        return []
    root = _trading_post("GetMyMessages",
                         _xml_get_bodies(token, ids), ebay_cfg)
    out: list[dict] = []
    for m in root.findall(f".//{NS}Messages/{NS}Message"):
        responded = (m.findtext(f"{NS}Responded") or "").lower() == "true"
        out.append({
            "message_id":  m.findtext(f"{NS}MessageID", "") or "",
            "ebay_msg_id": m.findtext(f"{NS}ExternalMessageID", "") or "",
            "sender":      m.findtext(f"{NS}Sender", "") or "",
            "recipient":   m.findtext(f"{NS}RecipientUserID", "") or "",
            "item_id":     m.findtext(f"{NS}ItemID", "") or "",
            "subject":     m.findtext(f"{NS}Subject", "") or "",
            "body":        (m.findtext(f"{NS}Text") or m.findtext(f"{NS}Content") or ""),
            "received_at": m.findtext(f"{NS}ReceiveDate", "") or "",
            "is_answered": responded,
        })
    return out

SHIPPING_RX = re.compile(r"\b(ship(ping)?|deliver(y|ed)?|how long|when (will|can)|tracking|arrive|usps|fedex)\b", re.I)
COMBINED_RX = re.compile(r"\b(combin(e|ed|ing)|bundle|multiple items?|cart|invoice|buy (more|two|three|2|3))\b", re.I)
CONDITION_RX = re.compile(r"\b(condition|raw|graded?|psa|bgs|cgc|sgc|slab|nm|near ?mint|mint|played|damaged?|surface)\b", re.I)
RETURN_RX   = re.compile(r"\b(return|refund|warranty|guarantee)\b", re.I)
PAYMENT_RX  = re.compile(r"\b(pay(ment|pal)?|venmo|cash app|method)\b", re.I)

def _condition_reply(item_id: str, listings: dict[str, dict]) -> tuple[str, bool]:
    """Build a condition reply from listing specifics; flag manual review if no data."""
    specs = (listings.get(str(item_id) or "") or {}).get("current_specifics") or {}
    graded  = (specs.get("Graded") or "").strip().lower()
    grade   = (specs.get("Grade") or "").strip()
    company = (specs.get("Professional Grader") or specs.get("Grader") or "").strip()
    if graded == "yes":
        bits = ["Graded"] + [b for b in (company, grade) if b]
        return (f"This card is {' '.join(bits)}. The slab is original from the "
                "grader and shown in the photos. Ships double-boxed with bubble "
                "wrap. Happy to send more close-up photos on request!", False)
    if graded == "no":
        return ("This one is raw (not professionally graded). Honest condition "
                "— please review the photos as the primary source of truth; any "
                "wear is called out in the description. Shipped in a penny "
                "sleeve + top loader inside a rigid mailer.", False)
    return ("Thanks for the question on condition — let me pull the card and "
            "double-check, I'll reply shortly with specifics.", True)

def draft_reply(message: dict, listings: dict[str, dict]) -> dict:
    """Classify message and produce a suggested reply."""
    text_l = ((message.get("body") or "") + " " +
              (message.get("subject") or "")).lower()
    category, body, manual = "other", REPLY_FALLBACK, True
    if COMBINED_RX.search(text_l):
        category, body, manual = "combined", REPLY_COMBINED, False
    elif SHIPPING_RX.search(text_l):
        category, body, manual = "shipping", REPLY_SHIPPING, False
    elif CONDITION_RX.search(text_l):
        body, manual = _condition_reply(message.get("item_id") or "", listings)
        category = "condition"
    elif RETURN_RX.search(text_l):
        category, body, manual = "returns", REPLY_RETURNS, False
    elif PAYMENT_RX.search(text_l):
        category, body, manual = "payment", REPLY_PAYMENT, False
    return {
        "message_id":  message.get("message_id"),
        "sender":      message.get("sender"),
        "item_id":     message.get("item_id"),
        "subject":     message.get("subject"),
        "body":        message.get("body"),
        "received_at": message.get("received_at"),
        "category":    category,
        "draft_reply": body,
        "needs_manual_review": manual,
    }

def _xml_send_reply(token: str, item_id: str, recipient: str,
                    parent_msg_id: str, body: str) -> str:
    safe = (body.replace("&", "&amp;").replace("<", "&lt;")
                 .replace(">", "&gt;"))
    parent_block = (f"<ParentMessageID>{parent_msg_id}</ParentMessageID>"
                    if parent_msg_id else "")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AddMemberMessageAAQToPartnerRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <ItemID>{item_id}</ItemID>\n'
        f'  <MemberMessage>\n'
        f'    <Subject>Re: your question</Subject>\n'
        f'    <Body>{safe}</Body>\n'
        f'    <RecipientID>{recipient}</RecipientID>\n'
        f'    <QuestionType>General</QuestionType>\n'
        f'    {parent_block}\n'
        f'  </MemberMessage>\n'
        f'</AddMemberMessageAAQToPartnerRequest>'
    )

def send_reply(token: str, message: dict, body: str, ebay_cfg: dict,
               dry_run: bool = True) -> dict:
    """Send a single reply via AddMemberMessageAAQToPartner."""
    record: dict = {
        "sent_at":    datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "message_id": message.get("message_id"),
        "recipient":  message.get("sender"),
        "item_id":    message.get("item_id"),
        "body":       body,
        "dry_run":    dry_run,
        "ok": None, "ack": None, "errors": [],
    }
    if dry_run:
        record["ok"], record["ack"] = True, "DryRun"
        return record
    xml = _xml_send_reply(token, message.get("item_id") or "",
                         message.get("sender") or "",
                         message.get("message_id") or "", body)
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

def build_report(drafts: list[dict]) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total  = len(drafts)
    manual = sum(1 for d in drafts if d.get("needs_manual_review"))
    auto   = total - manual

    if not drafts:
        rows_html = (
            "<p class='empty'>Inbox zero — no unanswered buyer messages in the "
            "last 30 days. New messages will appear here automatically.</p>"
        )
    else:
        def _row(d: dict) -> str:
            mid = _esc(d.get("message_id") or "")
            badge = ("<span class='badge manual'>needs review</span>"
                     if d.get("needs_manual_review")
                     else f"<span class='badge auto'>{_esc(d['category'])}</span>")
            return (
                f"<tr><td class='from'><div class='sender'>{_esc(d.get('sender') or '')}</div>"
                f"<div class='recv'>{_esc(d.get('received_at') or '')}</div>"
                f"<div class='iid'>item {_esc(d.get('item_id') or '—')}</div></td>"
                f"<td class='msg'><div class='subj'>{_esc(d.get('subject') or '(no subject)')}</div>"
                f"<div class='excerpt'>{_esc((d.get('body') or '')[:280])}</div>"
                f"<div class='cat'>{badge}</div></td>"
                f"<td class='reply'><textarea data-msg-id=\"{mid}\" rows='6'>"
                f"{_esc(d.get('draft_reply') or '')}</textarea>"
                f"<div class='row-actions'><button class='btn-send' data-msg-id=\"{mid}\">"
                f"Send via eBay</button><span class='hint'>Stub — wire to /ebay/send-reply Lambda.</span>"
                f"</div></td></tr>")
        rows_html = ("<div class='tbl-wrap'><table class='msg-tbl'><thead><tr>"
                     "<th>From</th><th>Message</th><th>Drafted Reply</th></tr></thead>"
                     f"<tbody>{''.join(_row(d) for d in drafts)}</tbody></table></div>")

    body = (
        f"<section class='hero'><h1>Buyer Messages</h1>"
        f"<p class='sub'>Last run: <code>{run_ts}</code></p>"
        f"<div class='msg-kpis'>"
        f"<div class='msg-kpi'><div class='n'>{total}</div><div class='l'>Unanswered</div></div>"
        f"<div class='msg-kpi'><div class='n'>{auto}</div><div class='l'>Auto-drafted</div></div>"
        f"<div class='msg-kpi'><div class='n'>{manual}</div><div class='l'>Needs review</div></div>"
        f"</div></section>"
        f"<section class='msg-note'><h3>How this works</h3><ul>"
        f"<li>Pulls unanswered messages from eBay (GetMyMessages, last 30 days).</li>"
        f"<li>Classifies into shipping / combined / condition / returns / payment.</li>"
        f"<li>Drafts a reply you can edit, then sends via AddMemberMessageAAQToPartner.</li>"
        f"</ul></section>{rows_html}"
    )

    html = promote.html_shell("Buyer Messages · Harpua2001", body,
                              extra_head=_PAGE_HEAD, active_page="messages.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Surface unanswered buyer messages + draft replies.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually send replies (default: dry run).")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS_BACK,
                    help=f"How far back to scan (default {DEFAULT_DAYS_BACK}).")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    listings = _load_specifics_index()
    print(f"  Loaded {len(listings)} listings from specifics_plan.json")

    token: str | None = None
    try:
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Could not get access token ({exc}); rendering empty state.")

    messages: list[dict] = []
    if token:
        try:
            print(f"  Fetching unanswered messages (last {args.days} days)...")
            messages = fetch_messages(token, ebay_cfg, days_back=args.days)
        except Exception as exc:
            print(f"  GetMyMessages failed: {exc}")
    print(f"  GetMyMessages returned {len(messages)} unanswered message(s).")

    drafts = [draft_reply(m, listings) for m in messages]
    _write_json(PLAN_PATH, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(drafts), "drafts": drafts,
    })

    if args.apply and drafts:
        if token is None:
            token = promote.get_access_token(ebay_cfg)
        print(f"\n  Sending {len(drafts)} replies via Trading API...")
        sent: list[dict] = []
        for d in drafts:
            if d.get("needs_manual_review"):
                print(f"  → {d['message_id']}: skipped (needs manual review)")
                continue
            msg = {"message_id": d["message_id"], "sender": d["sender"],
                   "item_id": d["item_id"]}
            rec = send_reply(token, msg, d["draft_reply"], ebay_cfg, dry_run=False)
            sent.append(rec)
            print(f"  → {d['message_id']}: ack={rec.get('ack')}")
        _append_history(sent)
    elif args.apply:
        print("\n  No drafts to send.")
    else:
        print("\n  Dry run only. Re-run with --apply to send replies.")

    report = build_report(drafts)
    print(f"  Report: {report}")
    print(f"  Plan:   {PLAN_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
