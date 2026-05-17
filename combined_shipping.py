"""
combined_shipping.py — Trading API combined-shipping (flat-rate) profile sync.

Why this exists:
  Cards stack. USPS first-class adds <$0.50 of marginal weight cost per extra
  card, but eBay's default per-listing shipping charges full freight on EVERY
  item in a multi-item cart. That penalty kills multi-card AOV. Combined
  shipping is the single highest-leverage AOV move for a card store: buyers
  see "first item $X, each additional $Y" on the listing page and self-bundle.

What this module does (idempotently):
  1. Derives a flat-rate discount rule from the store's inventory composition.
     (More lots → slightly higher per-additional, since lots weigh more.)
  2. Fetches the seller's current CombinedFixedFlatRateShippingDiscountProfile
     via Trading API GetShippingDiscountProfiles.
  3. Diffs desired vs live; emits SetShippingDiscountProfiles only if drift.
  4. Walks active listings and (optionally) ReviseItems them in batches of 50
     to set Item.ShippingDetails.ApplyShippingDiscount=true so the listing
     actually USES the profile. Skips items where the flag is already on.

Default = dry run. Use --apply to push to eBay.

Usage:
    python3 combined_shipping.py                  # dry run
    python3 combined_shipping.py --apply          # push profile + flip items
    python3 combined_shipping.py --profile-only   # only sync the profile
    python3 combined_shipping.py --items-only     # only flip ApplyShippingDiscount

Artifacts:
    output/combined_shipping_plan.json     latest plan
    output/combined_shipping_history.json  append-only run log
    docs/combined_shipping.html            human-readable report

Pattern mirrors seller_hub_phase2.py (Trading XML + backoff) and
promotions_agent.py (dry-run default, history log, html_shell report).
"""
from __future__ import annotations

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

REPO_ROOT   = Path(__file__).parent
OUTPUT_DIR  = REPO_ROOT / "output"
DOCS_DIR    = REPO_ROOT / "docs"
PLAN_PATH   = OUTPUT_DIR / "combined_shipping_plan.json"
HISTORY_PATH = OUTPUT_DIR / "combined_shipping_history.json"
LISTINGS_SNAPSHOT = OUTPUT_DIR / "listings_snapshot.json"
REPORT_PATH = DOCS_DIR / "combined_shipping.html"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT      = "967"
SITE_ID     = "0"

ITEMS_PER_BULK_CALL = 50
MAX_RETRIES         = 4
BACKOFF_BASE_SEC    = 1.5
DAILY_CALL_BUDGET   = 5000

DEFAULT_PROFILE_NAME = "Harpua2001 Flat Combined"


# --------------------------------------------------------------------------- #
# HTTP — Trading API client with exponential backoff                          #
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
    """POST to Trading API with retry/backoff on 5xx."""
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


def _ack(root: ET.Element) -> str:
    return root.findtext(f"{NS}Ack", "") or ""


# --------------------------------------------------------------------------- #
# Rule derivation                                                              #
# --------------------------------------------------------------------------- #

def _is_lot(listing: dict) -> bool:
    title = (listing.get("title") or "").lower()
    if "lot" in title:
        return True
    # Quantity > 1 also smells like a bundled lot
    try:
        q = int(listing.get("quantity") or 1)
        if q > 1:
            return True
    except (TypeError, ValueError):
        pass
    return False


