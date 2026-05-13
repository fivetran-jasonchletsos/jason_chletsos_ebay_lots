"""
repricing_agent.py — automated, guardrailed repricing for Harpua2001 listings.

Reads your active listings, sold history, market comps, multi-source pricing
(PriceCharting, PokemonTCG.io, eBay active), and locks. For each listing it
decides whether to raise, lower, or hold the price — subject to configurable
guardrails — then either previews the plan (dry run, default) or applies the
changes via the eBay Trading API ReviseItem call.

Usage:
    python repricing_agent.py                 # dry run — no eBay writes
    python repricing_agent.py --apply         # actually update prices on eBay
    python repricing_agent.py --apply --item 306913311444   # single listing
    python repricing_agent.py --no-fetch      # use cached listings.json snapshot
    python repricing_agent.py --report-only   # rebuild docs/repricing.html only

Artifacts:
    output/repricing_plan.json     latest plan (every decision, every reason)
    repricing_history.json         append-only log of applied changes
    docs/repricing.html            human-readable report
    repricing_config.json          tunable guardrails (created on first run)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests

import promote

REPO_ROOT          = Path(__file__).parent
CONFIG_PATH        = REPO_ROOT / "repricing_config.json"
HISTORY_PATH       = REPO_ROOT / "repricing_history.json"
LISTINGS_SNAPSHOT  = REPO_ROOT / "output" / "listings_snapshot.json"
PLAN_PATH          = REPO_ROOT / "output" / "repricing_plan.json"
REPORT_PATH        = promote.OUTPUT_DIR / "repricing.html"

DEFAULT_CONFIG: dict = {
    "enabled":              True,
    # Don't bother changing a price by less than this — avoids fee churn and
    # eBay's per-revision rate limits.
    "dead_zone_pct":        5.0,
    # Cap how far a single cycle can move a price. Protects against bad comps.
    "max_step_down_pct":    15.0,
    "max_step_up_pct":      25.0,
    # Hard floor regardless of comps. eBay's own floor is $0.99.
    "absolute_floor":       0.99,
    # Require this net (after fees + shipping) or we won't drop the price.
    "min_net_after_fees":   0.25,
    # Require this many comparable sales/comps before acting at all.
    "min_comp_count":       3,
    # Skip listings whose title contains any of these tokens (case-insensitive).
    # E.g. cards you've manually graded/priced and don't want algorithm touching.
    "skip_keywords":        [],
    # Cap how many price changes you'll push in one run. eBay throttles
    # ReviseItem calls aggressively for high-volume sellers.
    "max_changes_per_run":  25,
    # Rank of trusted sources, in order of preference for the "basis".
    "trust_sources":        ["sold_history", "pricecharting", "pokemontcg", "ebay_active"],
    # If True, require at least one "high-confidence" source (sold_history or
    # pricecharting) before lowering price. Active eBay comps alone don't count.
    "require_high_confidence_to_drop": True,
}


# --------------------------------------------------------------------------- #
# Config + history I/O                                                        #
# --------------------------------------------------------------------------- #

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2))
        print(f"  Created default config at {CONFIG_PATH.name}")
        return dict(DEFAULT_CONFIG)
    cfg = json.loads(CONFIG_PATH.read_text())
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def load_history() -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text())
    except json.JSONDecodeError:
        return []


def append_history(entries: list[dict]) -> None:
    if not entries:
        return
    history = load_history()
    history.extend(entries)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


# --------------------------------------------------------------------------- #
# Decision engine                                                             #
# --------------------------------------------------------------------------- #

def _is_lot(title: str) -> bool:
    return "lot" in title.lower()


def _ship_for(listing: dict) -> float:
    return promote.DEFAULT_SHIP_COST_HIGH if _is_lot(listing["title"]) else promote.DEFAULT_SHIP_COST_LOW


def _source_confidence(source_key: str, source_data: dict) -> str:
    """Return 'high', 'mid', or 'low' for a pricing source."""
    if source_key == "sold_history" and source_data.get("count", 0) >= 3:
        return "high"
    if source_key == "pricecharting":
        return "high"
    if source_key == "pokemontcg":
        return "mid"
    if source_key == "ebay_active":
        return "mid" if source_data.get("count", 0) >= 5 else "low"
    return "low"


def _best_basis(sources: dict, trust_order: list[str]) -> tuple[str | None, dict | None]:
    for k in trust_order:
        if k in sources and sources[k]:
            return k, sources[k]
    return None, None


def _cap_move(current: float, target: float, cfg: dict) -> tuple[float, list[str]]:
    """Clamp the proposed price to fit max-step guardrails. Returns (capped, trips)."""
    trips: list[str] = []
    if current <= 0:
        return target, trips
    delta_pct = (target - current) / current * 100
    if delta_pct < -cfg["max_step_down_pct"]:
        target = round(current * (1 - cfg["max_step_down_pct"] / 100), 2)
        trips.append(f"capped to max_step_down_pct={cfg['max_step_down_pct']}%")
    elif delta_pct > cfg["max_step_up_pct"]:
        target = round(current * (1 + cfg["max_step_up_pct"] / 100), 2)
        trips.append(f"capped to max_step_up_pct={cfg['max_step_up_pct']}%")
    return target, trips


def _round_psych(price: float) -> float:
    """Round to .99 ending, min $0.99."""
    if price < 1:
        return 0.99
    floor_d = int(price)
    if price - floor_d < 0.50:
        return max(0.99, round(floor_d - 0.01, 2))
    return round(floor_d + 0.99, 2)


def decide(listing: dict, market_row: dict, pricing_sources: dict,
           locks: dict, cfg: dict) -> dict:
    """
    Apply the full decision pipeline to a single listing.
    Returns a decision dict regardless of outcome (apply/skip/blocked).
    """
    item_id = listing["item_id"]
    try:
        current = float(listing.get("price") or 0)
    except (TypeError, ValueError):
        current = 0.0

    decision = {
        "item_id":            item_id,
        "title":              listing.get("title", ""),
        "current_price":      current,
        "target_price":       None,
        "delta_pct":          None,
        "decision":           "skip",
        "reasons":            [],
        "basis":              None,
        "basis_detail":       None,
        "confidence":         "low",
        "guardrails_tripped": [],
        "net_after_fees":     None,
        "url":                listing.get("url", ""),
    }

    # ---- Hard blocks ------------------------------------------------------- #
    if item_id in (locks.get("items") or {}):
        lock = locks["items"][item_id]
        decision["decision"] = "blocked"
        decision["reasons"].append(f"locked ({lock.get('reason', 'manual lock')})")
        return decision

    title_lower = (listing.get("title") or "").lower()
    for kw in cfg["skip_keywords"]:
        if kw.lower() in title_lower:
            decision["decision"] = "blocked"
            decision["reasons"].append(f"skip_keyword:{kw}")
            return decision

    if current <= 0:
        decision["decision"] = "blocked"
        decision["reasons"].append("no current price on listing")
        return decision

    # ---- Pick basis -------------------------------------------------------- #
    basis_key, basis_data = _best_basis(pricing_sources, cfg["trust_sources"])
    if not basis_key:
        decision["decision"] = "blocked"
        decision["reasons"].append("no pricing sources")
        return decision

    # Reference price from chosen source
    if basis_key == "sold_history":
        ref = basis_data.get("median")
        comp_count = basis_data.get("count", 0)
    elif basis_key == "ebay_active":
        ref = basis_data.get("median", 0) * 0.95
        comp_count = basis_data.get("count", 0)
    else:
        ref = basis_data.get("median")
        comp_count = basis_data.get("count", 1)

    if not ref or ref <= 0:
        decision["decision"] = "blocked"
        decision["reasons"].append(f"basis {basis_key} has no usable median")
        return decision

    if comp_count < cfg["min_comp_count"]:
        # Fallback to next source if this one is too thin
        # Build a trimmed trust order excluding insufficient ones
        fallback_order = [s for s in cfg["trust_sources"] if s != basis_key]
        for k in fallback_order:
            d = pricing_sources.get(k)
            if not d:
                continue
            if (d.get("count") or 0) >= cfg["min_comp_count"]:
                basis_key, basis_data = k, d
                if k == "ebay_active":
                    ref = d["median"] * 0.95
                else:
                    ref = d["median"]
                comp_count = d.get("count", 0)
                break
        else:
            decision["decision"] = "blocked"
            decision["reasons"].append(
                f"insufficient comps (need >={cfg['min_comp_count']}, got {comp_count} on {basis_key})"
            )
            return decision

    confidence = _source_confidence(basis_key, basis_data)
    decision["basis"] = basis_key
    decision["basis_detail"] = {
        "median":     basis_data.get("median"),
        "count":      comp_count,
        "reference":  round(ref, 2),
    }
    decision["confidence"] = confidence

    # ---- Propose target --------------------------------------------------- #
    target = _round_psych(ref)
    if target < cfg["absolute_floor"]:
        decision["decision"] = "blocked"
        decision["reasons"].append(f"target {target} below absolute_floor {cfg['absolute_floor']}")
        return decision

    # Cap by max step
    target_capped, trips = _cap_move(current, target, cfg)
    if trips:
        decision["guardrails_tripped"].extend(trips)
        # Re-round after cap so we still end on .99
        target_capped = _round_psych(target_capped)
    target = target_capped

    delta_pct = (target - current) / current * 100 if current > 0 else 0
    decision["target_price"] = target
    decision["delta_pct"] = round(delta_pct, 2)

    # ---- Net-after-fees floor (only matters when we'd be dropping) -------- #
    net = promote._ebay_net(target, _ship_for(listing))["net"]
    decision["net_after_fees"] = net
    if target < current and net < cfg["min_net_after_fees"]:
        decision["decision"] = "blocked"
        decision["reasons"].append(
            f"net ${net:.2f} would fall below min_net_after_fees ${cfg['min_net_after_fees']:.2f}"
        )
        return decision

    # ---- High-confidence requirement for drops ---------------------------- #
    if target < current and cfg["require_high_confidence_to_drop"] and confidence != "high":
        decision["decision"] = "blocked"
        decision["reasons"].append(
            f"drop requires high-confidence source; current basis {basis_key} is {confidence}"
        )
        return decision

    # ---- Dead-zone -------------------------------------------------------- #
    if abs(delta_pct) < cfg["dead_zone_pct"]:
        decision["decision"] = "skip"
        decision["reasons"].append(
            f"delta {delta_pct:.1f}% inside dead_zone_pct={cfg['dead_zone_pct']}%"
        )
        return decision

    decision["decision"] = "apply"
    decision["reasons"].append(
        f"{basis_key} median ${ref:.2f} (n={comp_count}, {confidence}) → target ${target:.2f}"
    )
    return decision


# --------------------------------------------------------------------------- #
# eBay write path                                                             #
# --------------------------------------------------------------------------- #

EBAY_NS = "urn:ebay:apis:eBLBaseComponents"


def revise_price(item_id: str, new_price: float, ebay_cfg: dict, token: str) -> dict:
    """Push a single StartPrice update via Trading API ReviseItem."""
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <StartPrice currencyID="USD">{new_price:.2f}</StartPrice>
  </Item>
</ReviseItemRequest>"""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "ReviseItem",
        "X-EBAY-API-APP-NAME":            ebay_cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            ebay_cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":           ebay_cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }
    r = requests.post("https://api.ebay.com/ws/api.dll",
                      headers=headers, data=xml_body.encode(), timeout=30)
    root = ET.fromstring(r.text)
    ack = root.findtext(f"{{{EBAY_NS}}}Ack", "")
    errors = []
    for err in root.findall(f".//{{{EBAY_NS}}}Errors"):
        sm = err.findtext(f"{{{EBAY_NS}}}ShortMessage", "") or ""
        code = err.findtext(f"{{{EBAY_NS}}}ErrorCode", "") or ""
        errors.append({"code": code, "msg": sm})
    return {
        "ack":     ack,
        "ok":      ack in ("Success", "Warning"),
        "errors":  errors,
        "http":    r.status_code,
    }


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    return f"${n:,.2f}"


