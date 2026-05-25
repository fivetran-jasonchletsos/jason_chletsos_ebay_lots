"""
orders_watch_agent.py — live "new sales" watch page for JC's morning coffee.

Pipeline:
    1. fetch_recent_orders()    Trading API GetOrders, last 30 days, newest first
    2. enrich_with_images()     join with output/listings_snapshot.json on item_id
    3. compute totals           today / 7d / 30d $$ and counts
    4. write JSON plan          output/orders_watch_plan.json  (canonical)
                                docs/orders_watch_plan.json    (for live JS poll)
    5. render docs/orders_watch.html using promote.html_shell

Usage:
    python3 orders_watch_agent.py
"""

from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Mark Messier'
AGENT_ROLE = 'Orders Watch'

import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

import promote
import chart_helpers

REPO_ROOT      = Path(__file__).parent
OUTPUT_DIR     = REPO_ROOT / "output"
PLAN_PATH      = OUTPUT_DIR / "orders_watch_plan.json"
DOCS_PLAN_PATH = promote.OUTPUT_DIR / "orders_watch_plan.json"
REPORT_PATH    = promote.OUTPUT_DIR / "orders_watch.html"
SNAPSHOT_PATH  = OUTPUT_DIR / "listings_snapshot.json"

TRADING_URL  = "https://api.ebay.com/ws/api.dll"
EBAY_NS      = "urn:ebay:apis:eBLBaseComponents"
NS           = "{" + EBAY_NS + "}"
COMPAT       = "967"
SITE_ID      = "0"

MAX_ORDERS      = 50
DAYS_BACK       = 30
PACE_SEC        = 0.4
MAX_RETRIES     = 3
BACKOFF_BASE    = 1.5


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
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            r = requests.post(TRADING_URL, headers=headers,
                              data=xml_body.encode("utf-8"), timeout=30)
            if 500 <= r.status_code < 600:
                raise RuntimeError(f"HTTP {r.status_code}")
            return ET.fromstring(r.text)
        except Exception as exc:
            last_exc = exc
            sleep_s = BACKOFF_BASE * (2 ** attempt)
            print(f"  [{call_name}] attempt {attempt+1} failed: {exc} — "
                  f"sleeping {sleep_s:.1f}s")
            time.sleep(sleep_s)
    raise RuntimeError(f"{call_name} failed after {MAX_RETRIES} retries: {last_exc}")


# ---------------------------------------------------------------------------
# Step 1 — fetch the most recent orders
# ---------------------------------------------------------------------------

def _xml_get_orders(token: str, start: datetime, end: datetime) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetOrdersRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <CreateTimeFrom>{start.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeFrom>\n'
        f'  <CreateTimeTo>{end.strftime("%Y-%m-%dT%H:%M:%S.000Z")}</CreateTimeTo>\n'
        f'  <OrderRole>Seller</OrderRole>\n'
        f'  <OrderStatus>All</OrderStatus>\n'
        f'  <Pagination><EntriesPerPage>{MAX_ORDERS}</EntriesPerPage>'
        f'<PageNumber>1</PageNumber></Pagination>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'</GetOrdersRequest>'
    )


