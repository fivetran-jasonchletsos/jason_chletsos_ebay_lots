"""best_offer_autorespond_agent.py — auto-respond to pending Best Offers.

best_offer_agent.py sets listing-level auto-accept/auto-decline thresholds; eBay
handles offers above/below those bands. This agent handles the middle band:
pulls pending offers, reads thresholds from output/best_offer_plan.json, and
decides accept | decline | counter | leave.

Per-offer logic:
    plan thresholds missing       → LEAVE (manual)
    offer >= accept_threshold     → ACCEPT
    offer <= decline_threshold    → DECLINE (polite message)
    accept > offer > decline      → COUNTER at (accept + offered) / 2

Usage:
    python3 best_offer_autorespond_agent.py           # dry run
    python3 best_offer_autorespond_agent.py --apply   # send responses

Artifacts:
    output/best_offer_autorespond_history.json
    docs/best_offer_inbox.html
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT    = Path(__file__).parent
OUTPUT_DIR   = REPO_ROOT / "output"
PLAN_PATH    = OUTPUT_DIR / "best_offer_plan.json"
HISTORY_PATH = OUTPUT_DIR / "best_offer_autorespond_history.json"
REPORT_PATH  = promote.OUTPUT_DIR / "best_offer_inbox.html"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT      = "967"
SITE_ID     = "0"

PACE_SEC         = 0.4
MAX_RETRIES      = 3
BACKOFF_BASE_SEC = 1.5

DECLINE_MESSAGE = ("Thanks so much for the offer! Unfortunately I can't go "
                   "that low on this one — feel free to send another.")

_ACTION_MAP = {"accept": "Accept", "decline": "Decline", "counter": "Counter"}
_BADGE = {"accept": ("Accept", "ok"), "decline": ("Decline", "no"),
          "counter": ("Counter", "warn"), "leave": ("Leave", "mute")}

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

def _load_plan_index() -> dict[str, dict]:
    raw = _read_json(PLAN_PATH, {}) or {}
    rows = raw.get("plan") if isinstance(raw, dict) else (raw or [])
    return {str(r.get("item_id") or ""): r for r in (rows or []) if r.get("item_id")}

def _append_history(entries: list[dict]) -> None:
    if not entries:
        return
    hist = _read_json(HISTORY_PATH, []) or []
    if not isinstance(hist, list):
        hist = []
    hist.extend(entries)
    _write_json(HISTORY_PATH, hist)

def _headers(call_name: str, ebay_cfg: dict) -> dict[str, str]:
    return {
        "X-EBAY-API-SITEID": SITE_ID,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT,
        "X-EBAY-API-CALL-NAME": call_name,
        "X-EBAY-API-APP-NAME": ebay_cfg.get("client_id", ""),
        "X-EBAY-API-DEV-NAME": ebay_cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME": ebay_cfg.get("client_secret", ""),
        "Content-Type": "text/xml",
    }

def _post(call_name: str, body: str, ebay_cfg: dict) -> ET.Element:
    headers = _headers(call_name, ebay_cfg)
    last_err: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(TRADING_URL, headers=headers,
                              data=body.encode("utf-8"), timeout=30)
            if 500 <= r.status_code < 600:
                raise RuntimeError(f"HTTP {r.status_code}")
            return ET.fromstring(r.text)
        except Exception as exc:
            last_err = exc
            sleep_s = BACKOFF_BASE_SEC * (2 ** attempt)
            print(f"  [{call_name}] attempt {attempt+1} failed: {exc} — "
                  f"sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"{call_name} failed after {MAX_RETRIES}: {last_err}")

def _parse_errors(root: ET.Element) -> list[dict]:
    return [{
        "code":     err.findtext(f"{NS}ErrorCode", "") or "",
        "severity": err.findtext(f"{NS}SeverityCode", "") or "",
        "msg":      err.findtext(f"{NS}ShortMessage", "") or "",
    } for err in root.findall(f".//{NS}Errors")]

def _txt(elem: ET.Element | None, tag: str) -> str:
    if elem is None:
        return ""
    return (elem.findtext(f"{NS}{tag}") or "").strip()

def _safe_float(s: str | None) -> float | None:
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None

def fetch_pending_offers(token: str, ebay_cfg: dict) -> list[dict]:
    """Pending Best Offers across all seller listings.

    Seller-wide GetBestOffers requires BestOfferStatus=All; filter client-side.
    """
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetBestOffersRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <BestOfferStatus>All</BestOfferStatus>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'</GetBestOffersRequest>'
    )
    root = _post("GetBestOffers", body, ebay_cfg)
    fatal = [e for e in _parse_errors(root) if e["severity"] == "Error"]
    if fatal:
        print(f"  GetBestOffers returned {len(fatal)} error(s):")
        for e in fatal:
            print(f"    {e['code']}: {e['msg']}")
        return []

    offers: list[dict] = []
    for bo in root.findall(f".//{NS}BestOffer"):
        status = _txt(bo, "Status")
        if status and status.lower() != "pending":
            continue
        price_el = bo.find(f"{NS}Price")
        buyer    = bo.find(f"{NS}Buyer")
        item_el  = bo.find(f"{NS}Item")
        cur_el = None
        if item_el is not None:
            cur_el = (item_el.find(f"{NS}SellingStatus/{NS}CurrentPrice")
                      or item_el.find(f"{NS}BuyItNowPrice")
                      or item_el.find(f"{NS}StartPrice"))
        offers.append({
            "offer_id":      _txt(bo, "BestOfferID"),
            "item_id":       _txt(item_el, "ItemID"),
            "title":         _txt(item_el, "Title"),
            "buyer_id":      _txt(buyer, "UserID") if buyer is not None else "",
            "offered_price": _safe_float(price_el.text if price_el is not None else None),
            "current_price": _safe_float(cur_el.text if cur_el is not None else None),
            "quantity":      _safe_float(_txt(bo, "Quantity")) or 1,
            "listed_at":     _txt(bo, "OfferTime"),
            "expires_at":    _txt(bo, "ExpirationTime"),
            "message":       _txt(bo, "BuyerMessage"),
            "status":        _txt(bo, "Status"),
        })
    return offers

def _round2(x: float) -> float:
    return round(x + 1e-9, 2)

def decide(offer: dict, listing_meta: dict | None) -> dict:
    offered = offer.get("offered_price") or 0.0
    out = {"action": "leave", "counter_price": None, "reason": "",
           "accept_thresh": None, "decline_thresh": None}
    if not listing_meta or listing_meta.get("decision") != "apply":
        out["reason"] = "no threshold data in best_offer_plan — leave for manual"
        return out
    accept_t  = listing_meta.get("auto_accept")
    decline_t = listing_meta.get("auto_decline")
    if accept_t is None or decline_t is None:
        out["reason"] = "thresholds missing — leave for manual"
        return out
    out["accept_thresh"]  = float(accept_t)
    out["decline_thresh"] = float(decline_t)
    if offered <= 0:
        out["reason"] = "missing offered price — leave for manual"
        return out
    if offered >= float(accept_t):
        out["action"] = "accept"
        out["reason"] = f"offer ${offered:.2f} ≥ accept ${float(accept_t):.2f}"
        return out
    if offered <= float(decline_t):
        out["action"] = "decline"
        out["reason"] = f"offer ${offered:.2f} ≤ decline ${float(decline_t):.2f}"
        return out
    counter = _round2((float(accept_t) + offered) / 2)
    list_price = listing_meta.get("price") or 0.0
    if list_price and counter > list_price:
        counter = _round2(list_price)
    out["action"]        = "counter"
    out["counter_price"] = counter
    out["reason"] = (f"in review band — counter at ${counter:.2f} "
                     f"(midpoint of accept ${float(accept_t):.2f} & offer ${offered:.2f})")
    return out

def respond(token: str, offer: dict, decision: dict, ebay_cfg: dict) -> dict:
    if decision["action"] not in _ACTION_MAP:
        return _record(offer, decision, ack="Skip", ok=True)
    action = _ACTION_MAP[decision["action"]]
    extra = ""
    if action == "Counter":
        extra = (f'  <CounterOfferPrice currencyID="USD">'
                 f'{decision["counter_price"]:.2f}</CounterOfferPrice>\n')
    seller_msg = ""
    if action == "Decline":
        seller_msg = f'  <SellerResponse>{escape(DECLINE_MESSAGE)}</SellerResponse>\n'
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<RespondToBestOfferRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <ItemID>{offer["item_id"]}</ItemID>\n'
        f'  <BestOfferID>{offer["offer_id"]}</BestOfferID>\n'
        f'  <Action>{action}</Action>\n{extra}{seller_msg}'
        f'</RespondToBestOfferRequest>'
    )
    try:
        root = _post("RespondToBestOffer", body, ebay_cfg)
        ack  = root.findtext(f"{NS}Ack", "") or ""
        return _record(offer, decision, ack=ack, ok=ack in ("Success", "Warning"),
                       errors=_parse_errors(root))
    except Exception as exc:
        return _record(offer, decision, ack=None, ok=False,
                       errors=[{"code": "EXC", "severity": "Error", "msg": str(exc)}])

def _decide_all(offers: list[dict],
                plan_idx: dict[str, dict]) -> list[tuple[dict, dict]]:
    return [(o, decide(o, plan_idx.get(str(o.get("item_id") or "")))) for o in offers]

def _summarize(decided: list[tuple[dict, dict]]) -> dict:
    counts = {"accept": 0, "decline": 0, "counter": 0, "leave": 0}
    uplift = 0.0
    for o, d in decided:
        counts[d["action"]] = counts.get(d["action"], 0) + 1
        if d["action"] == "accept" and o.get("offered_price"):
            uplift += float(o["offered_price"])
        elif d["action"] == "counter" and d.get("counter_price"):
            uplift += float(d["counter_price"]) - float(o.get("offered_price") or 0)
    return {"total": len(decided), **counts, "uplift": round(uplift, 2)}

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "—"

def _offer_row(o: dict, d: dict) -> str:
    label, klass = _BADGE.get(d["action"], ("?", "mute"))
    counter = _fmt_money(d.get("counter_price")) if d["action"] == "counter" else "—"
    msg = escape((o.get("message") or "")[:140])
    msg_html = f"<div class=msg>{msg}</div>" if msg else ""
    return (
        "<tr>"
        f"<td class='item'><span class='title'>{escape((o.get('title') or '')[:90])}</span>"
        f"<span class='item-id'>item {escape(str(o.get('item_id') or ''))}"
        f" · offer {escape(str(o.get('offer_id') or ''))}</span></td>"
        f"<td class='buyer'>{escape(o.get('buyer_id') or '')}</td>"
        f"<td class='num'>{_fmt_money(o.get('current_price'))}</td>"
        f"<td class='num offered'>{_fmt_money(o.get('offered_price'))}</td>"
        f"<td class='num'>{_fmt_money(d.get('accept_thresh'))}</td>"
        f"<td class='num'>{_fmt_money(d.get('decline_thresh'))}</td>"
        f"<td><span class='pill {klass}'>{label}</span></td>"
        f"<td class='num'>{counter}</td>"
        f"<td class='reason'>{escape(d.get('reason') or '')}{msg_html}</td>"
        f"</tr>"
    )

_CSS = (
    "<style>"
    ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
    ".bo-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px;margin:18px 0 28px}"
    ".bo-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}"
    ".bo-kpi::before{content:\"\";position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}"
    ".bo-kpi-n{font-family:'Bebas Neue',sans-serif;font-size:40px;color:var(--gold);line-height:1}"
    ".bo-kpi-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}"
    ".bo-kpi-foot{color:var(--text-dim);font-size:11px;margin-top:8px;border-top:1px dashed var(--border);padding-top:8px}"
    ".bo-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 24px}"
    ".bo-note h3{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}.bo-note ul{margin:0;padding-left:18px;color:var(--text)}"
    "h3 .count{color:var(--text-muted);font-weight:400;font-size:.7em}"
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}"
    "table.bo-tbl{width:100%;border-collapse:collapse;font-size:13px}"
    ".bo-tbl th,.bo-tbl td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}"
    ".bo-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
    ".bo-tbl tr:hover td{background:var(--surface-2)}.bo-tbl .num{text-align:right;font-variant-numeric:tabular-nums;font-family:'JetBrains Mono',monospace}"
    ".bo-tbl .offered{color:var(--gold);font-weight:600}.bo-tbl .item .title{display:block;color:var(--text)}"
    ".bo-tbl .item .item-id{display:block;color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px}"
    ".bo-tbl .buyer{font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-muted)}.bo-tbl .reason{color:var(--text-muted);font-size:12px;max-width:320px}"
    ".bo-tbl .reason .msg{margin-top:4px;padding:4px 6px;background:var(--surface-2);border-radius:4px;color:var(--text);font-style:italic}"
    ".pill{display:inline-block;padding:3px 9px;border-radius:999px;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.06em}"
    ".pill.ok{background:rgba(40,167,69,.15);color:var(--success)}.pill.no{background:rgba(220,53,69,.15);color:var(--danger)}"
    ".pill.warn{background:rgba(255,193,7,.15);color:var(--gold)}.pill.mute{background:var(--surface-2);color:var(--text-muted)}"
    ".empty{color:var(--text-muted);padding:28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}"
    "</style>"
)

def build_report(decided: list[tuple[dict, dict]],
                 summary: dict, dry_run: bool) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    mode   = "Dry run" if dry_run else "Applied"
    if decided:
        rows = "\n".join(_offer_row(o, d) for o, d in decided)
        table = (
            "<div class='tbl-wrap'><table class='bo-tbl'>"
            "<thead><tr><th>Listing</th><th>Buyer</th><th>List</th><th>Offered</th>"
            "<th>Accept ≥</th><th>Decline ≤</th><th>Action</th>"
            "<th>Counter</th><th>Reason</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )
    else:
        table = ("<p class='empty'>No pending Best Offers right now. "
                 "eBay's listing-level thresholds are doing the work — "
                 "this inbox lights up when an offer lands in the review band.</p>")

    def _kpi(n, lbl, foot):
        return (f"<div class='bo-kpi'><div class='bo-kpi-n'>{n}</div>"
                f"<div class='bo-kpi-l'>{lbl}</div>"
                f"<div class='bo-kpi-foot'>{foot}</div></div>")
    kpis = (
        _kpi(summary['total'],   "Reviewed",  "Pending offers polled this run") +
        _kpi(summary['accept'],  "Accepted",  "Offer ≥ accept threshold") +
        _kpi(summary['decline'], "Declined",  "Offer ≤ decline threshold") +
        _kpi(summary['counter'], "Countered", "Midpoint counter") +
        _kpi(_fmt_money(summary['uplift']), "Est. uplift",
             "Accept revenue + counter delta")
    )
    body = (
        f"<section class='hero'><h1>Best Offer Inbox</h1>"
        f"<p class='sub'>Last poll: <code>{run_ts}</code> · "
        f"Mode: <code>{mode}</code></p>"
        f"<div class='bo-kpis'>{kpis}</div></section>"
        "<section class='bo-note'><h3>How this works</h3><ul>"
        "<li><strong>best_offer_agent.py</strong> sets eBay's per-listing "
        "auto-accept (95% market) and auto-decline (75% market) thresholds.</li>"
        "<li>eBay handles offers above/below those bands automatically.</li>"
        "<li>Offers in the middle land here — we counter at the midpoint "
        "between the buyer's offer and the accept threshold.</li>"
        "<li>Listings without a plan entry are left for manual review.</li>"
        "</ul></section>"
        f"<h3>Inbox <span class='count'>({len(decided)})</span></h3>{table}"
    )
    html = promote.html_shell("Best Offer Inbox · Harpua2001",
                              body, extra_head=_CSS,
                              active_page="best_offer.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH

def _record(o: dict, d: dict, *, ack: str | None, ok: bool | None,
            errors: list[dict] | None = None) -> dict:
    return {
        "responded_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "offer_id":      o["offer_id"],
        "item_id":       o["item_id"],
        "title":         o.get("title", ""),
        "buyer_id":      o.get("buyer_id", ""),
        "offered_price": o.get("offered_price"),
        "current_price": o.get("current_price"),
        "action":        d["action"],
        "counter_price": d.get("counter_price"),
        "reason":        d["reason"],
        "ok": ok, "ack": ack, "errors": errors or [],
    }

def main() -> int:
    ap = argparse.ArgumentParser(description=(
        "Auto-respond to pending eBay Best Offers using best_offer_plan.json."))
    ap.add_argument("--apply", action="store_true",
                    help="Push RespondToBestOffer calls (default: dry run).")
    ap.add_argument("--limit", type=int, default=0,
                    help="Cap responses per run (0 = no cap).")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    plan_idx = _load_plan_index()
    print(f"  Loaded {len(plan_idx)} listings from best_offer_plan.json")
    try:
        print("  Fetching eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    except Exception as exc:
        print(f"  Token fetch failed ({exc}); aborting.")
        return 1

    print("  GetBestOffers (status=Pending)...")
    try:
        offers = fetch_pending_offers(token, ebay_cfg)
    except Exception as exc:
        print(f"  GetBestOffers failed ({exc}); rendering empty inbox.")
        offers = []
    print(f"  Found {len(offers)} pending offer(s)")

    decided = _decide_all(offers, plan_idx)
    summary = _summarize(decided)
    print(f"  Decisions: accept={summary['accept']}  decline={summary['decline']}"
          f"  counter={summary['counter']}  leave={summary['leave']}"
          f"  uplift≈{_fmt_money(summary['uplift'])}")

    if args.apply and decided:
        actionable = [(o, d) for o, d in decided if d["action"] in _ACTION_MAP]
        if args.limit > 0:
            actionable = actionable[:args.limit]
        print(f"\n  Responding to {len(actionable)} offer(s)...")
        responses: list[dict] = []
        for o, d in actionable:
            rec = respond(token, o, d, ebay_cfg)
            tag = "OK" if rec["ok"] else "FAIL"
            print(f"  → {d['action']:<7} offer {o['offer_id']}  "
                  f"ack={rec['ack']}  [{tag}]")
            responses.append(rec)
            time.sleep(PACE_SEC)
        _append_history(responses)
        ok_n = sum(1 for r in responses if r["ok"])
        print(f"\n  Result: {ok_n}/{len(responses)} responded successfully.")
    elif not decided:
        print("\n  Nothing to do — inbox empty.")
    else:
        print("\n  Dry run only. Re-run with --apply to send responses.")
        _append_history([_record(o, d, ack="DryRun", ok=None) for o, d in decided])

    report = build_report(decided, summary, dry_run=not args.apply)
    print(f"  Inbox:  {report}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
