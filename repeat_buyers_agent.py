"""
repeat_buyers_agent.py — surface JC's repeat buyers so they can be VIP'd.

Pipeline:
    1. fetch_all_orders()        Trading API GetOrders, last 365 days
                                 (chunked into 90-day windows to dodge the
                                 eBay 90-day API ceiling)
    2. group_by_buyer()          aggregate per buyer_user_id (count, spend,
                                 first/last order, top category, items)
    3. tier_buyers()             VIP (5+ orders OR $200+ lifetime) /
                                 Repeat (2-4 orders) / One-and-done
    4. draft_thanks_message()    polite VIP/Repeat thank-you template
    5. send_promo_message()      Trading API AddMemberMessageAAQToPartner
                                 (dry-run by default)

Artifacts:
    output/repeat_buyers_plan.json   latest aggregated buyer data
    output/repeat_buyers_sent.json   append-only send log
    docs/buyers.html                 admin-only review UI

Usage:
    python3 repeat_buyers_agent.py                # dry run (default)
    python3 repeat_buyers_agent.py --apply        # send to VIP+Repeat
    python3 repeat_buyers_agent.py --apply --tier vip   # VIP only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT    = Path(__file__).parent
OUTPUT_DIR   = REPO_ROOT / "output"
PLAN_PATH    = OUTPUT_DIR / "repeat_buyers_plan.json"
SENT_PATH    = OUTPUT_DIR / "repeat_buyers_sent.json"
REPORT_PATH  = promote.OUTPUT_DIR / "buyers.html"

TRADING_URL  = "https://api.ebay.com/ws/api.dll"
EBAY_NS      = "urn:ebay:apis:eBLBaseComponents"
NS           = "{" + EBAY_NS + "}"
COMPAT       = "967"
SITE_ID      = "0"

VIP_MIN_ORDERS  = 5
VIP_MIN_SPEND   = 200.0
REPEAT_MIN      = 2
THANK_CODE      = "THANKS5"
PROMO_SUBJECT   = "Thank you from Harpua2001 — first dibs on new cards"

PACE_SEC, MAX_RETRIES, BACKOFF_BASE_SEC = 0.4, 3, 1.5


# ---------------------------------------------------------------------------
# I/O helpers
# ---------------------------------------------------------------------------

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


def _append_sent(entries: list[dict]) -> None:
    if not entries:
        return
    h = _read_json(SENT_PATH, [])
    h = h if isinstance(h, list) else []
    h.extend(entries)
    _write_json(SENT_PATH, h)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Trading API plumbing
# ---------------------------------------------------------------------------

def _trading_headers(call_name: str, ebay_cfg: dict) -> dict[str, str]:
    return {
        "X-EBAY-API-SITEID": SITE_ID,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-APP-NAME":  ebay_cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME":  ebay_cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME": ebay_cfg.get("client_secret", ""),
        "Content-Type": "text/xml",
    }


def _trading_post(call_name: str, xml_body: str, ebay_cfg: dict) -> ET.Element:
    headers = _trading_headers(call_name, ebay_cfg)
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(TRADING_URL, headers=headers,
                              data=xml_body.encode("utf-8"), timeout=30)
            if 500 <= r.status_code < 600:
                raise RuntimeError(f"HTTP {r.status_code}")
            return ET.fromstring(r.text)
        except Exception as exc:
            last = exc
            sleep_s = BACKOFF_BASE_SEC * (2 ** attempt)
            print(f"  [{call_name}] attempt {attempt+1} failed: {exc} — "
                  f"sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"{call_name} failed after {MAX_RETRIES} retries: {last}")


def _parse_errors(root: ET.Element) -> list[dict]:
    return [{
        "code":     err.findtext(f"{NS}ErrorCode", "") or "",
        "severity": err.findtext(f"{NS}SeverityCode", "") or "",
        "msg":      err.findtext(f"{NS}ShortMessage", "") or "",
    } for err in root.findall(f".//{NS}Errors")]


# ---------------------------------------------------------------------------
# Step 1 — fetch orders (paginated, chunked over 90-day windows)
# ---------------------------------------------------------------------------

def _xml_get_orders(token: str, start: datetime, end: datetime, page: int) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetOrdersRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <CreateTimeFrom>{start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeFrom>\n'
        f'  <CreateTimeTo>{end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeTo>\n'
        f'  <OrderRole>Seller</OrderRole>\n'
        f'  <OrderStatus>All</OrderStatus>\n'
        f'  <Pagination><EntriesPerPage>100</EntriesPerPage>'
        f'<PageNumber>{page}</PageNumber></Pagination>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'</GetOrdersRequest>'
    )


def _fetch_window(token: str, ebay_cfg: dict,
                  start: datetime, end: datetime) -> list[dict]:
    """Page through one ≤90-day window and flatten to per-line-item rows."""
    out: list[dict] = []
    page = 1
    while True:
        root = _trading_post("GetOrders",
                             _xml_get_orders(token, start, end, page), ebay_cfg)
        if root.findtext(f"{NS}Ack") not in ("Success", "Warning"):
            for e in _parse_errors(root):
                print(f"  GetOrders error: [{e['code']}] {e['msg']}")
            break

        for order in root.findall(f".//{NS}Order"):
            order_id = order.findtext(f"{NS}OrderID", "") or ""
            buyer    = order.findtext(f"{NS}BuyerUserID", "") or ""
            created  = (order.findtext(f"{NS}CreatedTime", "")
                        or order.findtext(f"{NS}PaidTime", "") or "")
            country  = (order.findtext(
                f"{NS}ShippingAddress/{NS}Country", "") or "")

            for trans in order.findall(f".//{NS}Transaction"):
                item = trans.find(f"{NS}Item")
                if item is None:
                    continue
                item_id  = item.findtext(f"{NS}ItemID", "") or ""
                title    = item.findtext(f"{NS}Title", "") or ""
                category = (item.findtext(
                    f"{NS}PrimaryCategory/{NS}CategoryName", "") or "")
                price    = trans.findtext(f"{NS}TransactionPrice", "0") or "0"
                sold_at  = (trans.findtext(f"{NS}CreatedDate", "")
                            or created)
                try:
                    price_f = float(price)
                except (TypeError, ValueError):
                    price_f = 0.0
                if not buyer:
                    continue
                out.append({
                    "order_id":        order_id,
                    "buyer":           buyer,
                    "item_id":         item_id,
                    "item_title":      title,
                    "category":        category,
                    "sold_at":         sold_at,
                    "sale_price":      price_f,
                    "ship_to_country": country,
                })

        pr = root.find(f".//{NS}PaginationResult")
        total_pages = int(pr.findtext(f"{NS}TotalNumberOfPages", "1")) if pr is not None else 1
        if page >= total_pages:
            break
        page += 1
        time.sleep(PACE_SEC)
    return out


def fetch_all_orders(token: str, ebay_cfg: dict,
                     days_back: int = 365) -> list[dict]:
    """Pull every order in the last ``days_back`` days.

    eBay caps GetOrders at a 90-day window, so this loops over consecutive
    90-day chunks back through ``days_back``. Returns flattened rows with
    one entry per ``Transaction`` (so multi-item orders count fairly).
    """
    days_back = max(int(days_back), 1)
    now = datetime.now(timezone.utc)
    earliest = now - timedelta(days=days_back)

    rows: list[dict] = []
    seen: set[str] = set()  # de-dupe across overlapping windows
    cursor_end = now
    while cursor_end > earliest:
        cursor_start = max(cursor_end - timedelta(days=90), earliest)
        print(f"  GetOrders window: {cursor_start.date()} → "
              f"{cursor_end.date()}")
        chunk = _fetch_window(token, ebay_cfg, cursor_start, cursor_end)
        for r in chunk:
            uniq = f"{r['order_id']}:{r['item_id']}"
            if uniq in seen:
                continue
            seen.add(uniq)
            rows.append(r)
        # move window back; subtract one second so we don't double-count
        # the boundary row.
        cursor_end = cursor_start - timedelta(seconds=1)
    print(f"  Fetched {len(rows)} order rows from {len(seen)} unique lines.")
    return rows


# ---------------------------------------------------------------------------
# Step 2 — group by buyer
# ---------------------------------------------------------------------------

def group_by_buyer(orders: list[dict]) -> dict[str, dict]:
    """Aggregate per ``buyer_user_id``.

    Note: ``order_count`` counts distinct ``order_id`` values, not line
    items — a multi-card order still = one order.
    """
    by_buyer: dict[str, dict] = {}
    now = datetime.now(timezone.utc)
    for o in orders:
        buyer = o.get("buyer") or ""
        if not buyer:
            continue
        b = by_buyer.setdefault(buyer, {
            "buyer":             buyer,
            "order_ids":         set(),
            "order_count":       0,
            "line_item_count":   0,
            "lifetime_spend":    0.0,
            "first_order_date":  None,
            "last_order_date":   None,
            "items_bought":      [],
            "categories":        Counter(),
            "countries":         Counter(),
        })
        b["order_ids"].add(o.get("order_id") or "")
        b["line_item_count"] += 1
        b["lifetime_spend"]  += float(o.get("sale_price") or 0.0)
        sold_at = (o.get("sold_at") or "")[:19]
        if sold_at:
            if not b["first_order_date"] or sold_at < b["first_order_date"]:
                b["first_order_date"] = sold_at
            if not b["last_order_date"]  or sold_at > b["last_order_date"]:
                b["last_order_date"] = sold_at
        b["items_bought"].append({
            "item_id":    o.get("item_id"),
            "title":      o.get("item_title"),
            "sale_price": o.get("sale_price"),
            "sold_at":    sold_at,
        })
        if o.get("category"):
            b["categories"][o["category"]] += 1
        if o.get("ship_to_country"):
            b["countries"][o["ship_to_country"]] += 1

    out: dict[str, dict] = {}
    for buyer, b in by_buyer.items():
        b["order_count"] = len(b["order_ids"])
        b["order_ids"]   = sorted(b["order_ids"])
        b["lifetime_spend"] = round(b["lifetime_spend"], 2)
        top_cat = b["categories"].most_common(1)
        b["top_category"] = top_cat[0][0] if top_cat else ""
        b["categories"]   = dict(b["categories"])
        top_cty = b["countries"].most_common(1)
        b["top_country"]  = top_cty[0][0] if top_cty else ""
        b["countries"]    = dict(b["countries"])
        # days_since_last
        days = None
        if b["last_order_date"]:
            try:
                dt = datetime.fromisoformat(b["last_order_date"].replace("Z", ""))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days = (now - dt).days
            except ValueError:
                days = None
        b["days_since_last"] = days
        out[buyer] = b
    return out


# ---------------------------------------------------------------------------
# Step 3 — tier
# ---------------------------------------------------------------------------

def tier_buyers(grouped: dict[str, dict]) -> dict[str, dict]:
    """Annotate each buyer with a ``tier`` field and return the same map."""
    for buyer, b in grouped.items():
        oc = b.get("order_count", 0)
        spend = float(b.get("lifetime_spend") or 0.0)
        if oc >= VIP_MIN_ORDERS or spend >= VIP_MIN_SPEND:
            b["tier"] = "VIP"
        elif oc >= REPEAT_MIN:
            b["tier"] = "Repeat"
        else:
            b["tier"] = "One-and-done"
    return grouped


# ---------------------------------------------------------------------------
# Step 4 — draft message
# ---------------------------------------------------------------------------

def draft_thanks_message(buyer: dict) -> str:
    """Polite thank-you / first-look pitch for VIP+Repeat buyers."""
    n = buyer.get("order_count", 0)
    name = buyer.get("buyer", "")
    return (
        f"Hi {name}! Thanks for being a {n}-time customer. Just listed some "
        f"new cards you might like — first dibs before they hit the public "
        f"store: {promote.STORE_URL}. Use code {THANK_CODE} for 5% off your "
        f"next order over $20."
    )


# ---------------------------------------------------------------------------
# Step 5 — send message
# ---------------------------------------------------------------------------

def _xml_send_promo(token: str, recipient: str, item_id: str,
                    subject: str, body: str) -> str:
    safe_body = _esc(body)
    safe_subj = _esc(subject)
    item_block = f"<ItemID>{item_id}</ItemID>" if item_id else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<AddMemberMessageAAQToPartnerRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  {item_block}\n'
        f'  <MemberMessage>\n'
        f'    <Subject>{safe_subj}</Subject>\n'
        f'    <Body>{safe_body}</Body>\n'
        f'    <RecipientID>{recipient}</RecipientID>\n'
        f'    <QuestionType>General</QuestionType>\n'
        f'  </MemberMessage>\n'
        f'</AddMemberMessageAAQToPartnerRequest>'
    )


def send_promo_message(token: str, buyer: dict, body: str,
                       ebay_cfg: dict, dry_run: bool = True) -> dict:
    """Send a thank-you / promo message via AddMemberMessageAAQToPartner.

    Picks the buyer's most recent line-item as the ItemID context so the
    message threads under a real transaction (eBay AAQ requires either an
    ItemID or a matching member-message thread).
    """
    items = buyer.get("items_bought") or []
    item_id = ""
    if items:
        latest = max(items, key=lambda i: i.get("sold_at") or "")
        item_id = latest.get("item_id") or ""

    record: dict = {
        "sent_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "buyer":     buyer.get("buyer"),
        "tier":      buyer.get("tier"),
        "item_id":   item_id,
        "subject":   PROMO_SUBJECT,
        "body":      body,
        "dry_run":   dry_run,
        "ok": None, "ack": None, "errors": [],
    }
    if dry_run:
        record["ok"], record["ack"] = True, "DryRun"
        return record
    xml = _xml_send_promo(token, buyer.get("buyer") or "", item_id,
                          PROMO_SUBJECT, body)
    try:
        root = _trading_post("AddMemberMessageAAQToPartner", xml, ebay_cfg)
        ack = root.findtext(f"{NS}Ack", "") or ""
        record["ack"]    = ack
        record["errors"] = _parse_errors(root)
        record["ok"]     = ack in ("Success", "Warning")
    except Exception as exc:
        record["ok"]     = False
        record["errors"] = [{"code": "EXC", "severity": "Error", "msg": str(exc)}]
    time.sleep(PACE_SEC)
    return record


# ---------------------------------------------------------------------------
# Reporting — docs/buyers.html
# ---------------------------------------------------------------------------

_PAGE_CSS = (
    ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
    ".bk-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:18px 0 28px}"
    ".bk-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}"
    ".bk-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}"
    ".bk-kpi .n{font-family:'Bebas Neue',sans-serif;font-size:40px;color:var(--gold);line-height:1}"
    ".bk-kpi .l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}"
    ".bk-section-title{font-family:'Bebas Neue',sans-serif;font-size:28px;margin:28px 0 10px;letter-spacing:.04em}"
    ".bk-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 18px;color:var(--text-muted);font-size:13px}"
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}"
    "table.bk-tbl{width:100%;border-collapse:collapse;font-size:13px}"
    ".bk-tbl th,.bk-tbl td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}"
    ".bk-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
    ".bk-tbl .num{text-align:right;font-variant-numeric:tabular-nums}.bk-tbl .buyer{font-weight:600;color:var(--text)}"
    ".bk-tbl textarea{width:100%;min-width:280px;background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:10px 12px;font-family:inherit;font-size:12px;line-height:1.45;resize:vertical}"
    ".badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;font-weight:700}"
    ".badge.vip{background:rgba(234,179,8,.18);color:var(--gold,#facc15);border:1px solid rgba(234,179,8,.55)}"
    ".badge.rep{background:rgba(34,197,94,.12);color:var(--success,#22c55e);border:1px solid rgba(34,197,94,.4)}"
    ".badge.one{background:rgba(148,163,184,.12);color:var(--text-muted);border:1px solid var(--border)}"
    ".btn-send{background:var(--gold);color:#111;border:0;border-radius:var(--r-sm);padding:7px 13px;font-weight:700;cursor:pointer;text-transform:uppercase;letter-spacing:.06em;font-size:11px;margin-top:6px}"
    ".btn-send:hover{filter:brightness(1.08)}"
    ".empty{color:var(--text-muted);padding:28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}"
)
_PAGE_JS = (
    "document.addEventListener('click',function(e){var b=e.target.closest('.btn-send');if(!b)return;"
    "var id=b.getAttribute('data-buyer');var t=document.querySelector('textarea[data-buyer=\"'+id+'\"]');"
    "if(!t)return;b.disabled=true;b.textContent='Sending…';"
    "fetch('/ebay/send-promo',{method:'POST',headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({buyer:id,body:t.value})}).then(function(r){return r.json();})"
    ".then(function(d){b.textContent=d&&d.ok?'Sent ✓':'Failed';})"
    ".catch(function(){b.disabled=false;b.textContent='Send message';});});"
)
_PAGE_HEAD = f"<style>{_PAGE_CSS}</style><script>{_PAGE_JS}</script>"


def _tier_badge(tier: str) -> str:
    cls = {"VIP": "vip", "Repeat": "rep"}.get(tier, "one")
    return f"<span class='badge {cls}'>{_esc(tier)}</span>"


def _money(x: float) -> str:
    try:
        return f"${float(x):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _row(b: dict, with_message: bool) -> str:
    buyer = _esc(b.get("buyer") or "")
    days  = b.get("days_since_last")
    days_str = f"{days}d" if isinstance(days, int) else "—"
    if with_message:
        msg = _esc(draft_thanks_message(b))
        msg_cell = (f"<td><textarea data-buyer=\"{buyer}\" rows='4'>{msg}</textarea>"
                    f"<button class='btn-send' data-buyer=\"{buyer}\">Send message</button></td>")
    else:
        msg_cell = "<td><span style='color:var(--text-dim)'>—</span></td>"
    return (f"<tr><td>{_tier_badge(b.get('tier') or '')}</td>"
            f"<td class='buyer'>{buyer}</td>"
            f"<td class='num'>{b.get('order_count', 0)}</td>"
            f"<td class='num'>{_money(b.get('lifetime_spend', 0))}</td>"
            f"<td class='num'>{days_str}</td>"
            f"<td>{_esc((b.get('top_category') or '')[:60]) or '—'}</td>"
            f"{msg_cell}</tr>")


def _table(buyers: list[dict], with_message: bool) -> str:
    if not buyers:
        return "<p class='empty'>No buyers in this segment yet.</p>"
    msg_th = "Draft message" if with_message else "Message"
    head = ("<tr><th>Tier</th><th>Buyer</th><th class='num'>Orders</th>"
            "<th class='num'>Lifetime</th><th class='num'>Last seen</th>"
            f"<th>Top category</th><th>{msg_th}</th></tr>")
    body = "".join(_row(b, with_message) for b in buyers)
    return (f"<div class='tbl-wrap'><table class='bk-tbl'>"
            f"<thead>{head}</thead><tbody>{body}</tbody></table></div>")


def _kpi(n: str, l: str) -> str:
    return f"<div class='bk-kpi'><div class='n'>{n}</div><div class='l'>{l}</div></div>"


def build_report(buyers_map: dict[str, dict]) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    all_buyers = sorted(buyers_map.values(),
                        key=lambda b: (-(b.get("lifetime_spend") or 0),
                                       -(b.get("order_count") or 0)))
    vip     = [b for b in all_buyers if b.get("tier") == "VIP"]
    repeat  = [b for b in all_buyers if b.get("tier") == "Repeat"]
    onetime = [b for b in all_buyers if b.get("tier") == "One-and-done"]
    repeat_rev = sum((b.get("lifetime_spend") or 0) for b in all_buyers
                     if b.get("tier") in ("VIP", "Repeat"))
    total_rev  = sum((b.get("lifetime_spend") or 0) for b in all_buyers)
    n_top = max(1, round(len(all_buyers) * 0.10))
    top_rev = sum((b.get("lifetime_spend") or 0) for b in all_buyers[:n_top])
    pct_top = (top_rev / total_rev * 100.0) if total_rev > 0 else 0.0

    kpis = "".join([
        _kpi(str(len(all_buyers)), "Unique buyers"),
        _kpi(str(len(vip)),        "VIP (5+ orders or $200+)"),
        _kpi(str(len(repeat)),     "Repeat (2–4 orders)"),
        _kpi(str(len(onetime)),    "One-and-done"),
        _kpi(_money(repeat_rev),   "Revenue from repeats"),
        _kpi(f"{pct_top:.0f}%",    "Revenue from top 10%"),
    ])
    body = (
        f"<section class='hero'><h1>Repeat Buyers</h1>"
        f"<p class='sub'>Last run: <code>{run_ts}</code> · 365-day window · "
        f"grouped by <code>buyer_user_id</code></p>"
        f"<div class='bk-kpis'>{kpis}</div></section>"
        f"<section class='bk-note'>VIP+Repeat buyers each get a one-time "
        f"thank-you / first-look message. Code <code>{THANK_CODE}</code> is "
        f"generic — set up the coupon in eBay Seller Hub → Marketing → "
        f"Promotions before sending.</section>"
        f"<h2 class='bk-section-title'>VIP buyers</h2>{_table(vip, True)}"
        f"<h2 class='bk-section-title'>Repeat buyers</h2>{_table(repeat, True)}"
        f"<h2 class='bk-section-title'>One-and-done</h2>{_table(onetime, False)}"
    )
    html = promote.html_shell(f"Repeat Buyers · {promote.SELLER_NAME}", body,
                              extra_head=_PAGE_HEAD, active_page="buyers.html")
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(buyers_map: dict[str, dict]) -> None:
    all_buyers = sorted(buyers_map.values(),
                        key=lambda b: -(b.get("lifetime_spend") or 0))
    vip    = [b for b in all_buyers if b.get("tier") == "VIP"]
    repeat = [b for b in all_buyers if b.get("tier") == "Repeat"]
    onet   = [b for b in all_buyers if b.get("tier") == "One-and-done"]
    print()
    print(f"  Unique buyers : {len(all_buyers)}")
    print(f"  VIP           : {len(vip)}")
    print(f"  Repeat        : {len(repeat)}")
    print(f"  One-and-done  : {len(onet)}")
    print()
    print("  Top buyers by lifetime spend:")
    for b in all_buyers[:5]:
        print(f"    {b['buyer']:<24} "
              f"{b['order_count']:>3} orders  "
              f"{_money(b['lifetime_spend']):>10}  "
              f"[{b['tier']}]")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Surface JC's repeat buyers & draft VIP thank-you messages.")
    ap.add_argument("--apply", action="store_true",
                    help="Actually send messages (default: dry run).")
    ap.add_argument("--tier", choices=("vip", "repeat", "both"), default="both",
                    help="Which tier to send to with --apply.")
    ap.add_argument("--days", type=int, default=365,
                    help="How far back to scan (default 365).")
    args = ap.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    token: str | None = None
    try:
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Could not get access token ({exc}); rendering empty state.")

    orders: list[dict] = []
    if token:
        try:
            print(f"  Fetching orders (last {args.days} days)...")
            orders = fetch_all_orders(token, ebay_cfg, days_back=args.days)
        except Exception as exc:
            print(f"  GetOrders failed: {exc}")

    grouped = group_by_buyer(orders)
    grouped = tier_buyers(grouped)

    _write_json(PLAN_PATH, {
        "generated_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days_back":      args.days,
        "order_row_count": len(orders),
        "buyer_count":    len(grouped),
        "buyers":         list(grouped.values()),
    })

    _print_summary(grouped)
    report = build_report(grouped)
    print(f"\n  Report: {report}")
    print(f"  Plan:   {PLAN_PATH}")

    if args.apply:
        if token is None:
            token = promote.get_access_token(ebay_cfg)
        targets: list[dict]
        if args.tier == "vip":
            targets = [b for b in grouped.values() if b.get("tier") == "VIP"]
        elif args.tier == "repeat":
            targets = [b for b in grouped.values() if b.get("tier") == "Repeat"]
        else:
            targets = [b for b in grouped.values()
                       if b.get("tier") in ("VIP", "Repeat")]
        print(f"\n  Sending promo messages to {len(targets)} buyer(s) "
              f"[tier={args.tier}]...")
        sent: list[dict] = []
        for b in targets:
            body = draft_thanks_message(b)
            rec = send_promo_message(token, b, body, ebay_cfg, dry_run=False)
            sent.append(rec)
            print(f"  → {rec['buyer']}: ack={rec.get('ack')}")
        _append_sent(sent)
    else:
        print("\n  Dry run only. Re-run with --apply to send messages.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