def derive_combined_shipping_rule(listings: list[dict]) -> dict:
    """Derive a flat-rate combined-shipping rule from inventory composition.

    Heuristic (designed for harpua2001's ~128 mostly-singles store):
      - Singles-heavy (<25% lots): $0.50 each additional, $5 cap.
        USPS first-class adds <$0.50 of weight per single card.
      - Mixed (25-60% lots): $0.75 each additional, $6 cap.
        Lots stack heavier; per-add nudges up to cover marginal postage.
      - Lots-heavy (>=60% lots): $1.00 each additional, $7 cap.
        Bigger packages, often need bubble mailer upgrade.

    First item amount is unchanged — the listing's existing shipping cost
    remains the anchor, so the buyer sees "first item: <whatever you set>,
    each additional: $X, free after $Y."

    Args:
        listings: list of listing dicts (each with at least 'title' and
            optionally 'quantity'). Empty list → singles defaults.

    Returns:
        {
          "profile_name": str,
          "first_item_amount": None,           # use existing per-listing
          "each_additional_amount": float,
          "cap_amount": float,
          "lot_ratio": float,
          "rationale": str,
        }
    """
    n = len(listings)
    lot_count = sum(1 for l in listings if _is_lot(l))
    lot_ratio = (lot_count / n) if n else 0.0

    if lot_ratio < 0.25:
        each_add, cap, band = 0.50, 5.00, "singles-heavy"
    elif lot_ratio < 0.60:
        each_add, cap, band = 0.75, 6.00, "mixed"
    else:
        each_add, cap, band = 1.00, 7.00, "lots-heavy"

    return {
        "profile_name":           DEFAULT_PROFILE_NAME,
        "first_item_amount":      None,          # honor per-listing first cost
        "each_additional_amount": each_add,
        "cap_amount":             cap,
        "lot_ratio":              round(lot_ratio, 3),
        "n_listings":             n,
        "n_lots":                 lot_count,
        "band":                   band,
        "rationale":              (
            f"{lot_count}/{n} ({lot_ratio*100:.0f}%) lots → {band}: "
            f"${each_add:.2f}/add'l, cap ${cap:.2f}."
        ),
    }


# --------------------------------------------------------------------------- #
# XML envelope builders                                                       #
# --------------------------------------------------------------------------- #

def _xml_get_shipping_discount_profiles(token: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetShippingDiscountProfilesRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <DetailLevel>ReturnAll</DetailLevel>\n'
        f'</GetShippingDiscountProfilesRequest>'
    )


def _xml_set_shipping_discount_profiles(token: str, rule: dict,
                                        profile_id: str | None = None) -> str:
    """Build SetShippingDiscountProfilesRequest with a FlatShippingDiscount.

    eBay matches profiles by DiscountProfileName; including the existing
    MappedDiscountProfileID when present makes the request an update rather
    than a create.
    """
    pid_node = (f"<MappedDiscountProfileID>{profile_id}</MappedDiscountProfileID>"
                if profile_id else "")
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<SetShippingDiscountProfilesRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <CombinedPaymentOption>NotSpecified</CombinedPaymentOption>\n'
        f'  <FlatShippingDiscount>\n'
        f'    <DiscountName>EachAdditionalAmount</DiscountName>\n'
        f'    <DiscountProfile>\n'
        f'      <DiscountProfileName>{_xml_escape(rule["profile_name"])}</DiscountProfileName>\n'
        f'      {pid_node}\n'
        f'      <EachAdditionalAmount currencyID="USD">{rule["each_additional_amount"]:.2f}</EachAdditionalAmount>\n'
        f'    </DiscountProfile>\n'
        f'  </FlatShippingDiscount>\n'
        f'  <ShippingInsurance>\n'
        f'    <InsuranceOption>NotOffered</InsuranceOption>\n'
        f'  </ShippingInsurance>\n'
        f'</SetShippingDiscountProfilesRequest>'
    )


def _xml_revise_item_apply_discount_bulk(token: str, item_ids: list[str]) -> str:
    """ReviseItem batch — set ApplyShippingDiscount=true on each Item."""
    items = "\n".join(
        f'  <Item>\n'
        f'    <ItemID>{iid}</ItemID>\n'
        f'    <ShippingDetails>\n'
        f'      <ApplyShippingDiscount>true</ApplyShippingDiscount>\n'
        f'    </ShippingDetails>\n'
        f'  </Item>'
        for iid in item_ids
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<ReviseItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'{items}\n'
        f'</ReviseItemRequest>'
    )


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;")
             .replace("'", "&apos;"))


# --------------------------------------------------------------------------- #
# GetShippingDiscountProfiles                                                  #
# --------------------------------------------------------------------------- #

