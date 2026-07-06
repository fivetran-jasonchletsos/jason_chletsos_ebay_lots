"""
best_offer_agent.py — enable & tune Best Offer on Harpua2001 fixed-price listings.

Reads listings_snapshot.json + market medians (promote.fetch_market_prices) and,
for each Fixed-Price listing, decides:
    auto_accept   = market_median * 0.95   (or price * 0.98 fallback)
    auto_decline  = market_median * 0.75   (or price * 0.70 fallback)
    vault_eligible if price >= $250

Vault note: eBay's public Trading API has NO direct flag to opt a single
listing into the Authenticity Vault — Vault enrollment is currently a
seller-account level toggle, then an item-level toggle exercised through
the Seller Hub UI (see Best Offer/Vault docs as of 2026). We therefore
mark Vault candidates in the plan / report only and do NOT mutate the
listing via API for that flag. When eBay exposes the field on ReviseItem
we can wire the API write here without changing the report contract.

Usage:
    python3 best_offer_agent.py                     # dry run (default)
    python3 best_offer_agent.py --apply             # push Best Offer to eBay
    python3 best_offer_agent.py --apply --item 12345
    python3 best_offer_agent.py --no-fetch          # reuse cached GetItem state

Artifacts:
    output/best_offer_plan.json     latest decisions
    output/best_offer_history.json  append-only apply log
    output/best_offer_cache.json    cached GetItem responses (idempotency)
    docs/best_offer.html            admin-only report
"""

from __future__ import annotations

# --- Roster ---
AGENT_NAME = 'Phil Simms'
AGENT_ROLE = 'Best Offer'

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

import promote

REPO_ROOT       = Path(__file__).parent
OUTPUT_DIR      = REPO_ROOT / "output"
LISTINGS_PATH   = OUTPUT_DIR / "listings_snapshot.json"
PLAN_PATH       = OUTPUT_DIR / "best_offer_plan.json"
HISTORY_PATH    = OUTPUT_DIR / "best_offer_history.json"
CACHE_PATH      = OUTPUT_DIR / "best_offer_cache.json"
REPORT_PATH     = promote.OUTPUT_DIR / "best_offer.html"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT      = "967"
SITE_ID     = "0"

# Thresholds
MIN_PRICE_FOR_BEST_OFFER = 2.99     # 2026-05-30 selling-expert review: $5
                                    # floor left ~200 long-tail listings with
                                    # no negotiation channel. $2.99 keeps the
                                    # fee math positive on a $2.50 offer while
                                    # opening BO across the whole catalog.
VAULT_THRESHOLD          = 250.00   # eBay Authenticity Vault eligibility floor
ACCEPT_PCT_OF_MARKET     = 0.95
DECLINE_PCT_OF_MARKET    = 0.75
ACCEPT_FALLBACK_PCT      = 0.98     # if no market median
DECLINE_FALLBACK_PCT     = 0.70
ROUND_TO_CENT            = 0.01

# eBay requires MinimumBestOfferPrice < BIN. Clamp to a small buffer below
# the live BIN to absorb rounding / propagation lag after a reprice down.
DECLINE_BIN_CAP_PCT      = 0.95     # auto_decline <= price * 0.95
ACCEPT_BIN_CAP_PCT       = 0.98     # auto_accept  <= price * 0.98
MIN_ACCEPT_DECLINE_GAP   = 0.05     # accept must clear decline by >= 5¢

# eBay throttles aggressive ReviseItem callers — pace per item.
PACE_SEC = 0.6

# Treat "already configured" as equal if within this many cents.
IDEMPOTENCY_EPSILON = 0.05

MAX_RETRIES      = 3
BACKOFF_BASE_SEC = 1.5


# --------------------------------------------------------------------------- #
# I/O helpers                                                                 #
# --------------------------------------------------------------------------- #

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


def _load_listings() -> list[dict]:
    if not LISTINGS_PATH.exists():
        raise FileNotFoundError(
            f"{LISTINGS_PATH} not found — run promote.py / repricing_agent first."
        )
    raw = json.loads(LISTINGS_PATH.read_text())
    # Both shapes seen in repo: list[dict] (newer) and {"listings": [...]}.
    if isinstance(raw, dict):
        return raw.get("listings", []) or []
    return raw or []