def fetch_recent_orders(token: str, ebay_cfg: dict) -> list[dict]:
    """Pull the most recent ``MAX_ORDERS`` orders from the last ``DAYS_BACK`` days.

    Returns one row per line-item, newest-first, with at most ``MAX_ORDERS``
    rows in total.
    """
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=DAYS_BACK)
    root = _trading_post("GetOrders",
                         _xml_get_orders(token, start, now), ebay_cfg)
    ack = root.findtext(f"{NS}Ack", "") or ""
    if ack not in ("Success", "Warning"):
        for err in root.findall(f".//{NS}Errors"):
            print(f"  GetOrders error: "
                  f"[{err.findtext(f'{NS}ErrorCode', '')}] "
                  f"{err.findtext(f'{NS}ShortMessage', '')}")
        return []

    rows: list[dict] = []
    for order in root.findall(f".//{NS}Order"):
        order_id = order.findtext(f"{NS}OrderID", "") or ""
        buyer    = order.findtext(f"{NS}BuyerUserID", "") or ""
        created  = (order.findtext(f"{NS}CreatedTime", "")
                    or order.findtext(f"{NS}PaidTime", "") or "")
        addr = order.find(f"{NS}ShippingAddress")
        state = ""
        if addr is not None:
            state = (addr.findtext(f"{NS}StateOrProvince", "") or "").strip()

        for trans in order.findall(f".//{NS}Transaction"):
            item = trans.find(f"{NS}Item")
            if item is None:
                continue
            item_id = item.findtext(f"{NS}ItemID", "") or ""
            title   = item.findtext(f"{NS}Title", "") or ""
            price   = trans.findtext(f"{NS}TransactionPrice", "0") or "0"
            sold_at = (trans.findtext(f"{NS}CreatedDate", "") or created)
            try:
                price_f = float(price)
            except (TypeError, ValueError):
                price_f = 0.0
            rows.append({
                "order_id":    order_id,
                "item_id":     item_id,
                "item_title":  title,
                "image_url":   "",
                "sale_price":  price_f,
                "buyer":       buyer,
                "created_at":  sold_at,
                "ship_state":  state,
            })

    rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)
    return rows[:MAX_ORDERS]


# ---------------------------------------------------------------------------
# Step 2 — enrich with image_url from listings_snapshot.json
# ---------------------------------------------------------------------------

def _load_snapshot_pics() -> dict[str, str]:
    if not SNAPSHOT_PATH.exists():
        return {}
    try:
        data = json.loads(SNAPSHOT_PATH.read_text())
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    return {
        (row.get("item_id") or ""): (row.get("pic") or "")
        for row in data
        if isinstance(row, dict) and row.get("item_id")
    }


def enrich_with_images(orders: list[dict]) -> list[dict]:
    pic_map = _load_snapshot_pics()
    for o in orders:
        iid = o.get("item_id") or ""
        if not o.get("image_url") and iid in pic_map:
            o["image_url"] = pic_map[iid]
    return orders


# ---------------------------------------------------------------------------
# Step 3 — totals
# ---------------------------------------------------------------------------