def fetch_existing_profile(token: str, ebay_cfg: dict) -> dict | None:
    """Return the live flat-rate combined-shipping profile, or None.

    Walks every FlatShippingDiscount/DiscountProfile node on the response.
    We return the first one (a seller normally has 0 or 1). The shape:
        {
          "profile_id":   str,
          "profile_name": str,
          "each_additional_amount": float | None,
          "first_item_amount":      float | None,
        }
    """
    body = _xml_get_shipping_discount_profiles(token)
    root = _trading_post("GetShippingDiscountProfiles", body, ebay_cfg)
    errors = _parse_errors(root)
    if errors and any(e["severity"] == "Error" for e in errors):
        raise RuntimeError(f"GetShippingDiscountProfiles errors: {errors}")
    for flat in root.findall(f".//{NS}FlatShippingDiscount"):
        for prof in flat.findall(f"{NS}DiscountProfile"):
            ea = prof.findtext(f"{NS}EachAdditionalAmount", "") or ""
            fi = prof.findtext(f"{NS}FirstItemAmount", "") or ""
            return {
                "profile_id":              prof.findtext(f"{NS}MappedDiscountProfileID", "") or "",
                "profile_name":            prof.findtext(f"{NS}DiscountProfileName", "") or "",
                "each_additional_amount":  _to_float(ea),
                "first_item_amount":       _to_float(fi),
            }
    return None


def _to_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Profile sync                                                                 #
# --------------------------------------------------------------------------- #

def _profile_drift(existing: dict, rule: dict) -> list[str]:
    drift: list[str] = []
    if existing.get("profile_name") != rule["profile_name"]:
        drift.append(
            f"name: live '{existing.get('profile_name')}' vs config '{rule['profile_name']}'"
        )
    live_ea = existing.get("each_additional_amount")
    want_ea = float(rule["each_additional_amount"])
    if live_ea is None or abs(float(live_ea) - want_ea) > 0.001:
        drift.append(f"each_additional: live ${live_ea} vs config ${want_ea:.2f}")
    return drift


def sync_combined_shipping(token: str, rule: dict, ebay_cfg: dict,
                           dry_run: bool = True) -> dict:
    """Idempotent SetShippingDiscountProfiles. Diff-driven.

    Returns:
        {
          "action":  "created" | "updated" | "in_sync" | "would_create" | "would_update",
          "envelope": str | None,
          "ack":      str | None,
          "errors":   list[dict],
          "drift":    list[str],
          "existing": dict | None,
          "dry_run":  bool,
        }
    """
    result: dict[str, Any] = {
        "action":   "noop",
        "envelope": None,
        "ack":      None,
        "errors":   [],
        "drift":    [],
        "existing": None,
        "dry_run":  dry_run,
    }

    existing = None
    if not dry_run:
        existing = fetch_existing_profile(token, ebay_cfg)
    else:
        # Best-effort read on dry run too — credentials exist locally
        try:
            existing = fetch_existing_profile(token, ebay_cfg)
        except Exception as exc:
            print(f"  GetShippingDiscountProfiles read failed (dry-run): {exc}")
            existing = None
    result["existing"] = existing

    if existing:
        drift = _profile_drift(existing, rule)
        result["drift"] = drift
        if not drift:
            result["action"] = "in_sync"
            return result
        envelope = _xml_set_shipping_discount_profiles(
            token if not dry_run else "<TOKEN>", rule,
            profile_id=existing.get("profile_id") or None,
        )
        result["envelope"] = envelope
        if dry_run:
            result["action"] = "would_update"
            return result
        root = _trading_post("SetShippingDiscountProfiles", envelope, ebay_cfg)
        result["ack"]    = _ack(root)
        result["errors"] = _parse_errors(root)
        result["action"] = "updated" if result["ack"] in ("Success", "Warning") else "update_failed"
        return result

    # No existing profile — create
    envelope = _xml_set_shipping_discount_profiles(
        token if not dry_run else "<TOKEN>", rule, profile_id=None,
    )
    result["envelope"] = envelope
    if dry_run:
        result["action"] = "would_create"
        return result
    root = _trading_post("SetShippingDiscountProfiles", envelope, ebay_cfg)
    result["ack"]    = _ack(root)
    result["errors"] = _parse_errors(root)
    result["action"] = "created" if result["ack"] in ("Success", "Warning") else "create_failed"
    return result


# --------------------------------------------------------------------------- #
# Per-listing ApplyShippingDiscount=true                                       #
# --------------------------------------------------------------------------- #