def _fmt_pct(n) -> str:
    if n is None:
        return "—"
    sign = "+" if n > 0 else ""
    return f"{sign}{n:.1f}%"


def build_report(plan: list[dict], history: list[dict], cfg: dict) -> Path:
    """Render docs/repricing.html using promote.html_shell for theme consistency."""
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    by_decision: dict[str, list[dict]] = {"apply": [], "skip": [], "blocked": []}
    for d in plan:
        by_decision.setdefault(d["decision"], []).append(d)

    total_value_delta = sum(
        (d["target_price"] - d["current_price"])
        for d in by_decision["apply"]
        if d.get("target_price") and d.get("current_price")
    )

    def _row(d: dict) -> str:
        delta = d.get("delta_pct")
        delta_class = (
            "drop" if delta is not None and delta < 0
            else "rise" if delta is not None and delta > 0
            else "flat"
        )
        reasons = "<br>".join(d.get("reasons", []) or [])
        trips = "<br>".join(d.get("guardrails_tripped", []) or [])
        basis = d.get("basis") or "—"
        bd = d.get("basis_detail") or {}
        basis_str = (
            f"{basis} · n={bd.get('count', 0)} · ref ${bd.get('reference', 0):.2f}"
            if d.get("basis") else "—"
        )
        return f"""
        <tr class="row-{d['decision']}">
          <td class="item">
            <a href="{d['url']}" target="_blank" rel="noopener">
              <span class="title">{(d['title'] or '')[:90]}</span>
              <span class="item-id">{d['item_id']}</span>
            </a>
          </td>
          <td class="num">{_fmt_money(d['current_price'])}</td>
          <td class="num target">{_fmt_money(d.get('target_price'))}</td>
          <td class="num delta delta-{delta_class}">{_fmt_pct(delta)}</td>
          <td class="num">{_fmt_money(d.get('net_after_fees'))}</td>
          <td class="basis">{basis_str}<br><small class="conf-{d.get('confidence','low')}">{d.get('confidence','low')} confidence</small></td>
          <td class="reasons">{reasons}{('<br><em>'+trips+'</em>') if trips else ''}</td>
          <td class="decision decision-{d['decision']}">{d['decision'].upper()}</td>
        </tr>
        """

    def _section(title: str, items: list[dict]) -> str:
        if not items:
            return f"<h3>{title} <span class='count'>(0)</span></h3><p class='empty'>None.</p>"
        rows = "\n".join(_row(d) for d in items)
        return f"""
        <h3>{title} <span class='count'>({len(items)})</span></h3>
        <div class="tbl-wrap">
          <table class="reprice-tbl">
            <thead><tr>
              <th>Listing</th>
              <th>Now</th>
              <th>Target</th>
              <th>Δ</th>
              <th>Net@fees</th>
              <th>Basis</th>
              <th>Reasoning</th>
              <th>Decision</th>
            </tr></thead>
            <tbody>{rows}</tbody>
          </table>
        </div>
        """

    recent_history = list(reversed(history))[:50]
    hist_rows = "\n".join(
        f"<tr><td>{h.get('applied_at','')}</td>"
        f"<td><a href='{h.get('url','#')}' target='_blank'>{h.get('item_id')}</a></td>"
        f"<td class='num'>{_fmt_money(h.get('from_price'))}</td>"
        f"<td class='num'>{_fmt_money(h.get('to_price'))}</td>"
        f"<td class='num delta-{'drop' if (h.get('to_price') or 0)<(h.get('from_price') or 0) else 'rise'}'>"
        f"{_fmt_pct(h.get('delta_pct'))}</td>"
        f"<td>{h.get('basis','')}</td>"
        f"<td>{'OK' if h.get('ok') else 'FAIL: ' + (h.get('error') or '')}</td></tr>"
        for h in recent_history
    )
    history_block = (
        f"<div class='tbl-wrap'><table class='reprice-tbl'>"
        f"<thead><tr><th>Applied</th><th>Item</th><th>From</th><th>To</th><th>Δ</th><th>Basis</th><th>Result</th></tr></thead>"
        f"<tbody>{hist_rows}</tbody></table></div>"
        if recent_history else "<p class='empty'>No price changes applied yet.</p>"
    )

    body = f"""
<section class="hero">
  <h1>Repricing Agent</h1>
  <p class="sub">Last run: <code>{run_ts}</code></p>
  <div class="stat-grid">
    <div class="stat"><div class="stat-n">{len(by_decision['apply'])}</div><div class="stat-l">to apply</div></div>
    <div class="stat"><div class="stat-n">{len(by_decision['skip'])}</div><div class="stat-l">in dead zone</div></div>
    <div class="stat"><div class="stat-n">{len(by_decision['blocked'])}</div><div class="stat-l">blocked</div></div>
    <div class="stat"><div class="stat-n">{_fmt_money(total_value_delta)}</div><div class="stat-l">listed Δ</div></div>
  </div>
</section>

<section class="cfg">
  <h3>Active guardrails</h3>
  <ul class="cfg-list">
    <li>Dead zone: ±{cfg['dead_zone_pct']:.1f}%</li>
    <li>Max step down: {cfg['max_step_down_pct']:.0f}% · Max step up: {cfg['max_step_up_pct']:.0f}%</li>
    <li>Min comps: {cfg['min_comp_count']} · Min net after fees: {_fmt_money(cfg['min_net_after_fees'])}</li>
    <li>Drops require high-confidence source: {'yes' if cfg['require_high_confidence_to_drop'] else 'no'}</li>
    <li>Max changes per run: {cfg['max_changes_per_run']}</li>
  </ul>
  <p class="hint">Edit <code>repricing_config.json</code> at repo root to tune. Run: <code>python repricing_agent.py</code> (dry) or <code>--apply</code>.</p>
</section>

{_section('🎯 Will apply', by_decision['apply'])}
{_section('⊝ In dead zone (no-op)', by_decision['skip'])}
{_section('⛔ Blocked', by_decision['blocked'])}

<section>
  <h3>Recent change history</h3>
  {history_block}
</section>
"""

    extra_css = """
<style>
  .hero { padding: 24px 0 12px; }
  .hero h1 { margin: 0 0 4px; font-family: 'Bebas Neue', sans-serif; font-size: 56px; letter-spacing: .02em; }
  .hero .sub { color: var(--text-muted); }
  .stat-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 18px 0; }
  .stat { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 16px; }
  .stat-n { font-family: 'Bebas Neue', sans-serif; font-size: 36px; color: var(--gold); line-height: 1; }
  .stat-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 4px; }
  .cfg { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 18px 0; }
  .cfg h3 { margin: 0 0 8px; font-size: 14px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .cfg-list { list-style: none; padding: 0; margin: 0; display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 6px 18px; }
  .cfg-list li { color: var(--text); }
  .cfg .hint { color: var(--text-muted); font-size: 13px; margin: 10px 0 0; }
  h3 .count { color: var(--text-muted); font-weight: 400; font-size: .7em; }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.reprice-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .reprice-tbl th, .reprice-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .reprice-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .reprice-tbl tr:hover td { background: var(--surface-2); }
  .reprice-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .reprice-tbl .target { color: var(--gold); font-weight: 600; }
  .delta-drop { color: var(--danger); }
  .delta-rise { color: var(--success); }
  .delta-flat { color: var(--text-muted); }
  .conf-high { color: var(--success); }
  .conf-mid { color: var(--warning); }
  .conf-low { color: var(--text-dim); }
  .reprice-tbl .item .title { display: block; color: var(--text); }
  .reprice-tbl .item .item-id { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .reprice-tbl .item a { text-decoration: none; }
  .reprice-tbl .item a:hover .title { color: var(--gold); }
  .reprice-tbl .basis { color: var(--text-muted); font-size: 12px; }
  .reprice-tbl .reasons { color: var(--text-muted); font-size: 12px; max-width: 320px; }
  .reprice-tbl .reasons em { color: var(--warning); font-style: normal; }
  .decision { font-weight: 700; font-size: 11px; letter-spacing: .1em; }
  .decision-apply { color: var(--success); }
  .decision-skip { color: var(--text-muted); }
  .decision-blocked { color: var(--danger); }
  .row-apply { background: linear-gradient(to right, rgba(127,199,122,0.05), transparent); }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
</style>
"""
    html = promote.html_shell("Repricing Agent · Harpua2001", body,
                              extra_head=extra_css, active_page="repricing.html")
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def gather_inputs(use_cache: bool) -> tuple[dict, list[dict], dict, dict, list[dict]]:
    """Returns (ebay_cfg, listings, market, pricing_by_id, sold_history)."""
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    if use_cache and LISTINGS_SNAPSHOT.exists():
        print(f"  Using cached snapshot at {LISTINGS_SNAPSHOT.relative_to(REPO_ROOT)}")
        snap = json.loads(LISTINGS_SNAPSHOT.read_text())
        return ebay_cfg, snap["listings"], snap["market"], snap["pricing"], snap.get("sold", [])

    print("  Getting eBay access token...")
    token = promote.get_access_token(ebay_cfg)
    print("  Fetching active listings...")
    listings = promote.fetch_listings(token, ebay_cfg)
    print("  Fetching market comps...")
    market = promote.fetch_market_prices(listings, ebay_cfg)
    print("  Loading sold history...")
    sold = promote._load_sold_history()
    print("  Aggregating multi-source pricing...")
    pricing_cache = promote._pricing_cache_load()
    pricing_by_id: dict[str, dict] = {}
    for l in listings:
        pricing_by_id[l["item_id"]] = promote.gather_pricing_sources(
            l["title"], ebay_cfg, sold, market.get(l["item_id"]), pricing_cache
        )
    promote._pricing_cache_save(pricing_cache)

    LISTINGS_SNAPSHOT.parent.mkdir(exist_ok=True)
    LISTINGS_SNAPSHOT.write_text(json.dumps({
        "saved_at":  datetime.now(timezone.utc).isoformat(),
        "listings":  listings,
        "market":    market,
        "pricing":   pricing_by_id,
        "sold":      sold,
    }, indent=2))
    return ebay_cfg, listings, market, pricing_by_id, sold


