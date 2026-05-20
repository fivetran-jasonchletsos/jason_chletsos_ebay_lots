"""
hub_pages_agent.py
==================

Consolidates the previously sprawling admin nav into four hub pages:

    photo_hub.html      – Photo Audit · Photo Quality · Photo Upload
    analytics_hub.html  – Make Money · Daily · Cassini · P&L · Listing Perf · Analytics
    cx_hub.html         – Messages · Tracking · Returns · Repeat Buyers · Watchers
    listings_hub.html   – Specifics · Title Review · Price Review · Repricing · Quality

Each hub renders:
  • a KPI strip (pulled from each component agent's plan JSON in output/)
  • big tile-links to the underlying pages (which remain reachable for deep-links)

Hubs link out — they do NOT embed.  Keeps build cheap, keeps every original
page intact and addressable.

The agent exposes:
    build_all_hubs()  -> list[Path]
        Builds all four hub pages.  Idempotent; safe to call from promote.py.

Run standalone:
    python3 hub_pages_agent.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import promote  # reuses html_shell + OUTPUT_DIR + SELLER_NAME


OUTPUT_DIR = promote.OUTPUT_DIR
SELLER_NAME = promote.SELLER_NAME
PLAN_DIR = Path(__file__).parent / "output"


# ---------------------------------------------------------------------------
# Plan-JSON readers — every component agent dumps a plan in output/.  Each
# helper returns a small dict of KPI-friendly numbers; missing JSON returns
# safe zero defaults so the hub still renders.
# ---------------------------------------------------------------------------

def _load_json(name: str) -> dict | list | None:
    p = PLAN_DIR / name
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def _len_decisions(plan: Any, key: str = "decisions") -> int:
    if isinstance(plan, dict):
        v = plan.get(key)
        if isinstance(v, list):
            return len(v)
        # some plans key by item_id → action
        if isinstance(v, dict):
            return len(v)
    if isinstance(plan, list):
        return len(plan)
    return 0


def _recompute_daily_todo_count() -> int:
    """Mirror daily_digest_agent.build_todo() length when daily_digest_plan.json
    is absent. daily_digest_agent.py only writes HTML, not JSON, so the hub
    re-derives the TODO count from the same source files. Cheap (all reads are
    small JSONs already on disk). Always returns >= 1 (fallback bucket)."""
    try:
        from datetime import datetime, timezone, timedelta
        root = Path(__file__).parent
        out = root / "output"

        def _read(path: Path, default):
            try:
                return json.loads(path.read_text()) if path.exists() else default
            except Exception:
                return default

        listings = _read(out / "listings_snapshot.json", [])
        sold     = _read(root / "sold_history.json", [])
        bo_hist  = _read(out / "best_offer_autorespond_history.json", [])
        messages = _read(out / "messages_plan.json", {})
        reprice  = _read(root / "repricing_history.json", [])
        specifics = _read(out / "specifics_history.json", [])
        photo_q  = _read(out / "photo_quality_plan.json", {})

        now = datetime.now(timezone.utc)
        cutoff_1d = now - timedelta(days=1)

        def _parse(ts):
            if not ts: return None
            try:
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            except Exception:
                return None

        yesterday_orders = sum(
            1 for r in (sold if isinstance(sold, list) else [])
            if isinstance(r, dict) and (_parse(r.get("sold_date")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff_1d
        )
        active = len(listings) if isinstance(listings, list) else 0
        msgs_pending = 0
        try:
            msgs_pending = int(float((messages or {}).get("count") or 0))
        except Exception:
            pass
        offers_pending = sum(
            1 for r in (bo_hist if isinstance(bo_hist, list) else [])
            if isinstance(r, dict)
            and (_parse(r.get("ts") or r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff_1d
            and r.get("action") in ("leave", "counter")
        )
        repriced = sum(
            1 for r in (reprice if isinstance(reprice, list) else [])
            if isinstance(r, dict)
            and (_parse(r.get("ts") or r.get("timestamp") or r.get("applied_at")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff_1d
        )
        spec_today = sum(
            1 for r in (specifics if isinstance(specifics, list) else [])
            if isinstance(r, dict)
            and (_parse(r.get("ts") or r.get("timestamp")) or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff_1d
        )
        pq_summary = (photo_q or {}).get("summary") or {}
        try:
            photo_fail = int(float(pq_summary.get("fail") or 0))
        except Exception:
            photo_fail = 0

        count = 0
        if photo_fail:     count += 1
        if msgs_pending:   count += 1
        if offers_pending: count += 1
        if repriced:       count += 1
        if spec_today:     count += 1
        if yesterday_orders == 0: count += 1
        if active < 100:   count += 1
        return count or 1  # "Inbox is clean" bucket — still one TODO row
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Hub spec: (slug, title, eyebrow, subtitle, KPI strip, tiles)
# Each "tile" = (href, label, icon, blurb)
# ---------------------------------------------------------------------------

def _photo_hub_spec() -> dict:
    audit  = _load_json("photo_audit.json") or {}
    pq     = _load_json("photo_quality_plan.json") or {}
    upload = _load_json("photo_upload_queue.json") or {}

    # photo_audit.json structure: typically {"results": [...]}, count flaggable
    audit_flagged = 0
    if isinstance(audit, dict):
        results = audit.get("results") or audit.get("flagged") or []
        if isinstance(results, list):
            audit_flagged = sum(
                1 for r in results
                if isinstance(r, dict) and (r.get("needs_reshoot") or r.get("score", 100) < 70)
            )
    quality_issues = _len_decisions(pq, "decisions") or _len_decisions(pq, "issues")
    upload_pending = _len_decisions(upload, "queue") or _len_decisions(upload, "decisions")

    kpis = [
        ("Reshoot priorities", audit_flagged, "warning"),
        ("Quality issues",     quality_issues, "danger"),
        ("Pending uploads",    upload_pending, "accent"),
    ]
    tiles = [
        ("photo_audit.html",   "Photo Audit",   "📷",
         "Per-listing photo coverage + reshoot priority list."),
        ("photo_quality.html", "Photo Quality", "🔍",
         "Resolution, lighting, background — automated quality grade."),
        ("photo_upload.html",  "Photo Upload",  "⬆️",
         "Queue + push fresh shots to the eBay listings that need them."),
    ]
    return {
        "slug":     "photo_hub.html",
        "title":    "Photo Hub",
        "eyebrow":  "Imagery",
        "subtitle": "Every photo workflow — audit, score, upload — in one place.",
        "kpis":     kpis,
        "tiles":    tiles,
    }


def _analytics_hub_spec() -> dict:
    pnl   = _load_json("pnl_plan.json") or _load_json("pnl_snapshot.json") or {}
    cass  = _load_json("cassini_score_plan.json") or {}
    daily = _load_json("daily_digest_plan.json") or {}
    lperf = _load_json("listing_performance_plan.json") or {}

    # ---- Revenue (30d) ------------------------------------------------------
    # Prefer pnl_plan.json (revenue_30d / totals.revenue_30d) if present.
    # Neither pnl_agent.py nor daily_digest_agent.py currently persists a plan
    # JSON — both render HTML only. Fall back to a tiny inline sum over
    # sold_history.json so the tile reflects reality on every hub build.
    revenue_30d = 0.0
    if isinstance(pnl, dict):
        revenue_30d = float(
            pnl.get("revenue_30d")
            or pnl.get("rev_30d")
            or pnl.get("totals", {}).get("revenue_30d", 0)
            or 0
        )
    if not revenue_30d:
        try:
            from datetime import datetime, timezone, timedelta
            sold_path = Path(__file__).parent / "sold_history.json"
            if sold_path.exists():
                sold = json.loads(sold_path.read_text())
                cutoff = datetime.now(timezone.utc) - timedelta(days=30)
                total = 0.0
                for r in sold if isinstance(sold, list) else []:
                    if not isinstance(r, dict):
                        continue
                    ts = r.get("sold_date") or ""
                    try:
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    except Exception:
                        continue
                    if dt < cutoff:
                        continue
                    try:
                        total += float(r.get("sale_price") or 0)
                    except (TypeError, ValueError):
                        pass
                revenue_30d = total
        except Exception:
            pass

    # ---- Cassini actions: actionable = red + yellow listings ---------------
    cassini_actions = 0
    if isinstance(cass, dict):
        summary = cass.get("summary") or {}
        if isinstance(summary, dict) and ("red" in summary or "yellow" in summary):
            cassini_actions = int(summary.get("red", 0) or 0) + int(summary.get("yellow", 0) or 0)
        else:
            rows = cass.get("rows")
            if isinstance(rows, list):
                cassini_actions = len(rows)
            else:
                cassini_actions = _len_decisions(cass)

    # ---- Daily-digest items: prefer plan file; else recompute TODO count ---
    daily_actions = _len_decisions(daily, "todo") or _len_decisions(daily, "actions") or _len_decisions(daily)
    if not daily_actions:
        daily_actions = _recompute_daily_todo_count()

    # ---- Underperformers ---------------------------------------------------
    underperf = 0
    if isinstance(lperf, dict):
        buckets = lperf.get("buckets") or {}
        needs_help = buckets.get("needs_help") if isinstance(buckets, dict) else None
        if isinstance(needs_help, list):
            underperf = len(needs_help)
        if not underperf:
            rc = lperf.get("row_count")
            if isinstance(rc, int):
                underperf = rc
        if not underperf:
            underperf = _len_decisions(lperf, "underperformers") or _len_decisions(lperf)

    kpis = [
        ("Revenue (30d)",      f"${revenue_30d:,.0f}", "accent"),
        ("Cassini actions",    cassini_actions,        "warning"),
        ("Daily-digest items", daily_actions,          ""),
        ("Underperformers",    underperf,              "danger"),
    ]
    tiles = [
        ("make_money.html",         "Make Money",   "💰",
         "Revenue rollup — five agents, projected 30-day uplift."),
        ("daily.html",              "Daily Digest", "📅",
         "What changed since yesterday: new listings, sold, watchers, offers."),
        ("cassini.html",            "Cassini Score","📈",
         "Per-listing search-rank score + the levers to move it."),
        ("pnl.html",                "P&L",          "🧾",
         "Cost basis, fees, shipping, net margin — by listing and rollup."),
        ("listing_performance.html","Listing Perf", "📊",
         "Views · watchers · impressions · CTR · sell-through."),
        ("analytics.html",          "Analytics",    "🧪",
         "Cross-listing trends, set heatmaps, market velocity."),
    ]
    return {
        "slug":     "analytics_hub.html",
        "title":    "Analytics Hub",
        "eyebrow":  "Diagnostics",
        "subtitle": "Every dashboard that answers 'what's happening?' in one nav.",
        "kpis":     kpis,
        "tiles":    tiles,
    }


def _cx_hub_spec() -> dict:
    messages = _load_json("messages_plan.json") or {}
    returns  = _load_json("returns_plan.json") or {}
    buyers   = _load_json("repeat_buyers_plan.json") or {}
    watchers = _load_json("watchers_offer_plan.json") or {}

    msg_pending     = _len_decisions(messages, "pending") or _len_decisions(messages)
    open_returns    = _len_decisions(returns, "open") or _len_decisions(returns)
    repeat_buyers   = _len_decisions(buyers, "buyers") or _len_decisions(buyers)
    watcher_offers  = _len_decisions(watchers, "offers") or _len_decisions(watchers)

    kpis = [
        ("Pending replies",   msg_pending,     "warning"),
        ("Open returns",      open_returns,    "danger"),
        ("Repeat buyers",     repeat_buyers,   "accent"),
        ("Watcher offers",    watcher_offers,  ""),
    ]
    tiles = [
        ("messages.html", "Messages",      "💬",
         "Inbox triage — auto-drafted replies, urgency ranked."),
        ("tracking.html", "Tracking",      "📦",
         "In-flight shipments + lateness alerts."),
        ("returns.html",  "Returns",       "↩️",
         "Open return cases + suggested action + refund math."),
        ("buyers.html",   "Repeat Buyers", "🧑‍🤝‍🧑",
         "Who came back, what they bought, what to offer next."),
        ("watchers.html", "Watchers",      "👀",
         "Active watchers, queueable offers, conversion rate."),
    ]
    return {
        "slug":     "cx_hub.html",
        "title":    "CX Hub",
        "eyebrow":  "Customer Service",
        "subtitle": "Messages, returns, tracking, buyer follow-up — single console.",
        "kpis":     kpis,
        "tiles":    tiles,
    }


def _listings_hub_spec() -> dict:
    specifics = _load_json("specifics_plan.json") or _load_json("specifics_cache.json") or {}
    titles    = _load_json("title_review_plan.json") or {}
    pricing   = _load_json("price_review_plan.json") or _load_json("pricing_cache.json") or {}
    repricing = _load_json("repricing_plan.json") or {}
    quality   = _load_json("quality_plan.json") or {}

    specifics_gaps  = _len_decisions(specifics, "gaps") or _len_decisions(specifics)
    title_changes   = _len_decisions(titles, "changes") or _len_decisions(titles)
    price_changes   = _len_decisions(pricing, "changes") or _len_decisions(pricing)
    repricing_moves = _len_decisions(repricing)
    quality_red     = _len_decisions(quality, "red") or _len_decisions(quality)

    kpis = [
        ("Specifics gaps",   specifics_gaps,  "warning"),
        ("Title fixes",      title_changes,   "accent"),
        ("Price moves",      repricing_moves or price_changes, ""),
        ("Quality reds",     quality_red,     "danger"),
    ]
    tiles = [
        ("specifics.html",    "Specifics",   "🏷️",
         "Item-specifics gap filler — pumps Cassini relevance score."),
        ("title_review.html", "Titles",      "✍️",
         "Title rewrite suggestions + side-by-side preview."),
        ("price_review.html", "Pricing",     "💲",
         "Price-vs-market sanity check, per listing."),
        ("repricing.html",    "Repricing",   "⚖️",
         "Planned price moves — review, then apply with one flag."),
        ("quality.html",      "Quality",     "🩺",
         "Listing health — photos, specifics, description, returns policy."),
    ]
    return {
        "slug":     "listings_hub.html",
        "title":    "Listings Hub",
        "eyebrow":  "Optimization",
        "subtitle": "Every lever that moves a listing's Cassini rank, one nav.",
        "kpis":     kpis,
        "tiles":    tiles,
    }


# ---------------------------------------------------------------------------
# Renderer
# ---------------------------------------------------------------------------

def _render_kpi_strip(kpis: list[tuple[str, Any, str]]) -> str:
    cards = []
    for label, value, tone in kpis:
        cls = f" {tone}" if tone else ""
        cards.append(f"""
        <div class="stat-card">
          <div class="num{cls}">{value}</div>
          <div class="lbl">{label}</div>
        </div>""")
    return f'<div class="stat-grid">{"".join(cards)}</div>'


def _render_tiles(tiles: list[tuple[str, str, str, str]]) -> str:
    cards = []
    for href, label, icon, blurb in tiles:
        cards.append(f"""
        <a class="hub-tile" href="{href}">
          <div class="hub-tile-head">
            <span class="hub-tile-icon">{icon}</span>
            <span class="hub-tile-title">{label}</span>
          </div>
          <div class="hub-tile-blurb">{blurb}</div>
          <div class="hub-tile-foot">{href} →</div>
        </a>""")
    return f'<div class="hub-grid">{"".join(cards)}</div>'


_HUB_CSS = """
.hub-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: 14px;
  margin-top: 18px;
}
.hub-tile {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--gold);
  border-radius: var(--r-lg);
  padding: 16px 18px;
  text-decoration: none;
  color: var(--text);
  display: flex; flex-direction: column; gap: 10px;
  transition: all var(--t-fast);
}
.hub-tile:hover {
  border-color: var(--border-mid);
  transform: translateY(-2px);
  box-shadow: var(--shadow-card);
}
.hub-tile-head { display: flex; align-items: center; gap: 10px; }
.hub-tile-icon { font-size: 22px; }
.hub-tile-title { font-weight: 700; font-size: 15px; letter-spacing: .01em; }
.hub-tile-blurb { color: var(--text-muted); font-size: 13px; line-height: 1.55; }
.hub-tile-foot {
  font-size: 11px; letter-spacing: .08em; text-transform: uppercase;
  color: var(--gold); font-family: 'JetBrains Mono', ui-monospace, monospace;
  border-top: 1px dashed var(--border); padding-top: 8px; margin-top: 4px;
}
.hub-note {
  margin-top: 22px; padding: 14px 16px;
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r-md);
  color: var(--text-muted); font-size: 12px; line-height: 1.6;
}
"""


def _build_hub(spec: dict) -> Path:
    body = f"""
    <div class="section-head">
      <div>
        <div class="eyebrow">{spec['eyebrow']}</div>
        <h1 class="section-title">{spec['title']}</h1>
        <div class="section-sub">{spec['subtitle']}</div>
      </div>
    </div>

    {_render_kpi_strip(spec['kpis'])}

    {_render_tiles(spec['tiles'])}

    <div class="hub-note">
      All sub-pages remain fully reachable at their original URLs — this hub
      is just the consolidated entry point. Deep-links from emails, bookmarks,
      and agents continue to work.
    </div>
    """
    out = OUTPUT_DIR / spec["slug"]
    out.write_text(
        promote.html_shell(
            f"{spec['title']} · {SELLER_NAME}",
            body,
            extra_head=f"<style>{_HUB_CSS}</style>",
            active_page=spec["slug"],
        ),
        encoding="utf-8",
    )
    print(f"  Hub built: {out}")
    return out


def build_all_hubs() -> list[Path]:
    """Build all four hub pages.  Returns the list of written paths."""
    return [
        _build_hub(_photo_hub_spec()),
        _build_hub(_analytics_hub_spec()),
        _build_hub(_cx_hub_spec()),
        _build_hub(_listings_hub_spec()),
    ]


if __name__ == "__main__":
    paths = build_all_hubs()
    print(f"\nBuilt {len(paths)} hub pages.")