def _already_applies_discount(listing: dict) -> bool:
    """Best-effort: detect listings that already opted into combined shipping.
    The snapshot writer doesn't always include the flag, so absence is treated
    as 'unknown' (needs revising) — better to be idempotent on eBay's side via
    ReviseItem (a re-set is a no-op).
    """
    for key in ("apply_shipping_discount", "ApplyShippingDiscount"):
        v = listing.get(key)
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() == "true":
            return True
    sd = listing.get("shipping_details") or listing.get("ShippingDetails") or {}
    if isinstance(sd, dict):
        v = sd.get("ApplyShippingDiscount") or sd.get("apply_shipping_discount")
        if isinstance(v, bool):
            return v
        if isinstance(v, str) and v.lower() == "true":
            return True
    return False


def _chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def apply_to_listings(token: str, listings: list[dict], ebay_cfg: dict,
                      dry_run: bool = True) -> dict:
    """Bulk-flip Item.ShippingDetails.ApplyShippingDiscount=true via ReviseItem.

    Batches in 50. Skips listings where the flag is already on.
    """
    need: list[str] = []
    skipped: list[str] = []
    for l in listings:
        iid = l.get("item_id") or ""
        if not iid:
            continue
        if _already_applies_discount(l):
            skipped.append(iid)
        else:
            need.append(iid)

    n_calls = (len(need) + ITEMS_PER_BULK_CALL - 1) // ITEMS_PER_BULK_CALL
    if n_calls > DAILY_CALL_BUDGET:
        raise RuntimeError(
            f"Plan would issue {n_calls} ReviseItem batches — exceeds "
            f"daily budget {DAILY_CALL_BUDGET}. Aborting."
        )

    result: dict[str, Any] = {
        "total_listings": len(listings),
        "to_revise":      len(need),
        "skipped":        skipped,
        "batches":        n_calls,
        "dry_run":        dry_run,
        "envelopes":      [],
        "results":        [],
    }

    if not need:
        return result

    for batch_idx, batch in enumerate(_chunked(need, ITEMS_PER_BULK_CALL)):
        envelope = _xml_revise_item_apply_discount_bulk(
            token if not dry_run else "<TOKEN>", batch,
        )
        if dry_run:
            result["envelopes"].append(envelope)
            continue
        root = _trading_post("ReviseItem", envelope, ebay_cfg)
        result["results"].append({
            "batch":  batch_idx + 1,
            "ack":    _ack(root),
            "errors": _parse_errors(root),
            "items":  batch,
        })
        time.sleep(0.4)
    return result


# --------------------------------------------------------------------------- #
# Savings simulation                                                          #
# --------------------------------------------------------------------------- #

def simulate_savings(listings: list[dict], rule: dict,
                     cart_size: int = 5) -> dict:
    """Buyer of N cards: pre-profile pays N * first_ship; post-profile pays
    first_ship + (N-1) * each_additional, capped at rule['cap_amount'].

    Returns:
        {cart_size, avg_first_ship, no_profile_total, with_profile_total,
         savings, savings_pct}
    """
    # Best-effort: extract shipping from snapshot if present, else assume $4.50
    # (typical eBay Standard Envelope for cards is $4.49).
    ship_costs: list[float] = []
    for l in listings:
        sd = l.get("shipping_details") or l.get("ShippingDetails") or {}
        if isinstance(sd, dict):
            v = sd.get("ShippingServiceCost") or sd.get("shipping_service_cost")
            try:
                if v is not None:
                    ship_costs.append(float(v))
                    continue
            except (TypeError, ValueError):
                pass
        v = l.get("shipping_cost") or l.get("shipping")
        try:
            if v is not None:
                ship_costs.append(float(v))
        except (TypeError, ValueError):
            pass

    avg_first = round(sum(ship_costs) / len(ship_costs), 2) if ship_costs else 4.50

    no_profile = round(avg_first * cart_size, 2)
    each_add = float(rule["each_additional_amount"])
    cap      = float(rule["cap_amount"])
    with_profile = avg_first + each_add * (cart_size - 1)
    with_profile = round(min(with_profile, cap), 2)
    savings = round(no_profile - with_profile, 2)
    pct = (savings / no_profile) if no_profile else 0.0
    return {
        "cart_size":          cart_size,
        "avg_first_ship":     avg_first,
        "no_profile_total":   no_profile,
        "with_profile_total": with_profile,
        "savings":            savings,
        "savings_pct":        round(pct, 3),
        "sampled_n":          len(ship_costs),
    }


