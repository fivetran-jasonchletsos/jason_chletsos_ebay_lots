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
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<RelistFixedPriceItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <Item><ItemID>{item_id}</ItemID>'
        f'<ListingType>FixedPriceItem</ListingType>'
        f'<ListingDuration>GTC</ListingDuration></Item>\n'
        f'{price_block}'
        f'  <DeletedField>Item.BestOfferDetails</DeletedField>\n'
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
        err = root.find(f".//{NS}Errors")
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

_PAGE_CSS = (
    ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
    ".rl-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:18px 0 28px}"
    ".rl-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}"
    ".rl-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}"
    ".rl-kpi.bad::before{background:#ef4444}.rl-kpi.ok::before{background:#22c55e}.rl-kpi.warn::before{background:#facc15}"
    ".rl-kpi .n{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1}"
    ".rl-kpi .l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}"
    ".rl-note{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:0 0 24px}"
    ".rl-note h3{margin:0 0 6px;font-size:13px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}"
    ".rl-note ul{margin:0;padding-left:18px;color:var(--text)}"
    ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}"
    "table.rl-tbl{width:100%;border-collapse:collapse;font-size:13px}"
    ".rl-tbl th,.rl-tbl td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}"
    ".rl-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
    ".rl-tbl .item{width:280px}.rl-tbl .item img{width:64px;height:64px;object-fit:cover;border-radius:var(--r-sm);border:1px solid var(--border);float:left;margin-right:10px;background:var(--surface-2)}"
    ".rl-tbl .item .title{color:var(--text);font-weight:600;font-size:13px;line-height:1.35}"
    ".rl-tbl .item .iid{color:var(--text-dim);font-size:11px;font-family:'JetBrains Mono',monospace;margin-top:2px}"
    ".rl-tbl .price{font-family:'JetBrains Mono',monospace;color:var(--text);font-weight:600}"
    ".rl-tbl .suggest{font-family:'JetBrains Mono',monospace;color:var(--gold);font-weight:700}"
    ".rl-tbl .age{font-family:'JetBrains Mono',monospace;color:var(--text)}.rl-tbl .age.old{color:#ef4444}"
    ".row-actions{display:flex;flex-wrap:wrap;gap:8px}"
    ".btn{background:var(--surface-2);color:var(--text);border:1px solid var(--border);border-radius:var(--r-sm);padding:7px 12px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.06em;cursor:pointer;text-decoration:none;display:inline-block}"
    ".btn:hover{filter:brightness(1.1)}.btn.ok{background:#22c55e;color:#0a0a0a;border-color:#22c55e}"
    ".btn.no{background:#ef4444;color:#fff;border-color:#ef4444}.btn.gold{background:var(--gold);color:#0a0a0a;border-color:var(--gold)}"
    ".empty{color:var(--text-muted);padding:36px 28px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md);font-size:15px}"
    ".empty .big{font-family:'Bebas Neue',sans-serif;font-size:36px;color:var(--gold);display:block;margin-bottom:6px}"
)
_PAGE_JS = (
    "document.addEventListener('click',function(e){var b=e.target.closest('.btn[data-action]');if(!b)return;"
    "var act=b.getAttribute('data-action');var iid=b.getAttribute('data-item-id');"
    "if(!confirm('Confirm '+act+' on item '+iid+'?'))return;b.disabled=true;b.textContent='…';"
    "fetch('/ebay/relist-action',{method:'POST',headers:{'Content-Type':'application/json'},"
    "body:JSON.stringify({item_id:iid,action:act})}).then(function(r){return r.json();})"
    ".then(function(d){b.textContent=d&&d.ok?'Done ✓':'Failed';})"
    ".catch(function(){b.disabled=false;b.textContent=act;});});"
)
_PAGE_HEAD = f"<style>{_PAGE_CSS}</style><script>{_PAGE_JS}</script>"