def _load_cache() -> dict[str, dict]:
    return _read_json(CACHE_PATH, {}) or {}


def _save_cache(cache: dict[str, dict]) -> None:
    _write_json(CACHE_PATH, cache)


def _load_history() -> list[dict]:
    h = _read_json(HISTORY_PATH, [])
    return h if isinstance(h, list) else []


def _append_history(entries: list[dict]) -> None:
    if not entries:
        return
    h = _load_history()
    h.extend(entries)
    _write_json(HISTORY_PATH, h)


# --------------------------------------------------------------------------- #
# Trading API client                                                          #
# --------------------------------------------------------------------------- #

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


def _parse_errors(root: ET.Element) -> list[dict]:
    out: list[dict] = []
    for err in root.findall(f".//{NS}Errors"):
        out.append({
            "code":     err.findtext(f"{NS}ErrorCode", "") or "",
            "severity": err.findtext(f"{NS}SeverityCode", "") or "",
            "msg":      err.findtext(f"{NS}ShortMessage", "") or "",
        })
    return out


# --------------------------------------------------------------------------- #
# GetItem — idempotency check                                                 #
# --------------------------------------------------------------------------- #

def _xml_get_item(token: str, item_id: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <ItemID>{item_id}</ItemID>\n'
        f'  <IncludeItemSpecifics>true</IncludeItemSpecifics>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'</GetItemRequest>'
    )


