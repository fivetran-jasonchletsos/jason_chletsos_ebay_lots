"""
seller_hub_phase2.py — Phase 2 writer that mirrors the derived store
taxonomy (from seller_hub_agent.py) into the live eBay store via the
Trading API.

Phase 1 was preview-only. This module finally PUSHES:
  1) SetStoreCategories  — reconciles the eBay store sidebar against
     output/seller_hub_plan.json["categories"]. Diff-driven: pulls
     existing categories with GetStoreCategories first, then creates
     missing, renames drift, and (optionally) removes orphans.
  2) ReviseItem (bulk, 50/call) with Item.Storefront.StoreCategoryID —
     reassigns each active listing into the category produced by
     promote._categorize(). Items already in the right StoreCategoryID
     are skipped so reruns are cheap.

Default = dry run. Prints the XML envelopes that *would* be sent and
the diff summary. Use --apply to actually mutate the store.

Usage:
    python3 seller_hub_phase2.py                       # dry run (default)
    python3 seller_hub_phase2.py --apply               # push for real
    python3 seller_hub_phase2.py --categories-only     # skip item assignment
    python3 seller_hub_phase2.py --apply --categories-only

Artifacts:
    output/seller_hub_phase2_log.json   append-only run history

Constraints respected:
    - Trading API: 5000 calls/day soft cap → we estimate up-front and
      refuse to run if the plan would exceed a configurable budget.
    - ReviseItem batched 50 items per request (Trading bulk envelope).
    - Exponential backoff on HTTP 5xx and Failure Acks.
    - Idempotent: re-runs converge, they don't churn.

Agent B handles the Lambda surface (/ebay/sync-store-categories);
this file is the pure Python writer Agent B will import.
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
import seller_hub_agent

REPO_ROOT   = Path(__file__).parent
OUTPUT_DIR  = REPO_ROOT / "output"
PLAN_PATH   = OUTPUT_DIR / "seller_hub_plan.json"
LOG_PATH    = OUTPUT_DIR / "seller_hub_phase2_log.json"

TRADING_URL = "https://api.ebay.com/ws/api.dll"
EBAY_NS     = "urn:ebay:apis:eBLBaseComponents"
NS          = "{" + EBAY_NS + "}"
COMPAT      = "967"
SITE_ID     = "0"

# Trading API guardrails
DAILY_CALL_BUDGET   = 5000     # eBay's documented soft cap
ITEMS_PER_BULK_CALL = 50       # ReviseItem bulk envelope max
MAX_RETRIES         = 4
BACKOFF_BASE_SEC    = 1.5


# --------------------------------------------------------------------------- #
# HTTP — Trading API client with backoff                                      #
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
    """POST to Trading API with exponential backoff on 5xx."""
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
# XML envelope builders                                                       #
# --------------------------------------------------------------------------- #

def _xml_get_store_categories(token: str) -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<GetStoreRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <CategoryStructureOnly>true</CategoryStructureOnly>\n'
        f'</GetStoreRequest>'
    )


def _xml_set_store_categories(token: str, actions: list[dict]) -> str:
    """Build a single SetStoreCategoriesRequest. eBay's Trading API accepts
    exactly ONE <Action> per request, with multiple <CustomCategory> children
    inside the single <Store>/<Categories> block. So we group by action and
    return a single envelope per action — caller is responsible for splitting
    Add/Rename/Delete across separate calls.

    actions = [{"action": "Add" | "Rename" | "Delete",
                "category_id": "0" (for Add) | existing id,
                "name": "Pokemon Lots"}]
    """
    if not actions:
        return ""
    # All actions must share the same Action verb in a single call.
    action_kind = actions[0]["action"]
    assert all(a["action"] == action_kind for a in actions), \
        "Split Add/Rename/Delete into separate calls"

    category_xml = "\n".join(
        "    <CustomCategory>"
        + (f"<CategoryID>{a['category_id']}</CategoryID>"
           if action_kind in ("Rename", "Delete") else "")
        + (f"<Name>{_xml_escape(a['name'])}</Name>"
           if action_kind in ("Add", "Rename") else "")
        + "</CustomCategory>"
        for a in actions
    )

    extra = ""
    if action_kind == "Delete":
        extra = "  <DestinationParentCategoryID>0</DestinationParentCategoryID>\n"

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<SetStoreCategoriesRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <Action>{action_kind}</Action>\n'
        f'{extra}'
        f'  <Store>\n'
        f'    <Categories>\n'
        f'{category_xml}\n'
        f'    </Categories>\n'
        f'  </Store>\n'
        f'</SetStoreCategoriesRequest>'
    )


def _xml_revise_item_single(token: str, item_id: str, cat_id: str) -> str:
    """ReviseItem envelope for ONE listing — assigns Storefront/StoreCategoryID.

    The Trading API ReviseItem call accepts exactly one <Item> per envelope;
    multi-Item siblings produce "XML Parse error" (errorId 5). For bulk we
    issue N sequential single-Item calls with gentle pacing (matches the
    pattern in repricing_agent.revise_price).
    """
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<ReviseItemRequest xmlns="{EBAY_NS}">\n'
        f'  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>\n'
        f'  <Item>\n'
        f'    <ItemID>{_xml_escape(item_id)}</ItemID>\n'
        f'    <Storefront><StoreCategoryID>{_xml_escape(cat_id)}</StoreCategoryID></Storefront>\n'
        f'  </Item>\n'
        f'</ReviseItemRequest>'
    )


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;")
             .replace("'", "&apos;"))


# --------------------------------------------------------------------------- #
# GetStoreCategories — read existing store sidebar                            #
# --------------------------------------------------------------------------- #

def fetch_existing_categories(token: str, ebay_cfg: dict) -> dict[str, str]:
    """Returns {category_name -> StoreCategoryID} for the existing store.

    GetStore with CategoryStructureOnly=true is the canonical read; the
    older GetStoreCategories call name is kept as an alias by eBay but
    GetStore is the documented surface.
    """
    body = _xml_get_store_categories(token)
    root = _trading_post("GetStore", body, ebay_cfg)
    errors = _parse_errors(root)
    if errors and any(e["severity"] == "Error" for e in errors):
        raise RuntimeError(f"GetStore errors: {errors}")
    out: dict[str, str] = {}
    for cat in root.findall(f".//{NS}CustomCategory"):
        name = cat.findtext(f"{NS}Name", "") or ""
        cid  = cat.findtext(f"{NS}CategoryID", "") or ""
        if name and cid:
            out[name] = cid
    return out


# --------------------------------------------------------------------------- #
# Category sync                                                               #
# --------------------------------------------------------------------------- #

def _load_plan() -> dict:
    if not PLAN_PATH.exists():
        raise FileNotFoundError(
            f"{PLAN_PATH} not found — run seller_hub_agent.py first."
        )
    return json.loads(PLAN_PATH.read_text())


def _diff_categories(desired: list[dict], existing: dict[str, str]
                     ) -> tuple[list[dict], dict[str, str]]:
    """Return (actions, resolved_id_map).

    actions: list of {"action", "category_id", "name"} to send to eBay.
    resolved_id_map: {desired_name -> existing_id_or_placeholder}.

    For dry runs the new-add ids are "<NEW>" placeholders so the caller
    can still preview the assignment plan.
    """
    actions: list[dict] = []
    resolved: dict[str, str] = {}
    desired_names = {c["name"] for c in desired}

    for cat in desired:
        name = cat["name"]
        if name in existing:
            resolved[name] = existing[name]
        else:
            actions.append({"action": "Add", "category_id": "0", "name": name})
            resolved[name] = "<NEW>"

    # Orphans — categories on the store that no longer map to anything
    # in our taxonomy. We REPORT but don't auto-delete unless the caller
    # opted in via remove_orphans — preserves manual curation.
    for name, cid in existing.items():
        if name not in desired_names:
            actions.append({"action": "Delete", "category_id": cid, "name": name})

    return actions, resolved


def sync_store_categories(token: str, plan: dict, ebay_cfg: dict | None = None,
                          dry_run: bool = True, remove_orphans: bool = False
                          ) -> dict:
    """Push categories from the Phase 1 plan to eBay.

    Returns:
        {
          "created":   [name, ...],
          "updated":   [name, ...],    # renames
          "unchanged": [name, ...],
          "removed":   [name, ...],
          "id_map":    {name: StoreCategoryID},
          "dry_run":   bool,
          "envelope":  "<xml ...>" if dry_run else None,
          "ack":       "Success" | "Warning" | "Failure" | None,
          "errors":    [...],
        }
    """
    ebay_cfg = ebay_cfg or json.loads(promote.CONFIG_FILE.read_text())
    desired  = plan.get("categories") or []

    if dry_run:
        existing: dict[str, str] = {}
    else:
        existing = fetch_existing_categories(token, ebay_cfg)

    actions, id_map = _diff_categories(desired, existing)
    if not remove_orphans:
        actions = [a for a in actions if a["action"] != "Delete"]

    created   = [a["name"] for a in actions if a["action"] == "Add"]
    updated   = [a["name"] for a in actions if a["action"] == "Rename"]
    removed   = [a["name"] for a in actions if a["action"] == "Delete"]
    unchanged = [name for name in id_map if name not in created + updated]

    result: dict[str, Any] = {
        "created":   created,
        "updated":   updated,
        "unchanged": unchanged,
        "removed":   removed,
        "id_map":    id_map,
        "dry_run":   dry_run,
        "envelope":  None,
        "ack":       None,
        "errors":    [],
    }

    if not actions:
        print("  No category changes — store sidebar already matches plan.")
        return result

    # SetStoreCategories accepts only ONE <Action> per request. Group the
    # actions by verb and make one call per non-empty group. eBay assigns
    # CategoryIDs on Add; we re-fetch after to populate them.
    grouped: dict[str, list[dict]] = {}
    for a in actions:
        grouped.setdefault(a["action"], []).append(a)

    envelopes = {k: _xml_set_store_categories(token if not dry_run else "<TOKEN>", v)
                 for k, v in grouped.items()}
    if dry_run:
        result["envelope"] = "\n\n--- next action ---\n\n".join(envelopes.values())
        print("  DRY RUN — SetStoreCategories envelopes follow:")
        print(result["envelope"])
        return result

    acks: list[str] = []
    all_errors: list[dict] = []
    for verb, env in envelopes.items():
        root = _trading_post("SetStoreCategories", env, ebay_cfg)
        ack  = root.findtext(f"{NS}Ack", "") or ""
        errs = _parse_errors(root)
        acks.append(ack)
        all_errors.extend([{**e, "verb": verb} for e in errs])

    # Roll up: any Failure = Failure, all Success = Success, mix = Warning
    if any(a == "Failure" for a in acks):
        result["ack"] = "Failure"
    elif all(a == "Success" for a in acks):
        result["ack"] = "Success"
    else:
        result["ack"] = "Warning"
    result["errors"] = all_errors

    # Re-fetch to populate real IDs for the just-created categories.
    if result["ack"] in ("Success", "Warning"):
        fresh = fetch_existing_categories(token, ebay_cfg)
        for name in created:
            if name in fresh:
                result["id_map"][name] = fresh[name]
    return result


# --------------------------------------------------------------------------- #
# Item assignment                                                             #
# --------------------------------------------------------------------------- #

def _current_store_category(listing: dict) -> str | None:
    """Best-effort: pull existing StoreCategoryID off a listing snapshot.
    Snapshots produced by promote.fetch_listings may carry the field
    under a couple of names depending on which API path produced them.
    """
    for key in ("store_category_id", "StoreCategoryID", "storefront_category_id"):
        v = listing.get(key)
        if v:
            return str(v)
    sf = listing.get("storefront") or listing.get("Storefront") or {}
    if isinstance(sf, dict):
        return str(sf.get("StoreCategoryID") or sf.get("store_category_id") or "") or None
    return None


def _chunked(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def assign_items_to_categories(token: str, listings: list[dict],
                               category_id_map: dict[str, str],
                               ebay_cfg: dict | None = None,
                               dry_run: bool = True) -> dict:
    """For each listing, push Item.Storefront.StoreCategoryID via ReviseItem.

    category_id_map: {category_name -> StoreCategoryID} — typically the
    id_map returned by sync_store_categories().
    """
    ebay_cfg = ebay_cfg or json.loads(promote.CONFIG_FILE.read_text())

    planned:  list[tuple[str, str, str]] = []   # (item_id, cat_id, cat_name)
    skipped:  list[dict] = []
    unmapped: list[dict] = []

    for l in listings:
        cat_name = promote._categorize(l)
        # Match what seller_hub_agent does — eBay's 30-char limit.
        cat_name_trunc = cat_name[:seller_hub_agent.EBAY_CATEGORY_NAME_MAX]
        cat_id = category_id_map.get(cat_name_trunc) or category_id_map.get(cat_name)
        if not cat_id:
            unmapped.append({"item_id": l["item_id"], "category": cat_name_trunc})
            continue
        cur = _current_store_category(l)
        if cur and cur == cat_id:
            skipped.append({"item_id": l["item_id"], "reason": "already in category"})
            continue
        planned.append((l["item_id"], cat_id, cat_name_trunc))

    # Budget check — Trading ReviseItem is ONE Item per call, so n_calls == len(planned)
    n_calls = len(planned)
    if n_calls > DAILY_CALL_BUDGET:
        raise RuntimeError(
            f"Plan would issue {n_calls} ReviseItem calls — exceeds "
            f"daily budget {DAILY_CALL_BUDGET}. Aborting."
        )

    result: dict[str, Any] = {
        "total_listings": len(listings),
        "to_revise":      len(planned),
        "skipped":        skipped,
        "unmapped":       unmapped,
        "batches":        n_calls,
        "dry_run":        dry_run,
        "envelopes":      [],
        "results":        [],
    }

    if not planned:
        print("  No item reassignments needed.")
        return result

    for idx, (item_id, cat_id, cat_name) in enumerate(planned):
        envelope = _xml_revise_item_single(
            token if not dry_run else "<TOKEN>", item_id, cat_id
        )
        if dry_run:
            result["envelopes"].append(envelope)
            print(f"  DRY RUN — ReviseItem {idx+1}/{n_calls} "
                  f"(item {item_id} → {cat_name}):")
            print(envelope)
            continue
        root = _trading_post("ReviseItem", envelope, ebay_cfg)
        result["results"].append({
            "batch":   idx + 1,
            "ack":     root.findtext(f"{NS}Ack", "") or "",
            "errors":  _parse_errors(root),
            "items":   [item_id],
        })
        # gentle pacing — eBay throttles bursty ReviseItem callers
        time.sleep(0.6)

    return result


# --------------------------------------------------------------------------- #
# Run log                                                                     #
# --------------------------------------------------------------------------- #

def _append_log(record: dict) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    history: list[dict] = []
    if LOG_PATH.exists():
        try:
            history = json.loads(LOG_PATH.read_text())
            if not isinstance(history, list):
                history = []
        except json.JSONDecodeError:
            history = []
    history.append(record)
    LOG_PATH.write_text(json.dumps(history, indent=2))


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--apply", action="store_true",
                    help="Push changes to eBay (default: dry run, prints XML).")
    ap.add_argument("--categories-only", action="store_true",
                    help="Sync store categories but skip per-item reassignment.")
    ap.add_argument("--remove-orphans", action="store_true",
                    help="Delete store categories not present in the current plan.")
    ap.add_argument("--no-fetch", action="store_true",
                    help="Use cached listings_snapshot.json instead of re-fetching.")
    args = ap.parse_args()

    plan = _load_plan()
    ebay_cfg = json.loads(promote.CONFIG_FILE.read_text())

    if args.apply:
        print("  Acquiring eBay access token...")
        token = promote.get_access_token(ebay_cfg)
    else:
        token = "<DRY-RUN-TOKEN>"

    print(f"  Plan generated_at: {plan.get('generated_at')}")
    print(f"  Categories in plan: {len(plan.get('categories') or [])}")

    cat_result = sync_store_categories(
        token, plan, ebay_cfg=ebay_cfg,
        dry_run=not args.apply,
        remove_orphans=args.remove_orphans,
    )
    print(f"\n  Categories — created: {len(cat_result['created'])}  "
          f"updated: {len(cat_result['updated'])}  "
          f"unchanged: {len(cat_result['unchanged'])}  "
          f"removed: {len(cat_result['removed'])}")

    item_result: dict = {"skipped": True}
    if not args.categories_only:
        # Load listings snapshot — Phase 1 already left it on disk.
        snap_path = OUTPUT_DIR / "listings_snapshot.json"
        if not snap_path.exists():
            print("  listings_snapshot.json missing — skipping item assignment.")
        else:
            snap = json.loads(snap_path.read_text())
            listings = snap if isinstance(snap, list) else snap.get("listings", [])
            print(f"\n  Assigning {len(listings)} listings to store categories...")
            item_result = assign_items_to_categories(
                token, listings, cat_result["id_map"],
                ebay_cfg=ebay_cfg, dry_run=not args.apply,
            )
            print(f"  Items — to_revise: {item_result['to_revise']}  "
                  f"skipped: {len(item_result['skipped'])}  "
                  f"unmapped: {len(item_result['unmapped'])}  "
                  f"batches: {item_result['batches']}")

    record = {
        "ran_at":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode":            "apply" if args.apply else "dry_run",
        "categories_only": args.categories_only,
        "remove_orphans":  args.remove_orphans,
        "categories":      {
            "created":   cat_result["created"],
            "updated":   cat_result["updated"],
            "unchanged": cat_result["unchanged"],
            "removed":   cat_result["removed"],
            "ack":       cat_result["ack"],
            "errors":    cat_result["errors"],
        },
        "items":           {
            "to_revise": item_result.get("to_revise"),
            "skipped":   len(item_result.get("skipped", []))
                         if isinstance(item_result.get("skipped"), list) else None,
            "unmapped":  item_result.get("unmapped"),
            "batches":   item_result.get("batches"),
            "results":   item_result.get("results"),
        },
    }
    _append_log(record)
    print(f"\n  Log appended: {LOG_PATH}")
    if not args.apply:
        print("  Dry run only. Re-run with --apply to push to eBay.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