def _parse_iso(s: str) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def compute_totals(orders: list[dict]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start  = now - timedelta(days=7)
    total_30d   = 0.0
    total_7d    = 0.0
    total_today = 0.0
    count_today = 0
    for o in orders:
        price = float(o.get("sale_price") or 0.0)
        total_30d += price
        dt = _parse_iso(o.get("created_at") or "")
        if dt is None:
            continue
        if dt >= week_start:
            total_7d += price
        if dt >= today_start:
            total_today += price
            count_today += 1
    return {
        "total_30d":   round(total_30d, 2),
        "total_7d":    round(total_7d, 2),
        "total_today": round(total_today, 2),
        "count_today": count_today,
    }


# ---------------------------------------------------------------------------
# Step 4 — write JSON plan
# ---------------------------------------------------------------------------

def write_plan(orders: list[dict], totals: dict[str, Any]) -> dict[str, Any]:
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "orders":       orders,
        **totals,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PLAN_PATH.write_text(json.dumps(plan, indent=2, default=str))
    # Mirror into docs/ so the live page can fetch it via a same-origin URL.
    promote.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DOCS_PLAN_PATH.write_text(json.dumps(plan, default=str))
    return plan


# ---------------------------------------------------------------------------
# Step 5 — render docs/orders_watch.html
# ---------------------------------------------------------------------------

_PAGE_CSS = """
.ow-wrap{max-width:920px;margin:0 auto;padding:16px 12px 64px}
.ow-hero{padding:18px 18px 14px;border-radius:var(--r-md);background:var(--surface);
  border:1px solid var(--border);margin-bottom:14px;text-align:center}
.ow-hero .big{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:500;font-variation-settings:'opsz' 144,'SOFT' 30,'WONK' 1;letter-spacing:-0.005em;font-size:clamp(56px,16vw,120px);
  line-height:.95;color:var(--gold);letter-spacing:.02em;margin:0}
.ow-hero .sub{color:var(--text-muted);font-size:14px;margin-top:6px;letter-spacing:.04em}
.ow-stamp{font-size:11px;color:var(--text-dim);margin-top:8px}
.ow-stamp .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
  background:#22c55e;margin-right:6px;vertical-align:middle;
  animation:ow-blink 1.6s ease-in-out infinite}
@keyframes ow-blink{0%,100%{opacity:.35}50%{opacity:1}}
.ow-kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:18px}
.ow-kpi{background:var(--surface);border:1px solid var(--border);
  border-radius:var(--r-md);padding:12px 10px;text-align:center}
.ow-kpi .n{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:500;font-variation-settings:'opsz' 144,'SOFT' 30,'WONK' 1;letter-spacing:-0.005em;font-size:clamp(22px,5vw,32px);
  color:var(--gold);line-height:1}
.ow-kpi .l{color:var(--text-muted);font-size:10px;text-transform:uppercase;
  letter-spacing:.08em;margin-top:4px}
@media (max-width:480px){.ow-kpis{grid-template-columns:repeat(2,1fr)}}
.ow-section-title{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:500;font-variation-settings:'opsz' 144,'SOFT' 30,'WONK' 1;letter-spacing:-0.005em;font-size:22px;letter-spacing:.04em;
  margin:18px 0 10px;color:var(--text)}
.ow-cards{display:flex;flex-direction:column;gap:10px}
.ow-card{display:flex;gap:12px;align-items:flex-start;background:var(--surface);
  border:1px solid var(--border);border-radius:var(--r-md);padding:10px;
  transition:border-color .25s ease, box-shadow .25s ease}
.ow-card.fresh{border-color:rgba(34,197,94,.55);
  box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:ow-pulse 2.2s ease-out infinite}
@keyframes ow-pulse{
  0%{box-shadow:0 0 0 0 rgba(34,197,94,.55)}
  70%{box-shadow:0 0 0 10px rgba(34,197,94,0)}
  100%{box-shadow:0 0 0 0 rgba(34,197,94,0)}
}
.ow-thumb{width:72px;height:72px;flex:0 0 72px;border-radius:8px;
  background:var(--surface-2) center/cover no-repeat;border:1px solid var(--border)}
.ow-meta{flex:1;min-width:0}
.ow-title{font-size:13.5px;line-height:1.3;color:var(--text);font-weight:600;
  display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.ow-row{display:flex;justify-content:space-between;align-items:baseline;
  margin-top:6px;gap:8px;flex-wrap:wrap}
.ow-price{font-family:'Fraunces',Georgia,serif;font-style:italic;font-weight:500;font-variation-settings:'opsz' 144,'SOFT' 30,'WONK' 1;letter-spacing:-0.005em;font-size:22px;color:var(--gold);
  letter-spacing:.02em}
.ow-buyer{font-size:11px;color:var(--text-muted);letter-spacing:.04em}
.ow-when{font-size:11px;color:var(--text-dim)}
.ow-empty{padding:36px 18px;text-align:center;border:1px dashed var(--border);
  border-radius:var(--r-md);color:var(--text-muted);background:var(--surface)}
@media (prefers-reduced-motion: reduce){
  .ow-stamp .dot{animation:none;opacity:1}
  .ow-card.fresh{animation:none}
}
""".strip()

_PAGE_JS = r"""
(function(){
  var PLAN_URL = 'orders_watch_plan.json';
  var POLL_MS  = 30000;

  function money(n){
    var v = Number(n||0);
    return '$' + v.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  }
  function escapeHtml(s){
    return String(s==null?'':s).replace(/[&<>"']/g, function(c){
      return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c];
    });
  }
  function timeAgo(iso){
    if(!iso) return '';
    var t = Date.parse(iso); if(isNaN(t)) return '';
    var s = Math.max(0, Math.floor((Date.now()-t)/1000));
    if(s<60)  return s+' sec ago';
    var m = Math.floor(s/60);  if(m<60)  return m+' min ago';
    var h = Math.floor(m/60);  if(h<24)  return h+' hr ago';
    var d = Math.floor(h/24);  return d+' day'+(d===1?'':'s')+' ago';
  }
  function isFresh(iso){
    if(!iso) return false;
    var t = Date.parse(iso); if(isNaN(t)) return false;
    return (Date.now()-t) < 3600*1000;
  }
  function render(plan){
    if(!plan) return;
    var heroN = document.getElementById('ow-hero-amount');
    var heroS = document.getElementById('ow-hero-sub');
    var count = plan.count_today || 0;
    heroN.textContent = money(plan.total_today);
    heroS.textContent = 'Today · ' + count + (count===1?' order':' orders');

    document.getElementById('ow-k-today-amt').textContent  = money(plan.total_today);
    document.getElementById('ow-k-today-cnt').textContent  = String(count);
    document.getElementById('ow-k-7d-amt').textContent     = money(plan.total_7d);
    document.getElementById('ow-k-30d-amt').textContent    = money(plan.total_30d);

    var stamp = document.getElementById('ow-stamp');
    if(stamp) stamp.innerHTML = '<span class="dot"></span>Live · last update ' +
      new Date().toLocaleTimeString();

    var host = document.getElementById('ow-cards');
    var orders = (plan.orders||[]);
    if(!orders.length){
      host.innerHTML =
        "<div class='ow-empty'>No orders yet today &mdash; Reddit post helps, store is set up tight</div>";
      return;
    }
    var rows = orders.map(function(o){
      var fresh = isFresh(o.created_at) ? ' fresh' : '';
      var img   = o.image_url
        ? "<div class='ow-thumb' style=\"background-image:url('" +
            escapeHtml(o.image_url) + "')\"></div>"
        : "<div class='ow-thumb'></div>";
      var state = o.ship_state ? (' &middot; ' + escapeHtml(o.ship_state)) : '';
      return "<article class='ow-card" + fresh + "'>" + img +
        "<div class='ow-meta'>" +
          "<div class='ow-title'>" + escapeHtml(o.item_title||'') + "</div>" +
          "<div class='ow-row'>" +
            "<span class='ow-price'>" + money(o.sale_price) + "</span>" +
            "<span class='ow-buyer'>" + escapeHtml(o.buyer||'') + state + "</span>" +
          "</div>" +
          "<div class='ow-when'>" + escapeHtml(timeAgo(o.created_at)) + "</div>" +
        "</div></article>";
    }).join('');
    host.innerHTML = rows;
  }

  function poll(){
    fetch(PLAN_URL + '?ts=' + Date.now(), {cache:'no-store'})
      .then(function(r){ return r.ok ? r.json() : null; })
      .then(render)
      .catch(function(){ /* swallow — keep polling */ });
  }

  // initial render from inline bootstrap if present
  try {
    var seed = window.__OW_BOOTSTRAP;
    if(seed) render(seed);
  } catch(e) {}

  poll();
  setInterval(poll, POLL_MS);

  // re-render time-since strings every 20s without re-fetching
  setInterval(function(){
    var when = document.querySelectorAll('.ow-card .ow-when[data-iso]');
    when.forEach(function(el){ el.textContent = timeAgo(el.getAttribute('data-iso')); });
  }, 20000);
})();
""".strip()


def _daily_revenue_chart(plan: dict[str, Any]) -> str:
    """Build a 30-day daily-revenue bar chart from the orders list."""
    today = datetime.now(timezone.utc).date()
    by_day: dict[str, float] = {}
    for o in plan.get("orders", []):
        ts = o.get("created_at") or ""
        try:
            d = datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
        except Exception:
            continue
        try:
            amt = float(o.get("sale_price") or 0)
        except (TypeError, ValueError):
            amt = 0.0
        key = d.isoformat()
        by_day[key] = by_day.get(key, 0.0) + amt

    rows = []
    for i in range(29, -1, -1):
        d = today - timedelta(days=i)
        key = d.isoformat()
        # 3-tuple: compact day-of-month tick on the axis, full date in the tooltip.
        rows.append((d.strftime("%-d"), by_day.get(key, 0.0), d.strftime("%b %-d")))
    # Today is always at the right edge (last row built), so it is always index 29.
    today_idx = 29
    chart = chart_helpers.bar_chart_vertical(
        rows,
        height=180,
        accent_index=today_idx,
        y_label="DAILY $",
    )
    return chart_helpers.card_wrapper(
        f"Revenue · last 30 days",
        f"30d ${plan.get('total_30d', 0):,.2f} · 7d ${plan.get('total_7d', 0):,.2f}",
        chart,
    )


def render_html(plan: dict[str, Any]) -> Path:
    bootstrap = json.dumps(plan, default=str)
    revenue_chart = _daily_revenue_chart(plan)
    body = f"""
<main class="ow-wrap">
  <section class="ow-hero">
    <div class="big" id="ow-hero-amount">$0.00</div>
    <div class="sub" id="ow-hero-sub">Today &middot; 0 orders</div>
    <div class="ow-stamp" id="ow-stamp"><span class="dot"></span>Live</div>
  </section>

  <section class="ow-kpis">
    <div class="ow-kpi"><div class="n" id="ow-k-today-amt">$0.00</div><div class="l">Today $</div></div>
    <div class="ow-kpi"><div class="n" id="ow-k-today-cnt">0</div><div class="l">Today orders</div></div>
    <div class="ow-kpi"><div class="n" id="ow-k-7d-amt">$0.00</div><div class="l">7-day $</div></div>
    <div class="ow-kpi"><div class="n" id="ow-k-30d-amt">$0.00</div><div class="l">30-day $</div></div>
  </section>

  {revenue_chart}

  <h2 class="ow-section-title">Live orders</h2>
  <div id="ow-cards" class="ow-cards"></div>
</main>
<script>window.__OW_BOOTSTRAP = {bootstrap};</script>
<script>{_PAGE_JS}</script>
""".strip()
    html = promote.html_shell(
        f"Orders Watch · {promote.SELLER_NAME}",
        body,
        extra_head=f"<style>{_PAGE_CSS}</style>",
        active_page="orders_watch.html",
    )
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(plan: dict[str, Any]) -> None:
    print()
    print(f"  Today        : ${plan['total_today']:.2f} across "
          f"{plan['count_today']} order(s)")
    print(f"  7-day total  : ${plan['total_7d']:.2f}")
    print(f"  30-day total : ${plan['total_30d']:.2f}")
    print(f"  Rows in plan : {len(plan.get('orders', []))}")
    print()


def main() -> int:
    print(f"  Mark Messier (Orders Watch) reporting in.")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    orders: list[dict] = []
    try:
        ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
        print("  Getting eBay access token...")
        token = promote.get_access_token(ebay_cfg)
        print(f"  Fetching most recent {MAX_ORDERS} orders (last {DAYS_BACK} days)...")
        orders = fetch_recent_orders(token, ebay_cfg)
        print(f"  Got {len(orders)} order row(s).")
    except Exception as exc:
        print(f"  Could not fetch orders ({exc}); rendering empty state.")

    orders = enrich_with_images(orders)
    totals = compute_totals(orders)
    plan = write_plan(orders, totals)
    _print_summary(plan)
    report = render_html(plan)
    print(f"  Plan:   {PLAN_PATH}")
    print(f"  Live:   {DOCS_PLAN_PATH}")
    print(f"  Page:   {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