def fetch_item_state(item_id: str, token: str, ebay_cfg: dict) -> dict:
    """Return {best_offer_enabled, auto_accept, min_offer, listing_type}."""
    body = _xml_get_item(token, item_id)
    root = _trading_post("GetItem", body, ebay_cfg)
    errs = _parse_errors(root)
    if errs and any(e["severity"] == "Error" for e in errs):
        return {
            "ok": False, "errors": errs, "best_offer_enabled": None,
            "auto_accept": None, "min_offer": None, "listing_type": None,
            "listing_status": None,
        }
    bo_enabled = (root.findtext(f".//{NS}BestOfferDetails/{NS}BestOfferEnabled", "")
                  or "").lower() == "true"
    auto_accept = root.findtext(f".//{NS}ListingDetails/{NS}BestOfferAutoAcceptPrice", "")
    min_offer   = root.findtext(f".//{NS}ListingDetails/{NS}MinimumBestOfferPrice", "")
    listing_type   = root.findtext(f".//{NS}ListingType", "") or ""
    listing_status = root.findtext(f".//{NS}SellingStatus/{NS}ListingStatus", "") or ""
    sku            = root.findtext(f".//{NS}SKU", "") or ""
    # The live BIN/current price. Used by the clamp to guard against snapshot
    # drift: when the listing was repriced down after the snapshot saved, the
    # snapshot's `price` is stale and the clamp must use the live BIN instead.
    current_price = (root.findtext(f".//{NS}SellingStatus/{NS}CurrentPrice", "")
                     or root.findtext(f".//{NS}StartPrice", "")
                     or root.findtext(f".//{NS}BuyItNowPrice", "")
                     or "")
    return {
        "ok":                 True,
        "errors":             [],
        "best_offer_enabled": bo_enabled,
        "auto_accept":        float(auto_accept) if auto_accept else None,
        "min_offer":          float(min_offer) if min_offer else None,
        "current_price":      float(current_price) if current_price else None,
        "listing_type":       listing_type,
        "listing_status":     listing_status,
        "sku":                sku,
        "fetched_at":         datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------- #
# Decision engine                                                             #
# --------------------------------------------------------------------------- #

def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


def _market_median_for(item_id: str, market: dict) -> float | None:
    row = (market or {}).get(item_id) or {}
    v = row.get("market_median")
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def propose_best_offer(listings: list[dict], market: dict, cfg: dict) -> list[dict]:
    """Pure decisioning. Idempotency vs. live state is layered on later."""
    plan: list[dict] = []
    for l in listings:
        item_id = str(l.get("item_id") or "")
        title   = l.get("title") or ""
        try:
            price = float(l.get("price") or 0)
        except (TypeError, ValueError):
            price = 0.0
        listing_type = (l.get("listing_type") or "").strip()

        row: dict[str, Any] = {
            "item_id":           item_id,
            "title":             title,
            "price":             price,
            "listing_type":      listing_type,
            "market_median":     _market_median_for(item_id, market),
            "auto_accept":       None,
            "auto_decline":      None,
            "vault_recommended": price >= VAULT_THRESHOLD,
            "decision":          "skip",
            "reason":            "",
            "url":               l.get("url") or "",
        }

        # Auction can't take Best Offer at the API level.
        if listing_type and listing_type.lower().startswith("auction"):
            row["reason"] = "listing_type=Auction — Best Offer is fixed-price only"
            plan.append(row); continue

        if price < MIN_PRICE_FOR_BEST_OFFER:
            row["reason"] = f"price ${price:.2f} below floor ${MIN_PRICE_FOR_BEST_OFFER:.2f}"
            plan.append(row); continue

        median = row["market_median"]
        if median and median > 0:
            accept  = _round2(median * ACCEPT_PCT_OF_MARKET)
            decline = _round2(median * DECLINE_PCT_OF_MARKET)
            basis   = f"market_median ${median:.2f}"
        else:
            accept  = _round2(price * ACCEPT_FALLBACK_PCT)
            decline = _round2(price * DECLINE_FALLBACK_PCT)
            basis   = f"no market data — fallback to list price ${price:.2f}"

        # Clamp below current BIN. eBay rejects ReviseItem when
        # MinimumBestOfferPrice >= BIN; this fires after a reprice-down
        # when market_median still trails the new lower list price.
        accept_cap  = _round2(price * ACCEPT_BIN_CAP_PCT)
        decline_cap = _round2(price * DECLINE_BIN_CAP_PCT)
        clamped = (accept > accept_cap) or (decline > decline_cap)
        accept  = min(accept,  accept_cap)
        decline = min(decline, decline_cap)

        # Guarantee accept >= decline + 5¢ to keep eBay happy. If the clamp
        # collapsed the band, drop decline further; if that pushes decline
        # under the BO floor, skip the listing.
        if accept - decline < MIN_ACCEPT_DECLINE_GAP:
            decline = _round2(accept - MIN_ACCEPT_DECLINE_GAP)

        # eBay floor: auto-accept and min-offer must each be >= $0.99.
        if accept < 0.99 or decline < 0.99:
            row["reason"] = (
                f"clamp-collapsed: BIN ${price:.2f} too low vs median "
                f"${median:.2f}" if median else
                f"clamp-collapsed: BIN ${price:.2f} below floor after clamp"
            )
            plan.append(row); continue

        row["auto_accept"]  = accept
        row["auto_decline"] = decline
        row["decision"]     = "apply"
        clamp_note = " [clamped<BIN]" if clamped else ""
        row["reason"]       = (
            f"FP eligible; {basis}; accept@${accept:.2f} ({ACCEPT_PCT_OF_MARKET*100:.0f}%) "
            f"decline@${decline:.2f} ({DECLINE_PCT_OF_MARKET*100:.0f}%){clamp_note}"
        )
        plan.append(row)
    return plan


def filter_for_idempotency(plan: list[dict],
                           cache: dict[str, dict]) -> list[dict]:
    """Strip 'apply' rows whose live state already matches our targets, AND
    re-clamp accept/decline against the LIVE BIN from GetItem when available.

    Without this re-clamp, accept/decline computed from a stale snapshot price
    can exceed the live BIN after a same-day reprice-down, causing eBay to
    reject ReviseItem with errorId 22003 ("Auto decline amount cannot be
    greater than or equal to the Buy It Now price").
    """
    out: list[dict] = []
    for d in plan:
        if d["decision"] != "apply":
            out.append(d); continue
        state = cache.get(d["item_id"]) or {}
        if not state.get("ok"):
            # Not hydrated this run (hydration is capped) or GetItem failed — we
            # can't confirm the listing is Active or re-clamp accept/decline
            # against the live BIN, so DEFER instead of firing an unverified
            # ReviseItem (risks errorId 22003 or revising an Ended listing). It
            # rotates to a later run via the hydration window.
            out.append({**d, "decision": "skip",
                        "reason": "state not verified this run (hydration capped/failed)"})
            continue
        # Inventory-API-managed listings (CollX imports, SKU CDP-*) reject Trading
        # ReviseItem with err 21919474 ("not allowed for inventory items"). They
        # already carry Best Offer set via the Sell Inventory API on import, so
        # there is nothing to push here — skip to stop generating false failures.
        sku = (state.get("sku") or "")
        if sku.upper().startswith("CDP-"):
            d = dict(d)
            d["decision"] = "skip"
            d["reason"]   = ("inventory-managed (SKU " + sku + "); Best Offer set via "
                             "Sell Inventory API — Trading ReviseItem not allowed (21919474)")
            out.append(d); continue
        # ReviseItem only succeeds on Active listings; skip Completed/Ended.
        status = (state.get("listing_status") or "").strip()
        if status and status.lower() != "active":
            d = dict(d)
            d["decision"] = "skip"
            d["reason"]   = f"listing_status={status} — ReviseItem requires Active"
            out.append(d); continue
        # Re-clamp against live BIN if the snapshot price is stale (live < snapshot).
        live_bin = state.get("current_price")
        if live_bin and d.get("price") and live_bin < d["price"]:
            d = dict(d)
            accept_cap  = _round2(live_bin * ACCEPT_BIN_CAP_PCT)
            decline_cap = _round2(live_bin * DECLINE_BIN_CAP_PCT)
            d["auto_accept"]  = min(d["auto_accept"],  accept_cap)
            d["auto_decline"] = min(d["auto_decline"], decline_cap)
            if d["auto_accept"] - d["auto_decline"] < MIN_ACCEPT_DECLINE_GAP:
                d["auto_decline"] = _round2(d["auto_accept"] - MIN_ACCEPT_DECLINE_GAP)
            if d["auto_accept"] < 0.99 or d["auto_decline"] < 0.99:
                d["decision"] = "skip"
                d["reason"]   = f"clamp-collapsed against live BIN ${live_bin:.2f}"
                out.append(d); continue
            d["reason"] = (d.get("reason","") +
                           f" [re-clamped to live BIN ${live_bin:.2f}]")
        cur_acc = state.get("auto_accept")
        cur_dec = state.get("min_offer")
        same = (
            state.get("best_offer_enabled")
            and cur_acc is not None and cur_dec is not None
            and abs(cur_acc - d["auto_accept"])  <= IDEMPOTENCY_EPSILON
            and abs(cur_dec - d["auto_decline"]) <= IDEMPOTENCY_EPSILON
        )
        if same:
            d = dict(d)
            d["decision"] = "skip"
            d["reason"]   = (
                f"already configured (BO on, accept ${cur_acc:.2f}, "
                f"min ${cur_dec:.2f})"
            )
        out.append(d)
    return out


# --------------------------------------------------------------------------- #
# ReviseItem — push Best Offer                                                #
# --------------------------------------------------------------------------- #

def _xml_revise_best_offer(token: str, item_id: str,
                           accept: float, decline: float) -> str:
    # Note: BestOfferEnabled lives under Item.BestOfferDetails; the price
    # thresholds live under Item.ListingDetails. eBay accepts both blocks
    # in a single ReviseItem call.
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<ReviseItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <Item>\n'
        f'    <ItemID>{item_id}</ItemID>\n'
        f'    <BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>\n'
        f'    <ListingDetails>\n'
        f'      <BestOfferAutoAcceptPrice currencyID="USD">{accept:.2f}</BestOfferAutoAcceptPrice>\n'
        f'      <MinimumBestOfferPrice currencyID="USD">{decline:.2f}</MinimumBestOfferPrice>\n'
        f'    </ListingDetails>\n'
        f'  </Item>\n'
        f'</ReviseItemRequest>'
    )