def _row_html(plan: dict) -> str:
    iid     = _esc(plan.get("item_id") or "")
    title   = _esc(plan.get("title") or "(no title)")
    photos  = plan.get("photos") or []
    thumb   = (photos[0] if photos else
               (f"https://i.ebayimg.com/images/g/{iid}/s-l64.jpg" if iid else ""))
    end     = plan.get("end_date") or ""
    age     = _days_ago(end)
    age_cls = "old" if age >= 7 else ""
    orig    = float(plan.get("original_price") or 0)
    suggest = float(plan.get("suggested_price") or 0)
    ltype   = _esc(plan.get("listing_type") or "")
    view    = f"https://www.ebay.com/itm/{iid}" if iid else "#"
    img     = f'<img src="{_esc(thumb)}" alt="" loading="lazy">' if thumb else ""
    return (
        f"<tr><td class='item'>{img}<div class='title'>{title}</div>"
        f"<div class='iid'>item {iid or '—'} · {ltype}</div></td>"
        f"<td class='price'>${orig:.2f}</td>"
        f"<td class='age'>{_esc(end[:10])}</td>"
        f"<td class='age {age_cls}'>{age}d</td>"
        f"<td class='suggest'>${suggest:.2f}</td>"
        f"<td><div class='row-actions'>"
        f"<button class='btn ok' data-action='relist' data-item-id=\"{iid}\">Relist as FP</button>"
        f"<button class='btn gold' data-action='edit_relist' data-item-id=\"{iid}\">Edit then relist</button>"
        f"<button class='btn no' data-action='skip_permanent' data-item-id=\"{iid}\">Skip (delist)</button>"
        f"<a class='btn' href='{view}' target='_blank' rel='noopener'>View</a>"
        f"</div></td></tr>"
    )

def build_report(plans: list[dict], window_days: int) -> Path:
    run_ts    = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    count     = len(plans)
    total_val = sum(float(p.get("original_price") or 0) for p in plans)
    ages      = [_days_ago(p.get("end_date") or "") for p in plans]
    oldest    = max(ages) if ages else 0
    avg_age   = round(statistics.mean(ages), 1) if ages else 0.0

    if count == 0:
        body_rows = (
            "<div class='empty'><span class='big'>Zero unsold listings</span>"
            "Nothing to relist right now — every ended auction either sold "
            "or is still active.<br>As auctions end without bids, they'll "
            "surface here automatically.</div>"
        )
    else:
        body_rows = (
            "<div class='tbl-wrap'><table class='rl-tbl'><thead><tr>"
            "<th>Item</th><th>Original</th><th>Ended</th><th>Days ago</th>"
            "<th>Suggested FP</th><th>Action</th></tr></thead>"
            f"<tbody>{''.join(_row_html(p) for p in plans)}</tbody></table></div>"
        )

    kpis = (
        f"<div class='rl-kpi {'warn' if count else 'ok'}'><div class='n'>{count}</div><div class='l'>Unsold listings</div></div>"
        f"<div class='rl-kpi'><div class='n'>${total_val:,.2f}</div><div class='l'>Total unsold value</div></div>"
        f"<div class='rl-kpi {'bad' if oldest >= 7 else ''}'><div class='n'>{oldest}d</div><div class='l'>Oldest unsold</div></div>"
        f"<div class='rl-kpi'><div class='n'>{avg_age}d</div><div class='l'>Average days unsold</div></div>"
    )
    note = (
        f"<section class='rl-note'><h3>How this works</h3><ul>"
        f"<li>Pulls all ended-without-bid auctions via Trading <code>GetMyeBaySelling</code> "
        f"(<code>UnsoldList.Include=true</code>) for the past {window_days} days.</li>"
        f"<li>Suggests a Fixed-Price relist price: original BIN if set, else 2× the starting "
        f"bid (auctions usually open very low), else market median × 0.95.</li>"
        f"<li><b>Relist as FP</b> calls Trading <code>RelistFixedPriceItem</code>, which "
        f"takes the previous auction's ItemID and re-publishes it as a GTC Fixed-Price item "
        f"— photos, store category, item specifics, condition, shipping & returns carry over.</li>"
        f"<li>Run <code>python3 relist_agent.py --apply</code> to actually relist; otherwise "
        f"everything is dry-run.</li></ul></section>"
    )
    body = (
        f"<section class='hero'><h1>Relist Unsold</h1>"
        f"<p class='sub'>Last run: <code>{run_ts}</code> · window: <code>{window_days}d</code></p>"
        f"<div class='rl-kpis'>{kpis}</div></section>{note}{body_rows}"
    )
    html = promote.html_shell(f"Relist Unsold · {promote.SELLER_NAME}", body,
                              extra_head=_PAGE_HEAD, active_page="relist.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH

def main() -> int:
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

    report = build_report(plans, window_days=args.days)
    print(f"  Report: {report}")
    print(f"  Plan:   {PLAN_PATH}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