def plan_all(listings: list[dict], pricing_by_id: dict, cfg: dict) -> list[dict]:
    locks = promote.load_locks()
    plan = []
    for l in listings:
        sources = pricing_by_id.get(l["item_id"], {}) or {}
        market_row = sources.get("ebay_active") or {}
        plan.append(decide(l, market_row, sources, locks, cfg))
    return plan


def apply_plan(plan: list[dict], ebay_cfg: dict, cfg: dict,
               only_item: str | None = None) -> list[dict]:
    token = promote.get_access_token(ebay_cfg)
    applied: list[dict] = []
    to_apply = [d for d in plan if d["decision"] == "apply"]
    if only_item:
        to_apply = [d for d in to_apply if d["item_id"] == only_item]
    cap = cfg["max_changes_per_run"]
    if len(to_apply) > cap:
        print(f"  Capping run at {cap} of {len(to_apply)} eligible changes")
        to_apply = to_apply[:cap]

    for d in to_apply:
        print(f"  → {d['item_id']}: ${d['current_price']:.2f} → ${d['target_price']:.2f}  ({d['delta_pct']:+.1f}%)")
        result = revise_price(d["item_id"], d["target_price"], ebay_cfg, token)
        record = {
            "applied_at":  datetime.now(timezone.utc).isoformat(),
            "item_id":     d["item_id"],
            "title":       d["title"],
            "from_price":  d["current_price"],
            "to_price":    d["target_price"],
            "delta_pct":   d["delta_pct"],
            "basis":       d["basis"],
            "ok":          result["ok"],
            "ack":         result["ack"],
            "error":       (result["errors"][0]["msg"] if result["errors"] else None),
            "error_code":  (result["errors"][0]["code"] if result["errors"] else None),
            "url":         d.get("url"),
        }
        applied.append(record)
        # If eBay rejected with content-policy or ended-listing codes, auto-lock
        if not result["ok"] and result["errors"]:
            code = result["errors"][0]["code"]
            if code in ("240", "291"):
                locks = promote.load_locks()
                locks.setdefault("items", {})[d["item_id"]] = {
                    "code":   code,
                    "reason": result["errors"][0]["msg"] or f"eBay error {code}",
                    "since":  datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                }
                promote.LOCKS_FILE.write_text(json.dumps(locks, indent=2))
                print(f"    ↳ auto-locked {d['item_id']} (eBay code {code})")
        # eBay throttles aggressive revisers; small pacing helps.
        time.sleep(0.5)
    return applied