def apply_best_offer(token: str, plan: list[dict], ebay_cfg: dict,
                     dry_run: bool = True,
                     only_item: str | None = None) -> list[dict]:
    """Iterate plan rows with decision='apply' and push via ReviseItem."""
    results: list[dict] = []
    to_apply = [d for d in plan if d["decision"] == "apply"]
    if only_item:
        to_apply = [d for d in to_apply if d["item_id"] == only_item]

    # Respect locks.json — listings the user has explicitly protected.
    # The repricing agent already honours this file; best_offer_agent
    # was ignoring it, which let BO floors get set on locked lots and
    # blocked subsequent price reverts (errors 22003/23004).
    try:
        locks = promote.load_locks() or {}
        locked_ids = set((locks.get("items") or {}).keys())
    except Exception:
        locked_ids = set()
    if locked_ids:
        before = len(to_apply)
        to_apply = [d for d in to_apply if d["item_id"] not in locked_ids]
        skipped = before - len(to_apply)
        if skipped:
            print(f"  Skipping {skipped} locked listing(s): "
                  f"{', '.join(sorted(locked_ids & {d['item_id'] for d in plan}))[:120]}")

    for d in to_apply:
        envelope = _xml_revise_best_offer(
            token if not dry_run else "<TOKEN>",
            d["item_id"], d["auto_accept"], d["auto_decline"],
        )
        record = {
            "applied_at":   datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "item_id":      d["item_id"],
            "title":        d["title"],
            "price":        d["price"],
            "auto_accept":  d["auto_accept"],
            "auto_decline": d["auto_decline"],
            "dry_run":      dry_run,
            "ok":           None,
            "ack":          None,
            "errors":       [],
        }
        if dry_run:
            record["ok"]  = True
            record["ack"] = "DryRun"
            results.append(record)
            continue
        try:
            root = _trading_post("ReviseItem", envelope, ebay_cfg)
            ack  = root.findtext(f"{NS}Ack", "") or ""
            errs = _parse_errors(root)
            record["ack"]    = ack
            record["errors"] = errs
            record["ok"]     = ack in ("Success", "Warning")
            line = (f"  → {d['item_id']}: ack={ack}  "
                    f"(accept ${d['auto_accept']:.2f} / min ${d['auto_decline']:.2f})")
            # Surface eBay's actual error reason on Failure so the operator can act.
            if ack != "Success" and errs:
                err_summary = "; ".join(f"{e['code']}:{e['msg']}" for e in errs[:2])
                line += f"\n     errors: {err_summary}"
            print(line)
        except Exception as exc:
            record["ok"]     = False
            record["errors"] = [{"code": "EXC", "severity": "Error", "msg": str(exc)}]
            print(f"  → {d['item_id']}: EXC {exc}")
        results.append(record)
        time.sleep(PACE_SEC)
    return results