# --------------------------------------------------------------------------- #
# History I/O                                                                  #
# --------------------------------------------------------------------------- #

def _append_history(record: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if HISTORY_PATH.exists():
        try:
            data = json.loads(HISTORY_PATH.read_text())
            if isinstance(data, list):
                history = data
        except json.JSONDecodeError:
            history = []
    history.append(record)
    HISTORY_PATH.write_text(json.dumps(history, indent=2))


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


def _badge_for_action(action: str) -> str:
    klass = {
        "in_sync":       "badge-ok",
        "created":       "badge-ok",
        "updated":       "badge-ok",
        "would_create":  "badge-info",
        "would_update":  "badge-warn",
        "create_failed": "badge-err",
        "update_failed": "badge-err",
    }.get(action, "badge-muted")
    return f"<span class='badge {klass}'>{action.replace('_',' ')}</span>"


def build_report(plan: dict) -> Path:
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rule  = plan.get("rule") or {}
    prof  = plan.get("profile") or {}
    items = plan.get("items") or {}
    sims  = plan.get("savings") or []

    sim5 = next((s for s in sims if s.get("cart_size") == 5), sims[0] if sims else {})

    sim_rows = "\n".join(
        f"<tr><td class='num'>{s['cart_size']}</td>"
        f"<td class='num'>{_fmt_money(s['no_profile_total'])}</td>"
        f"<td class='num target'>{_fmt_money(s['with_profile_total'])}</td>"
        f"<td class='num delta'>−{_fmt_money(s['savings'])}</td>"
        f"<td class='num'>{s['savings_pct']*100:.0f}%</td></tr>"
        for s in sims
    )

    drift_lines = "".join(f"<li>{x}</li>" for x in prof.get("drift", []))
    drift_block = f"<ul class='drift'>{drift_lines}</ul>" if drift_lines else ""

    skipped_n = len(items.get("skipped", []) or [])
    to_revise = items.get("to_revise", 0)
    total_l   = items.get("total_listings", 0)

    existing = prof.get("existing") or {}
    existing_block = (
        f"<dl class='kv'>"
        f"<dt>Live profile name</dt><dd>{existing.get('profile_name','—')}</dd>"
        f"<dt>Live profile ID</dt><dd><code>{existing.get('profile_id','—')}</code></dd>"
        f"<dt>Live each-additional</dt><dd>{_fmt_money(existing.get('each_additional_amount'))}</dd>"
        f"</dl>"
    ) if existing else "<p class='empty'>No existing flat combined-shipping profile.</p>"

    body = f"""
<section class='hero'>
  <h1>Combined Shipping</h1>
  <p class='sub'>Last run: <code>{run_ts}</code> · Mode: <code>{plan.get('mode','dry-run')}</code></p>
  <div class='stat-grid'>
    <div class='stat'><div class='stat-n'>{_badge_for_action(prof.get('action','noop'))}</div><div class='stat-l'>profile state</div></div>
    <div class='stat'><div class='stat-n'>{to_revise}</div><div class='stat-l'>listings need flip</div></div>
    <div class='stat'><div class='stat-n'>{skipped_n}</div><div class='stat-l'>already opted in</div></div>
    <div class='stat'><div class='stat-n'>{total_l}</div><div class='stat-l'>active listings</div></div>
    <div class='stat'><div class='stat-n'>{_fmt_money(sim5.get('savings'))}</div><div class='stat-l'>5-card buyer saves</div></div>
    <div class='stat'><div class='stat-n'>{(sim5.get('savings_pct',0))*100:.0f}%</div><div class='stat-l'>shipping cut</div></div>
  </div>
</section>

<section class='cfg'>
  <h3>Derived flat-rate rule</h3>
  <ul class='cfg-list'>
    <li>Profile name: <code>{rule.get('profile_name','—')}</code></li>
    <li>Each additional: {_fmt_money(rule.get('each_additional_amount'))}</li>
    <li>Cap (free after): {_fmt_money(rule.get('cap_amount'))}</li>
    <li>First item: honor existing per-listing ship cost</li>
    <li>Lot ratio: {(rule.get('lot_ratio') or 0)*100:.0f}% · band <code>{rule.get('band','—')}</code></li>
  </ul>
  <p class='hint'>{rule.get('rationale','')}</p>
</section>

<section class='cfg'>
  <h3>Live profile</h3>
  {drift_block}
  {existing_block}
</section>

<section>
  <h3>Savings simulation</h3>
  <p class='hint'>Based on avg first-item ship of {_fmt_money(sim5.get('avg_first_ship'))}
    (sampled {sim5.get('sampled_n',0)} listings; falls back to $4.50 when shipping
    metadata absent).</p>
  <div class='tbl-wrap'>
    <table class='reprice-tbl'>
      <thead><tr><th>Cart size</th><th>Without profile</th><th>With profile</th><th>Savings</th><th>% off</th></tr></thead>
      <tbody>{sim_rows}</tbody>
    </table>
  </div>
</section>

<section class='cfg'>
  <h3>How to read this</h3>
  <ul class='cfg-list'>
    <li><b>Profile state</b> — whether the flat-rate combined-shipping profile is in_sync, would_create, or drift.</li>
    <li><b>Listings need flip</b> — count of active items that still need <code>Item.ShippingDetails.ApplyShippingDiscount=true</code>.</li>
    <li><b>5-card buyer saves</b> — out-of-pocket shipping difference for a buyer who bundles 5 cards.</li>
  </ul>
  <p class='hint'>Dry-run safe. Apply with <code>python combined_shipping.py --apply</code>.</p>
</section>
"""

    extra_css = (
        "<style>"
        ".hero{padding:24px 0 12px}.hero h1{margin:0 0 4px;font-family:'Bebas Neue',sans-serif;font-size:56px;letter-spacing:.02em}.hero .sub{color:var(--text-muted)}"
        ".stat-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:18px 0}"
        ".stat{background:var(--surface);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 16px}"
        ".stat-n{font-family:'Bebas Neue',sans-serif;font-size:32px;color:var(--gold);line-height:1}"
        ".stat-l{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.08em;margin-top:4px}"
        ".cfg{background:var(--surface-2);border:1px solid var(--border);border-radius:var(--r-md);padding:14px 18px;margin:18px 0}"
        ".cfg h3{margin:0 0 8px;font-size:14px;text-transform:uppercase;letter-spacing:.1em;color:var(--text-muted)}"
        ".cfg-list{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:6px 18px}"
        ".cfg .hint{color:var(--text-muted);font-size:13px;margin:10px 0 0}"
        ".badge{display:inline-block;padding:3px 9px;border-radius:999px;font-size:13px;font-weight:600}"
        ".badge-ok{background:rgba(127,199,122,.15);color:var(--success)}"
        ".badge-warn{background:rgba(212,175,55,.15);color:var(--gold)}"
        ".badge-err{background:rgba(220,80,80,.15);color:var(--danger)}"
        ".badge-info{background:rgba(120,160,220,.15);color:var(--text)}"
        ".badge-muted{background:var(--surface);color:var(--text-muted)}"
        ".drift{margin:8px 0 0 18px;color:var(--gold)}"
        ".kv{display:grid;grid-template-columns:220px 1fr;gap:4px 18px;margin:8px 0}"
        ".kv dt{color:var(--text-muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.kv dd{margin:0;color:var(--text)}"
        ".tbl-wrap{overflow-x:auto;border-radius:var(--r-md);border:1px solid var(--border);margin:8px 0 24px}"
        "table.reprice-tbl{width:100%;border-collapse:collapse;font-size:13px}"
        ".reprice-tbl th,.reprice-tbl td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--border);vertical-align:top}"
        ".reprice-tbl th{background:var(--surface-2);color:var(--text-muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}"
        ".reprice-tbl tr:hover td{background:var(--surface-2)}"
        ".reprice-tbl .num{text-align:right;font-variant-numeric:tabular-nums;font-family:'JetBrains Mono',monospace}"
        ".reprice-tbl .target{color:var(--gold);font-weight:600}.reprice-tbl .delta{color:var(--danger)}"
        ".empty{color:var(--text-muted);padding:20px;text-align:center;background:var(--surface);border:1px dashed var(--border);border-radius:var(--r-md)}"
        "</style>"
    )
    html = promote.html_shell(
        "Combined Shipping · Harpua2001", body,
        extra_head=extra_css, active_page="combined_shipping.html",
    )
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(html, encoding="utf-8")
    return REPORT_PATH


# --------------------------------------------------------------------------- #
# Orchestration                                                               #
# --------------------------------------------------------------------------- #

def _load_listings() -> list[dict]:
    if not LISTINGS_SNAPSHOT.exists():
        return []
    raw = json.loads(LISTINGS_SNAPSHOT.read_text())
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        return raw.get("listings") or []
    return []


def run(args: argparse.Namespace) -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    listings = _load_listings()
    print(f"  Loaded {len(listings)} active listings from snapshot")

    rule = derive_combined_shipping_rule(listings)
    print(f"  Derived rule: {rule['rationale']}")

    # Acquire Trading token. On dry-runs we still read the existing profile
    # if creds are available; on a failure we fall through with no live data.
    token: str
    if args.apply:
        print("  Acquiring eBay access token (Trading)...")
        token = promote.get_access_token(ebay_cfg)
    else:
        try:
            token = promote.get_access_token(ebay_cfg)
        except Exception as exc:
            print(f"  Token unavailable on dry-run ({exc}); profile read will be skipped.")
            token = "<DRY-RUN-TOKEN>"

    # --- Profile sync ---
    prof_result: dict = {"action": "skipped"}
    if not args.items_only:
        prof_result = sync_combined_shipping(
            token, rule, ebay_cfg, dry_run=not args.apply,
        )
        print(f"  Profile action: {prof_result['action']}")
        if prof_result.get("drift"):
            for d in prof_result["drift"]:
                print(f"    drift: {d}")

    # --- Per-listing flip ---
    items_result: dict = {"total_listings": len(listings), "to_revise": 0,
                          "skipped": [], "batches": 0, "dry_run": not args.apply}
    if not args.profile_only:
        items_result = apply_to_listings(
            token, listings, ebay_cfg, dry_run=not args.apply,
        )
        print(f"  Listings — to_revise: {items_result['to_revise']}  "
              f"already_opted_in: {len(items_result['skipped'])}  "
              f"batches: {items_result['batches']}")

    # --- Savings sim ---
    sims = [simulate_savings(listings, rule, cart_size=n) for n in (2, 3, 5, 10)]
    sim5 = next(s for s in sims if s["cart_size"] == 5)
    print(f"  Savings sim — 5-card cart: ${sim5['no_profile_total']:.2f} → "
          f"${sim5['with_profile_total']:.2f} (saves ${sim5['savings']:.2f}, "
          f"{sim5['savings_pct']*100:.0f}%)")

    # --- Persist plan ---
    plan = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode":         "apply" if args.apply else "dry-run",
        "rule":         rule,
        "profile":      prof_result,
        "items":        items_result,
        "savings":      sims,
    }
    PLAN_PATH.write_text(json.dumps(plan, indent=2))
    print(f"  Plan: {PLAN_PATH}")

    # --- History ---
    _append_history({
        "ran_at":        plan["generated_at"],
        "mode":          plan["mode"],
        "profile_action": prof_result.get("action"),
        "drift":         prof_result.get("drift"),
        "to_revise":     items_result.get("to_revise"),
        "skipped":       len(items_result.get("skipped") or []),
        "savings_5":     sim5,
    })

    # --- HTML ---
    report = build_report(plan)
    print(f"  Report: {report}")
    if not args.apply:
        print("  Dry run only. Re-run with --apply to push changes to eBay.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="Push changes to eBay (default: dry run).")
    ap.add_argument("--profile-only", action="store_true",
                    help="Sync the discount profile only; skip per-item flip.")
    ap.add_argument("--items-only", action="store_true",
                    help="Flip per-item ApplyShippingDiscount only; skip profile sync.")
    args = ap.parse_args()
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
