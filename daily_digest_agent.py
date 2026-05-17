"""daily_digest_agent.py — morning briefing for JC at Harpua2001.

Reads existing JSON outputs (best-effort; missing files are skipped) and
renders a single newspaper-style page so JC doesn't have to bounce between
Seller Hub tabs over coffee.

Reads:
    sold_history.json
    output/listings_snapshot.json
    output/seller_hub_plan.json
    output/promoted_listings_plan.json
    output/best_offer_autorespond_history.json
    output/messages_plan.json
    repricing_history.json
    output/specifics_history.json
    output/photo_quality_plan.json
    output/listing_performance_plan.json   (optional, for rank-killer)

Writes:
    docs/daily.html

Usage:
    python3 daily_digest_agent.py
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

import promote

REPO_ROOT = Path(__file__).parent
OUTPUT_DIR = REPO_ROOT / "output"
DOCS_DIR = REPO_ROOT / "docs"
REPORT_PATH = DOCS_DIR / "daily.html"

SOLD_PATH = REPO_ROOT / "sold_history.json"
LISTINGS_PATH = OUTPUT_DIR / "listings_snapshot.json"
SELLER_HUB_PATH = OUTPUT_DIR / "seller_hub_plan.json"
PROMOTED_PATH = OUTPUT_DIR / "promoted_listings_plan.json"
BEST_OFFER_HIST_PATH = OUTPUT_DIR / "best_offer_autorespond_history.json"
MESSAGES_PATH = OUTPUT_DIR / "messages_plan.json"
REPRICING_HIST_PATH = REPO_ROOT / "repricing_history.json"
SPECIFICS_HIST_PATH = OUTPUT_DIR / "specifics_history.json"
PHOTO_QUALITY_PATH = OUTPUT_DIR / "photo_quality_plan.json"
LISTING_PERF_PATH = OUTPUT_DIR / "listing_performance_plan.json"


# ---------- helpers ------------------------------------------------------
def _load_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  ! could not read {path.name}: {exc}")
        return default


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def _money(n: Any) -> str:
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def _to_float(n: Any) -> float:
    try:
        return float(n)
    except (TypeError, ValueError):
        return 0.0


# ---------- metric computations ------------------------------------------
def revenue_windows(sold: list[dict], now: datetime) -> dict[str, Any]:
    cut_1 = now - timedelta(days=1)
    cut_7 = now - timedelta(days=7)
    cut_30 = now - timedelta(days=30)
    rev_1 = rev_7 = rev_30 = 0.0
    cnt_1 = cnt_7 = cnt_30 = 0
    yesterday_items: list[dict] = []
    for row in sold:
        dt = _parse_dt(row.get("sold_date"))
        if not dt:
            continue
        price = _to_float(row.get("sale_price"))
        qty = _to_float(row.get("quantity")) or 1.0
        gross = price * qty
        if dt >= cut_30:
            rev_30 += gross
            cnt_30 += 1
        if dt >= cut_7:
            rev_7 += gross
            cnt_7 += 1
        if dt >= cut_1:
            rev_1 += gross
            cnt_1 += 1
            yesterday_items.append(row)
    top = max(yesterday_items, key=lambda r: _to_float(r.get("sale_price")),
              default=None) if yesterday_items else None
    return {
        "yesterday_rev": round(rev_1, 2),
        "yesterday_orders": cnt_1,
        "rev_7d": round(rev_7, 2),
        "orders_7d": cnt_7,
        "rev_30d": round(rev_30, 2),
        "orders_30d": cnt_30,
        "top_earner": top,
        "yesterday_items": yesterday_items,
    }


def watcher_total(promoted: dict | None) -> int:
    if not promoted:
        return 0
    total = 0
    for d in promoted.get("decisions", []) or []:
        total += int(_to_float(d.get("watchers")))
    return total


def pending_offers_count(best_offer_hist: list[dict], now: datetime) -> int:
    cut = now - timedelta(days=1)
    n = 0
    for row in best_offer_hist or []:
        ts = _parse_dt(row.get("responded_at"))
        if ts and ts >= cut and (row.get("action") in ("leave", "counter")):
            n += 1
    return n


def repricings_today(reprice_hist: list[dict], now: datetime) -> int:
    cut = now - timedelta(days=1)
    n = 0
    for row in reprice_hist or []:
        ts = _parse_dt(row.get("applied_at"))
        if ts and ts >= cut and row.get("ok"):
            n += 1
    return n


def specifics_today(spec_hist: list[dict], now: datetime) -> int:
    cut = now - timedelta(days=1)
    n = 0
    for row in spec_hist or []:
        ts = _parse_dt(row.get("applied_at"))
        if ts and ts >= cut and row.get("ok"):
            n += 1
    return n


def rank_killer(listing_perf: dict | None,
                promoted: dict | None) -> dict | None:
    """Highest impressions x lowest CTR — the listing wasting the most reach."""
    if listing_perf:
        nh = (listing_perf.get("buckets") or {}).get("needs_help") or []
        if nh:
            return nh[0]
    # Fallback: promoted listings with 0 sales but watcher signal worst.
    if promoted:
        cands = [d for d in promoted.get("decisions", []) or []
                 if int(_to_float(d.get("sold_30d"))) == 0
                 and int(_to_float(d.get("watchers"))) >= 1]
        cands.sort(key=lambda d: -int(_to_float(d.get("watchers"))))
        if cands:
            d = cands[0]
            return {
                "title": d.get("title"),
                "item_id": d.get("item_id"),
                "url": d.get("url"),
                "impressions": None,
                "ctr_pct": None,
                "reason": f"{d.get('watchers')} watchers, 0 sales in 30d",
            }
    return None


def build_todo(*, photo_fail: int, msgs_pending: int,
               offers_pending: int, repriced: int, specifics: int,
               active: int, yesterday_orders: int) -> list[str]:
    todo: list[str] = []
    if photo_fail:
        todo.append(f"{photo_fail} listing{'s' if photo_fail != 1 else ''} "
                    f"need reshoot (Cassini wants 8+ photos at 1600px+).")
    if msgs_pending:
        todo.append(f"{msgs_pending} buyer message"
                    f"{'s' if msgs_pending != 1 else ''} waiting on a reply.")
    if offers_pending:
        todo.append(f"{offers_pending} Best Offer"
                    f"{'s' if offers_pending != 1 else ''} parked for manual "
                    "review — open Best Offer Inbox.")
    if repriced:
        todo.append(f"{repriced} item{'s' if repriced != 1 else ''} dropped "
                    "below market overnight — repricer already adjusted.")
    if specifics:
        todo.append(f"Item specifics added to {specifics} listing"
                    f"{'s' if specifics != 1 else ''} (better search reach).")
    if yesterday_orders == 0:
        todo.append("No sales yesterday — check repricing.html for stale "
                    "high-priced listings.")
    if active < 100:
        todo.append(f"Active listings down to {active} — time to scan more "
                    "inventory in scan_wizard.html.")
    if not todo:
        todo.append("Inbox is clean. Pour another cup and watch the "
                    "watchers roll in.")
    return todo[:8]


# ---------- HTML rendering -----------------------------------------------
_CSS = """<style>
.dd-hero{padding:32px 0 16px;border-bottom:1px solid var(--border);margin-bottom:24px}
.dd-hero .dateline{font-family:'JetBrains Mono',monospace;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:var(--text-muted);margin-bottom:6px}
.dd-hero h1{margin:0;font-family:'Bebas Neue',sans-serif;font-size:64px;letter-spacing:.01em;line-height:1.02}
.dd-hero h1 .accent{color:var(--gold)}
.dd-hero .sub{color:var(--text-muted);margin-top:8px;font-size:15px}
.dd-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:0 0 32px}
.dd-kpi{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:18px 20px;position:relative;overflow:hidden}
.dd-kpi::before{content:'';position:absolute;inset:0 auto 0 0;width:3px;background:var(--gold);opacity:.7}
.dd-kpi-n{font-family:'Bebas Neue',sans-serif;font-size:40px;color:var(--gold);line-height:1}
.dd-kpi-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:6px}
.dd-kpi-foot{color:var(--text-dim);font-size:11px;margin-top:8px;border-top:1px dashed var(--border);padding-top:8px}
.dd-grid{display:grid;grid-template-columns:1.4fr 1fr;gap:24px;margin-bottom:32px}
@media (max-width:900px){.dd-grid{grid-template-columns:1fr}}
.dd-section{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:20px 22px}
.dd-section h2{margin:0 0 14px;font-family:'Bebas Neue',sans-serif;font-size:28px;letter-spacing:.02em;color:var(--text)}
.dd-section h2 .tag{font-family:'JetBrains Mono',monospace;font-size:10px;letter-spacing:.16em;color:var(--text-muted);text-transform:uppercase;margin-left:10px;vertical-align:middle}
.dd-todo{list-style:none;padding:0;margin:0}
.dd-todo li{padding:10px 0;border-bottom:1px dashed var(--border);display:flex;align-items:flex-start;gap:10px;color:var(--text);font-size:14px}
.dd-todo li:last-child{border-bottom:none}
.dd-todo .box{display:inline-block;width:14px;height:14px;border:1.5px solid var(--gold);border-radius:3px;margin-top:2px;flex-shrink:0}
.dd-top{display:flex;gap:16px;align-items:stretch}
.dd-top .thumb{width:140px;height:140px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);flex-shrink:0;overflow:hidden;display:flex;align-items:center;justify-content:center}
.dd-top .thumb img{width:100%;height:100%;object-fit:cover}
.dd-top .thumb .ph{color:var(--text-dim);font-size:11px;text-align:center;padding:8px}
.dd-top .meta{flex:1;display:flex;flex-direction:column;justify-content:center}
.dd-top .meta .ttl{font-size:15px;color:var(--text);line-height:1.35;margin-bottom:8px;font-weight:600}
.dd-top .meta .price{font-family:'Bebas Neue',sans-serif;font-size:44px;color:var(--gold);line-height:1}
.dd-top .meta .order{font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-dim);margin-top:6px}
.dd-top a{color:var(--text);text-decoration:none}.dd-top a:hover{color:var(--gold)}
.dd-fix{list-style:none;padding:0;margin:0}
.dd-fix li{padding:12px 0;border-bottom:1px solid var(--border);display:flex;gap:12px;align-items:flex-start}
.dd-fix li:last-child{border-bottom:none}
.dd-fix .rank{font-family:'Bebas Neue',sans-serif;font-size:26px;color:var(--gold);width:28px;flex-shrink:0;line-height:1}
.dd-fix .body .ttl{font-size:13px;color:var(--text);line-height:1.35;margin-bottom:3px}
.dd-fix .body .why{font-size:11px;color:var(--text-muted);font-family:'JetBrains Mono',monospace}
.dd-fix a{color:var(--text);text-decoration:none}.dd-fix a:hover{color:var(--gold)}
.dd-empty{color:var(--text-muted);font-size:13px;padding:16px;background:var(--surface-2);border:1px dashed var(--border);border-radius:var(--r-sm);text-align:center}
.dd-foot{margin:32px 0 16px;padding:18px;background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-muted);text-align:center;letter-spacing:.06em}
.dd-foot code{color:var(--gold);background:var(--surface);padding:2px 6px;border-radius:3px}
</style>"""


def _kpi(value: str, label: str, foot: str) -> str:
    return (f"<div class='dd-kpi'><div class='dd-kpi-n'>{escape(value)}</div>"
            f"<div class='dd-kpi-l'>{escape(label)}</div>"
            f"<div class='dd-kpi-foot'>{escape(foot)}</div></div>")


def _top_earner_card(top: dict | None, snapshot_by_id: dict[str, dict]) -> str:
    if not top:
        return ("<div class='dd-empty'>No sales in the last 24 hours. "
                "When the next one closes it will land right here.</div>")
    pic = top.get("pic") or ""
    if not pic:
        snap = snapshot_by_id.get(str(top.get("item_id") or ""))
        if snap:
            pic = snap.get("pic") or ""
    title = (top.get("title") or "")[:120]
    price = _money(top.get("sale_price"))
    url = top.get("url") or ""
    order_id = top.get("order_id") or ""
    thumb = (f"<div class='thumb'><img src='{escape(pic)}' alt=''"
             " onerror=\"this.parentNode.innerHTML='<div class=ph>no image</div>'\""
             "></div>") if pic else "<div class='thumb'><div class='ph'>no image</div></div>"
    title_html = (f"<a href='{escape(url)}' target='_blank' rel='noopener'>"
                  f"{escape(title)}</a>") if url else escape(title)
    return (
        "<div class='dd-top'>"
        f"{thumb}"
        "<div class='meta'>"
        f"<div class='ttl'>{title_html}</div>"
        f"<div class='price'>{price}</div>"
        f"<div class='order'>order #{escape(str(order_id))}</div>"
        "</div></div>"
    )


def _attention_list(rank_killer_row: dict | None,
                    photo_fails: list[dict]) -> str:
    items: list[tuple[str, str, str]] = []  # (title, why, url)
    if rank_killer_row:
        impr = rank_killer_row.get("impressions")
        ctr = rank_killer_row.get("ctr_pct")
        if impr is not None and ctr is not None:
            why = (f"{int(_to_float(impr)):,} impressions · "
                   f"{_to_float(ctr):.2f}% CTR — rewrite title")
        else:
            why = rank_killer_row.get("reason") or "low engagement"
        items.append((rank_killer_row.get("title") or "(untitled)",
                      why, rank_killer_row.get("url") or ""))
    for l in photo_fails[:3 - len(items)]:
        rec = (l.get("recommendation") or "needs reshoot")[:90]
        items.append((l.get("title") or "(untitled)",
                      f"photo fail · {rec}", l.get("url") or ""))
    if not items:
        return ("<div class='dd-empty'>Nothing screaming for attention. "
                "Performance signals are quiet.</div>")
    rows = []
    for i, (title, why, url) in enumerate(items, 1):
        title_short = escape(title[:90])
        title_html = (f"<a href='{escape(url)}' target='_blank' rel='noopener'>"
                      f"{title_short}</a>") if url else title_short
        rows.append(
            f"<li><div class='rank'>{i}</div><div class='body'>"
            f"<div class='ttl'>{title_html}</div>"
            f"<div class='why'>{escape(why)}</div></div></li>"
        )
    return "<ul class='dd-fix'>" + "".join(rows) + "</ul>"


def render(metrics: dict, todo: list[str], top_earner_html: str,
           attention_html: str, now: datetime) -> str:
    dateline = now.strftime("%A · %B %d, %Y")
    ts = now.strftime("%Y-%m-%d %H:%M UTC")
    yest_rev = _money(metrics["yesterday_rev"])
    yest_orders = metrics["yesterday_orders"]
    headline = (f"Yesterday at <span class='accent'>{escape(promote.SELLER_NAME)}</span>"
                f" &mdash; <span class='accent'>{yest_rev}</span> in sales, "
                f"<span class='accent'>{yest_orders}</span> "
                f"order{'s' if yest_orders != 1 else ''}")
    hero = (
        f"<section class='dd-hero'>"
        f"<div class='dateline'>{escape(dateline)} &middot; morning briefing</div>"
        f"<h1>{headline}</h1>"
        f"<p class='sub'>One scroll, then back to packing boxes.</p>"
        f"</section>"
    )
    kpis = (
        _kpi(yest_rev, "Yesterday", f"{yest_orders} order(s) closed") +
        _kpi(_money(metrics["rev_7d"]), "7-day revenue",
             f"{metrics['orders_7d']} orders") +
        _kpi(_money(metrics["rev_30d"]), "30-day revenue",
             f"{metrics['orders_30d']} orders") +
        _kpi(str(metrics["active"]), "Active listings",
             f"{metrics['watchers']} total watchers")
    )
    kpis_html = f"<div class='dd-kpis'>{kpis}</div>"

    todo_items = "".join(
        f"<li><span class='box'></span><span>{escape(t)}</span></li>"
        for t in todo
    )
    todo_section = (
        "<section class='dd-section'>"
        f"<h2>Today's TODO<span class='tag'>{len(todo)} items</span></h2>"
        f"<ul class='dd-todo'>{todo_items}</ul></section>"
    )
    top_section = (
        "<section class='dd-section'>"
        "<h2>Top earner<span class='tag'>last 24h</span></h2>"
        f"{top_earner_html}</section>"
    )
    attention_section = (
        "<section class='dd-section' style='margin-top:24px'>"
        "<h2>Needs your attention<span class='tag'>top 3</span></h2>"
        f"{attention_html}</section>"
    )
    grid = (
        "<div class='dd-grid'>"
        f"<div>{todo_section}{attention_section}</div>"
        f"<div>{top_section}</div>"
        "</div>"
    )
    foot = (
        f"<div class='dd-foot'>Generated {escape(ts)} &mdash; "
        f"run <code>python3 daily_digest_agent.py</code> to refresh.</div>"
    )
    body = hero + kpis_html + grid + foot
    return promote.html_shell(
        f"Daily Digest · {promote.SELLER_NAME}",
        body, extra_head=_CSS, active_page="daily.html",
    )


# ---------- main ---------------------------------------------------------
def main() -> int:
    now = datetime.now(timezone.utc)
    print(f"  Daily digest @ {now.strftime('%Y-%m-%d %H:%M UTC')}")

    sold = _load_json(SOLD_PATH, [])
    listings = _load_json(LISTINGS_PATH, [])
    _load_json(SELLER_HUB_PATH, {})  # touch for graceful skip
    promoted = _load_json(PROMOTED_PATH, {})
    bo_hist = _load_json(BEST_OFFER_HIST_PATH, [])
    messages = _load_json(MESSAGES_PATH, {})
    reprice = _load_json(REPRICING_HIST_PATH, [])
    specifics = _load_json(SPECIFICS_HIST_PATH, [])
    photo_q = _load_json(PHOTO_QUALITY_PATH, {})
    listing_perf = _load_json(LISTING_PERF_PATH, {})

    rev = revenue_windows(sold if isinstance(sold, list) else [], now)
    active = len(listings) if isinstance(listings, list) else 0
    snapshot_by_id = {str(l.get("item_id")): l for l in listings
                      if isinstance(l, dict)}
    watchers = watcher_total(promoted if isinstance(promoted, dict) else None)
    msgs_pending = int(_to_float((messages or {}).get("count")))
    offers_pending = pending_offers_count(
        bo_hist if isinstance(bo_hist, list) else [], now)
    repriced = repricings_today(
        reprice if isinstance(reprice, list) else [], now)
    spec_today = specifics_today(
        specifics if isinstance(specifics, list) else [], now)
    pq_summary = (photo_q or {}).get("summary") or {}
    photo_fail = int(_to_float(pq_summary.get("fail")))
    photo_fail_listings = [l for l in (photo_q or {}).get("listings") or []
                           if l.get("status") == "fail"]
    rk = rank_killer(listing_perf if isinstance(listing_perf, dict) else None,
                     promoted if isinstance(promoted, dict) else None)

    metrics = {
        "yesterday_rev": rev["yesterday_rev"],
        "yesterday_orders": rev["yesterday_orders"],
        "rev_7d": rev["rev_7d"],
        "orders_7d": rev["orders_7d"],
        "rev_30d": rev["rev_30d"],
        "orders_30d": rev["orders_30d"],
        "active": active,
        "watchers": watchers,
    }
    todo = build_todo(
        photo_fail=photo_fail, msgs_pending=msgs_pending,
        offers_pending=offers_pending, repriced=repriced,
        specifics=spec_today, active=active,
        yesterday_orders=rev["yesterday_orders"],
    )
    top_html = _top_earner_card(rev["top_earner"], snapshot_by_id)
    attention_html = _attention_list(rk, photo_fail_listings)

    html = render(metrics, todo, top_html, attention_html, now)
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")

    print(f"  Yesterday: {_money(rev['yesterday_rev'])} on "
          f"{rev['yesterday_orders']} order(s)")
    print(f"  7-day: {_money(rev['rev_7d'])} | 30-day: {_money(rev['rev_30d'])}")
    print(f"  Active: {active} | Watchers: {watchers} | "
          f"Offers pending: {offers_pending} | Msgs: {msgs_pending}")
    print(f"  TODO items: {len(todo)}")
    print(f"  Wrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