# --------------------------------------------------------------------------- #
# HTML report                                                                 #
# --------------------------------------------------------------------------- #

def _fmt_money(n) -> str:
    if n is None:
        return "—"
    try:
        return f"${float(n):,.2f}"
    except (TypeError, ValueError):
        return "—"


def build_report(plan: list[dict], summary: dict) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    fp_rows = [d for d in plan if d["decision"] == "apply"]
    skip_rows = [d for d in plan if d["decision"] == "skip"]
    vault_rows = [d for d in plan if d.get("vault_recommended")]

    def _row(d: dict) -> str:
        return (
            "<tr>"
            f"<td class='item'><a href='{d.get('url') or '#'}' target='_blank' rel='noopener'>"
            f"<span class='title'>{(d['title'] or '')[:90]}</span>"
            f"<span class='item-id'>{d['item_id']}</span></a></td>"
            f"<td class='num'>{_fmt_money(d['price'])}</td>"
            f"<td class='num'>{_fmt_money(d.get('market_median'))}</td>"
            f"<td class='num accept'>{_fmt_money(d.get('auto_accept'))}</td>"
            f"<td class='num decline'>{_fmt_money(d.get('auto_decline'))}</td>"
            f"<td class='reason'>{d.get('reason','')}</td>"
            f"</tr>"
        )

    def _table(items: list[dict], empty: str) -> str:
        if not items:
            return f"<p class='empty'>{empty}</p>"
        rows = "\n".join(_row(d) for d in items)
        return (
            "<div class='tbl-wrap'><table class='bo-tbl'>"
            "<thead><tr>"
            "<th>Listing</th><th>Price</th><th>Market</th>"
            "<th>Auto-Accept</th><th>Auto-Decline</th><th>Reason</th>"
            "</tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )

    def _vault_table(items: list[dict]) -> str:
        if not items:
            return ("<p class='empty'>No Vault-eligible listings "
                    f"(price ≥ ${VAULT_THRESHOLD:.0f}).</p>")
        rows = "\n".join(
            f"<tr><td class='item'><a href='{d.get('url') or '#'}' target='_blank' rel='noopener'>"
            f"<span class='title'>{(d['title'] or '')[:90]}</span>"
            f"<span class='item-id'>{d['item_id']}</span></a></td>"
            f"<td class='num'>{_fmt_money(d['price'])}</td></tr>"
            for d in items
        )
        return (
            "<div class='tbl-wrap'><table class='bo-tbl'>"
            "<thead><tr><th>Listing</th><th>Price</th></tr></thead>"
            f"<tbody>{rows}</tbody></table></div>"
        )

    body = f"""
<section class="hero">
  <h1>Best Offer Agent</h1>
  <p class="sub">Last run: <code>{run_ts}</code></p>
  <div class="bo-kpis">
    <div class="bo-kpi">
      <div class="bo-kpi-n">{summary['fp_eligible']}</div>
      <div class="bo-kpi-l">FP eligible</div>
      <div class="bo-kpi-foot">Fixed-price · ≥ ${MIN_PRICE_FOR_BEST_OFFER:.0f}</div>
    </div>
    <div class="bo-kpi">
      <div class="bo-kpi-n">{summary['would_apply']}</div>
      <div class="bo-kpi-l">Would apply</div>
      <div class="bo-kpi-foot">After idempotency filter</div>
    </div>
    <div class="bo-kpi">
      <div class="bo-kpi-n">{summary['vault_eligible']}</div>
      <div class="bo-kpi-l">Vault eligible</div>
      <div class="bo-kpi-foot">Price ≥ ${VAULT_THRESHOLD:.0f} (UI flag only)</div>
    </div>
    <div class="bo-kpi">
      <div class="bo-kpi-n">{summary['skipped']}</div>
      <div class="bo-kpi-l">Skipped</div>
      <div class="bo-kpi-foot">Auction / sub-floor / no-op</div>
    </div>
  </div>
</section>

<section class="bo-note">
  <h3>Thresholds</h3>
  <ul>
    <li><strong>Auto-Accept</strong>: 95% of market median (fallback 98% of list)</li>
    <li><strong>Auto-Decline</strong>: 75% of market median (fallback 70% of list)</li>
    <li><strong>Vault</strong>: flagged at $250+ list price. eBay's Trading API does not
      expose a per-item Vault toggle today; enable in Seller Hub UI per item.</li>
  </ul>
</section>

<h3>Will apply <span class='count'>({len(fp_rows)})</span></h3>
{_table(fp_rows, "Nothing to apply — every FP listing is either already configured or sub-floor.")}

<h3>Vault-eligible <span class='count'>({len(vault_rows)})</span></h3>
{_vault_table(vault_rows)}

<h3>Skipped <span class='count'>({len(skip_rows)})</span></h3>
{_table(skip_rows, "Nothing skipped.")}
"""

    extra_css = """
<style>
  .hero { padding: 24px 0 12px; }
  .hero h1 { margin: 0 0 4px; font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; letter-spacing: -0.005em; font-size: 56px; letter-spacing: .02em; }
  .hero .sub { color: var(--text-muted); }
  .bo-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin: 18px 0 28px; }
  .bo-kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-md); padding: 18px 20px; position: relative; overflow: hidden; }
  .bo-kpi::before { content:""; position:absolute; inset:0 auto 0 0; width:3px; background: var(--gold); opacity:.7; }
  .bo-kpi-n { font-family: 'Fraunces', Georgia, serif; font-style: italic; font-weight: 500; font-variation-settings: 'opsz' 144, 'SOFT' 30, 'WONK' 1; letter-spacing: -0.005em; font-size: 44px; color: var(--gold); line-height: 1; }
  .bo-kpi-l { color: var(--text-muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-top: 6px; }
  .bo-kpi-foot { color: var(--text-dim); font-size: 11px; margin-top: 8px; border-top: 1px dashed var(--border); padding-top: 8px; }
  .bo-note { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: 14px 18px; margin: 0 0 24px; }
  .bo-note h3 { margin: 0 0 6px; font-size: 13px; text-transform: uppercase; letter-spacing: .1em; color: var(--text-muted); }
  .bo-note ul { margin: 0; padding-left: 18px; color: var(--text); }
  .bo-note li { margin: 2px 0; }
  h3 .count { color: var(--text-muted); font-weight: 400; font-size: .7em; }
  .tbl-wrap { overflow-x: auto; border-radius: var(--r-md); border: 1px solid var(--border); margin: 8px 0 24px; }
  table.bo-tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .bo-tbl th, .bo-tbl td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--border); vertical-align: top; }
  .bo-tbl th { background: var(--surface-2); color: var(--text-muted); font-size: 11px; text-transform: uppercase; letter-spacing: .08em; }
  .bo-tbl tr:hover td { background: var(--surface-2); }
  .bo-tbl .num { text-align: right; font-variant-numeric: tabular-nums; font-family: 'JetBrains Mono', monospace; }
  .bo-tbl .accept { color: var(--success); font-weight: 600; }
  .bo-tbl .decline { color: var(--danger); font-weight: 600; }
  .bo-tbl .item .title { display: block; color: var(--text); }
  .bo-tbl .item .item-id { display: block; color: var(--text-dim); font-size: 11px; font-family: 'JetBrains Mono', monospace; margin-top: 2px; }
  .bo-tbl .item a { text-decoration: none; }
  .bo-tbl .item a:hover .title { color: var(--gold); }
  .bo-tbl .reason { color: var(--text-muted); font-size: 12px; max-width: 360px; }
  .empty { color: var(--text-muted); padding: 20px; text-align: center; background: var(--surface); border: 1px dashed var(--border); border-radius: var(--r-md); }
</style>
"""
    html = promote.html_shell("Best Offer Agent · Harpua2001",
                              body, extra_head=extra_css,
                              active_page="best_offer.html")
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def _summarize(plan: list[dict]) -> dict:
    fp_eligible    = sum(1 for d in plan
                         if (d.get("listing_type") or "").lower() != "auction"
                         and (d.get("price") or 0) >= MIN_PRICE_FOR_BEST_OFFER)
    vault_eligible = sum(1 for d in plan if d.get("vault_recommended"))
    would_apply    = sum(1 for d in plan if d["decision"] == "apply")
    skipped        = sum(1 for d in plan if d["decision"] == "skip")
    return {
        "fp_eligible":    fp_eligible,
        "vault_eligible": vault_eligible,
        "would_apply":    would_apply,
        "skipped":        skipped,
    }


def _hydrate_state(plan: list[dict], token: str, ebay_cfg: dict,
                   use_cache: bool, max_hydrate: int = 200,
                   advance_offset: bool = True,
                   only_item: str | None = None) -> dict[str, dict]:
    """Fetch (or reuse cached) GetItem results for 'apply' candidates.

    GetItem is a serial-per-item Trading call; hydrating every candidate (which
    can balloon to 700+ when Browse comps are unavailable) is what timed the
    agent out. So: fetch in parallel (bounded pool, no per-item sleep) and CAP
    the count per run. Items beyond the cap are simply not hydrated this run —
    they fall out of the idempotency filter and get picked up on a later run
    (already-enabled offers become idempotent-skips, so coverage rotates).
    """
    from concurrent.futures import ThreadPoolExecutor
    cache = _load_cache() if use_cache else {}
    # When targeting a single item (--item), hydrate ONLY that item so it can't
    # fall outside the rotating window and get silently deferred (--apply --item X
    # would otherwise apply nothing if X wasn't in this run's window).
    candidates = [d["item_id"] for d in plan if d["decision"] == "apply"
                  and (only_item is None or d["item_id"] == only_item)]
    fresh: dict[str, dict] = dict(cache) if use_cache else {}
    to_fetch = [iid for iid in candidates if not (use_cache and iid in cache)]
    capped = len(to_fetch) > max_hydrate
    if capped:
        # Rotate the hydration window each run so every candidate eventually
        # gets verified+applied. Without rotation the first max_hydrate items
        # would be the only ones ever hydrated — and the rest, now deferred by
        # filter_for_idempotency (state never verified), would never apply.
        off_path = OUTPUT_DIR / "best_offer_hydrate_offset.json"
        offset = (_read_json(off_path, {}) or {}).get("offset", 0) % len(to_fetch)
        to_fetch = (to_fetch + to_fetch)[offset:offset + max_hydrate]
        # Only advance/persist the window on a real apply run — advancing in a
        # dry-run would skip that window forward so the next --apply run never
        # hydrates (and thus never applies) the items we just previewed.
        if advance_offset:
            _write_json(off_path, {"offset": (offset + max_hydrate) % len(candidates or [1])})

    def _one(iid):
        try:
            return iid, fetch_item_state(iid, token, ebay_cfg)
        except Exception as exc:
            return iid, {"ok": False, "errors": [{"msg": str(exc)}]}

    if to_fetch:
        with ThreadPoolExecutor(max_workers=6) as ex:
            for iid, st in ex.map(_one, to_fetch):
                fresh[iid] = st
        print(f"  GetItem hydrated {len(to_fetch)} listings (parallel"
              f"{'; capped this run' if capped else ''})")
    elif use_cache:
        print(f"  Reused {len(fresh)} cached GetItem results")
    # Merge into the on-disk cache rather than clobbering it — on the default
    # (non --no-fetch) path `fresh` holds only this run's hydration window, so a
    # wholesale write would shrink the idempotency cache to ~max_hydrate items
    # and lose every previously-cached listing's state. Reuse the disk read from
    # the top on the use_cache path instead of reading it a second time.
    merged = dict(cache) if use_cache else _load_cache()
    merged.update(fresh)
    _save_cache(merged)
    # Return THIS run's state (not the merged cache): filter_for_idempotency
    # defers any 'apply' candidate whose state isn't present, so returning the
    # full cache would let prior-run (possibly stale) state slip an un-hydrated
    # listing through to an unverified ReviseItem.
    return fresh


def main() -> int:
    print(f"  Phil Simms (Best Offer) reporting in.")
    ap = argparse.ArgumentParser(
        description="Enable & tune Best Offer on Harpua2001 fixed-price listings.")
    ap.add_argument("--apply",    action="store_true",
                    help="Push ReviseItem to eBay (default: dry run).")
    ap.add_argument("--item",     help="Limit apply to a single item_id.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Reuse cached GetItem state instead of re-querying.")
    ap.add_argument("--no-market", action="store_true",
                    help="Skip fetch_market_prices (use list-price fallback).")
    args = ap.parse_args()

    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())
    listings = _load_listings()
    print(f"  Loaded {len(listings)} listings from {LISTINGS_PATH.name}")

    # Market signal — optional. Auction & sub-floor items will be skipped anyway.
    market: dict = {}
    if not args.no_market:
        try:
            print("  Fetching market medians (Browse API)...")
            market = promote.fetch_market_prices(listings, ebay_cfg) or {}
        except Exception as exc:
            print(f"  fetch_market_prices failed ({exc}); falling back to list price")
            market = {}

    plan = propose_best_offer(listings, market, ebay_cfg)

    # Hydrate live state only if we plan to mutate something. In dry run we
    # still hydrate (when not --no-fetch) so the report reflects idempotency.
    need_hydrate = any(d["decision"] == "apply" for d in plan)
    if need_hydrate:
        try:
            print("  Getting eBay access token for GetItem hydration...")
            token = promote.get_access_token(ebay_cfg)
            cache = _hydrate_state(plan, token, ebay_cfg, use_cache=args.no_fetch,
                                   advance_offset=args.apply, only_item=args.item)
            plan = filter_for_idempotency(plan, cache)
        except Exception as exc:
            print(f"  Hydration skipped ({exc}); proceeding without idempotency filter")
            token = None
    else:
        token = None

    summary = _summarize(plan)
    print(f"  Plan: fp_eligible={summary['fp_eligible']}  "
          f"would_apply={summary['would_apply']}  "
          f"vault_eligible={summary['vault_eligible']}  "
          f"skipped={summary['skipped']}")

    _write_json(PLAN_PATH, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary":      summary,
        "plan":         plan,
    })

    applied: list[dict] = []
    if args.apply:
        if token is None:
            token = promote.get_access_token(ebay_cfg)
        print("\n  Applying Best Offer settings to eBay...")
        applied = apply_best_offer(token, plan, ebay_cfg,
                                   dry_run=False, only_item=args.item)
        _append_history(applied)
        ok = sum(1 for a in applied if a["ok"])
        print(f"\n  Result: {ok}/{len(applied)} applied successfully.")
    else:
        print("\n  Dry run only. Re-run with --apply to push to eBay.")

    report = build_report(plan, summary)
    print(f"  Report:  {report}")
    print(f"  Plan:    {PLAN_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