def summarize(plan: list[dict]) -> None:
    buckets = {"apply": 0, "skip": 0, "blocked": 0}
    for d in plan:
        buckets[d["decision"]] = buckets.get(d["decision"], 0) + 1
    print(f"\n  Plan summary: "
          f"{buckets.get('apply',0)} to apply · "
          f"{buckets.get('skip',0)} dead-zone · "
          f"{buckets.get('blocked',0)} blocked")


def main() -> int:
    ap = argparse.ArgumentParser(description="Guardrailed repricing agent for Harpua2001 eBay listings.")
    ap.add_argument("--apply", action="store_true", help="Actually push price changes to eBay (default: dry run)")
    ap.add_argument("--no-fetch", action="store_true", help="Reuse cached listings snapshot instead of refetching")
    ap.add_argument("--item", help="Limit apply to a single item_id (plan is still computed for all)")
    ap.add_argument("--report-only", action="store_true", help="Rebuild docs/repricing.html from last plan + history")
    args = ap.parse_args()

    cfg = load_config()
    if not cfg.get("enabled", True):
        print("Repricing agent is disabled in repricing_config.json (set 'enabled': true).")
        return 0

    if args.report_only:
        plan = json.loads(PLAN_PATH.read_text()) if PLAN_PATH.exists() else []
        path = build_report(plan, load_history(), cfg)
        print(f"  Wrote {path}")
        return 0

    ebay_cfg, listings, market, pricing_by_id, _sold = gather_inputs(use_cache=args.no_fetch)
    print(f"  Loaded {len(listings)} active listings")

    plan = plan_all(listings, pricing_by_id, cfg)
    PLAN_PATH.parent.mkdir(exist_ok=True)
    PLAN_PATH.write_text(json.dumps({
        "generated_at":  datetime.now(timezone.utc).isoformat(),
        "config":        cfg,
        "decisions":     plan,
    }, indent=2))
    summarize(plan)

    applied: list[dict] = []
    if args.apply:
        print("\n  Applying changes to eBay...")
        applied = apply_plan(plan, ebay_cfg, cfg, only_item=args.item)
        append_history(applied)
        ok = sum(1 for a in applied if a["ok"])
        print(f"\n  Result: {ok}/{len(applied)} applied successfully.")
    else:
        print("\n  Dry run only. Re-run with --apply to push changes.")

    report = build_report(plan, load_history(), cfg)
    print(f"  Report: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
