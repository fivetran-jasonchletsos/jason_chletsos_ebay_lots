"""
sold_reconciler_agent.py — close the loop between eBay sales and CollX.

When a card sells on eBay, CollX has no idea (it has no inbound API). This
agent pulls SoldList from the Trading API's GetMyeBaySelling call over the
last N days, then:

  1. Marks the corresponding row in linkage_db as `sold` with sold_at,
     sold_price, and buyer (when --apply is passed).
  2. Emits output/sold_reconciler_plan.json — the "mark these sold in CollX"
     list (since CollX has no API, this is the manual to-do for Jason).
  3. Renders docs/sold_reconciler.html — a small buyer-site-themed report
     showing the window summary and the CollX to-do list.

Default mode is dry-run. Pass --apply to actually update the linkage DB.

CLI:
    python3 sold_reconciler_agent.py                  # dry run, 30-day window
    python3 sold_reconciler_agent.py --days 7         # narrower window
    python3 sold_reconciler_agent.py --apply          # write to linkage DB

Architecture notes:
- OAuth scope set mirrors push_to_ebay.WRITE_SCOPES so the same refresh
  token works without requiring an additional consent dance.
- Trading-API call shape mirrors push_to_ebay.trading_headers + XML
  envelope for code-style consistency.
- Uses linkage_db.mark_sold() as the only write path. Does not touch the
  schema or any other agent.
"""
from __future__ import annotations

import argparse
import base64
import html as html_lib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import requests

import linkage_db

REPO_ROOT  = Path(__file__).parent
CONFIG     = REPO_ROOT / "configuration.json"
PLAN_PATH  = REPO_ROOT / "output" / "sold_reconciler_plan.json"
HTML_PATH  = REPO_ROOT / "docs" / "sold_reconciler.html"

TRADING_URL  = "https://api.ebay.com/ws/api.dll"
OAUTH_URL    = "https://api.ebay.com/identity/v1/oauth2/token"
COMPAT_LEVEL = "967"
SITE_ID_US   = "0"
NS           = "urn:ebay:apis:eBLBaseComponents"

# Mirror push_to_ebay's WRITE_SCOPES — broader than read-only, ensures the
# Trading-API IAF token is accepted for GetMyeBaySelling (which Trading
# treats as a seller-context call).
WRITE_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
])


# ---------------------------------------------------------------------------
# eBay auth + Trading API plumbing (mirrors push_to_ebay.py style)
# ---------------------------------------------------------------------------

def get_write_token(cfg: dict) -> str:
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post(OAUTH_URL,
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token",
              "refresh_token": cfg["refresh_token"],
              "scope": WRITE_SCOPES},
        timeout=30,
    )
    if not r.ok:
        raise SystemExit(f"OAuth failed ({r.status_code}): {r.text[:400]}")
    return r.json()["access_token"]


def trading_headers(call_name: str, cfg: dict, access_token: str) -> dict:
    return {
        "X-EBAY-API-SITEID":              SITE_ID_US,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
        "X-EBAY-API-IAF-TOKEN":           access_token,
        "Content-Type":                   "text/xml",
    }


# ---------------------------------------------------------------------------
# Tiny XML helpers (regex-based, mirrors push_to_ebay.py find_tag / find_all)
# ---------------------------------------------------------------------------

def find_tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else None


def find_all_blocks(xml: str, tag: str) -> list[str]:
    return [m.group(1)
            for m in re.finditer(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)]


def xml_escape(s) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


# ---------------------------------------------------------------------------
# GetMyeBaySelling — pull SoldList for the window
# ---------------------------------------------------------------------------

def build_sold_list_xml(token: str, days: int, page: int = 1,
                        per_page: int = 100) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<GetMyeBaySellingRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <SoldList>
    <Include>true</Include>
    <DurationInDays>{int(days)}</DurationInDays>
    <Pagination>
      <EntriesPerPage>{int(per_page)}</EntriesPerPage>
      <PageNumber>{int(page)}</PageNumber>
    </Pagination>
  </SoldList>
</GetMyeBaySellingRequest>"""


def fetch_sold(cfg: dict, token: str, days: int) -> list[dict]:
    """Return a flat list of sold entries:
        {ebay_item_id, title, sold_price, sold_at, buyer}
    Iterates pages until TotalNumberOfPages is reached."""
    headers = trading_headers("GetMyeBaySelling", cfg, token)
    out: list[dict] = []
    page = 1
    while True:
        body = build_sold_list_xml(token, days, page=page, per_page=100)
        r = requests.post(TRADING_URL, headers=headers, data=body, timeout=60)
        if not r.ok:
            raise SystemExit(
                f"GetMyeBaySelling failed ({r.status_code}): {r.text[:400]}"
            )
        xml = r.text
        ack = find_tag(xml, "Ack") or ""
        if ack.lower() not in ("success", "warning"):
            # Surface the first error message so it's debuggable.
            err = find_tag(xml, "LongMessage") or find_tag(xml, "ShortMessage") or "(no detail)"
            raise SystemExit(f"GetMyeBaySelling Ack={ack!r}: {err}")

        sold_list = find_tag(xml, "SoldList") or ""
        item_blocks = find_all_blocks(sold_list, "Item")
        for block in item_blocks:
            entry = _parse_item_block(block)
            if entry:
                out.append(entry)

        # Pagination: stop when we've consumed all pages.
        total_pages_str = find_tag(sold_list, "TotalNumberOfPages") or "1"
        try:
            total_pages = int(total_pages_str)
        except ValueError:
            total_pages = 1
        if page >= total_pages or not item_blocks:
            break
        page += 1
    return out


def _parse_item_block(block: str) -> dict | None:
    ebay_item_id = find_tag(block, "ItemID")
    if not ebay_item_id:
        return None
    title = find_tag(block, "Title") or ""

    # Sold price + sold_at + buyer all live under the first Transaction node.
    tx_block = ""
    tx_array = find_tag(block, "TransactionArray") or ""
    tx_blocks = find_all_blocks(tx_array, "Transaction")
    if tx_blocks:
        tx_block = tx_blocks[0]

    sold_price = 0.0
    sold_at: str | None = None
    buyer: str | None = None
    if tx_block:
        amount_paid = find_tag(tx_block, "AmountPaid")
        if amount_paid:
            try:
                sold_price = float(amount_paid)
            except ValueError:
                sold_price = 0.0
        # CreatedDate is the canonical sale timestamp from Trading.
        sold_at = find_tag(tx_block, "CreatedDate") or None
        buyer_block = find_tag(tx_block, "Buyer") or ""
        buyer = find_tag(buyer_block, "UserID") if buyer_block else None

    # Fallback: SellingStatus > CurrentPrice (covers single-quantity FixedPriceItem
    # where the Transaction array is sometimes thin).
    if sold_price == 0.0:
        selling_status = find_tag(block, "SellingStatus") or ""
        cp = find_tag(selling_status, "CurrentPrice")
        if cp:
            try:
                sold_price = float(cp)
            except ValueError:
                pass

    return {
        "ebay_item_id": ebay_item_id,
        "title":        title,
        "sold_price":   sold_price,
        "sold_at":      sold_at,
        "buyer":        buyer,
    }


# ---------------------------------------------------------------------------
# Match to linkage DB + classify
# ---------------------------------------------------------------------------

def classify_sales(sold: list[dict]) -> tuple[list[dict], list[dict]]:
    """Returns (linked, ebay_only).
    `linked` rows carry collx_id from the linkage DB.
    `ebay_only` rows are pre-CollX (or otherwise unmapped) sales."""
    linked: list[dict] = []
    ebay_only: list[dict] = []
    for entry in sold:
        row = linkage_db.get_link_by_ebay(entry["ebay_item_id"])
        if row:
            entry = dict(entry)
            entry["collx_id"]      = row.get("collx_id")
            entry["listed_price"]  = row.get("listed_price")
            entry["already_sold"]  = (row.get("status") == "sold")
            linked.append(entry)
        else:
            ebay_only.append(entry)
    return linked, ebay_only


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

def write_plan(linked: list[dict], ebay_only: list[dict], days: int) -> None:
    PLAN_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at":  datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_days":   days,
        "totals": {
            "sold_in_window": len(linked) + len(ebay_only),
            "linked_to_collx": len(linked),
            "ebay_only":       len(ebay_only),
        },
        # The actionable list — Jason copies these collx_ids into CollX
        # and marks each card sold there. CollX has no inbound API.
        "mark_sold_in_collx": [
            {
                "collx_id":     row["collx_id"],
                "ebay_item_id": row["ebay_item_id"],
                "title":        row["title"],
                "sold_price":   row["sold_price"],
                "sold_at":      row["sold_at"],
                "buyer":        row.get("buyer"),
                "already_marked_sold_in_linkage": row.get("already_sold", False),
            }
            for row in linked
        ],
        "ebay_only_sales": [
            {
                "ebay_item_id": row["ebay_item_id"],
                "title":        row["title"],
                "sold_price":   row["sold_price"],
                "sold_at":      row["sold_at"],
                "buyer":        row.get("buyer"),
            }
            for row in ebay_only
        ],
    }
    PLAN_PATH.write_text(json.dumps(payload, indent=2))


def _h(s) -> str:
    """HTML-escape for the static report. Stripped of pipe-as-separator
    aesthetics per project copy rules."""
    if s is None:
        return ""
    return html_lib.escape(str(s))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="Reconcile eBay sold listings against the CollX linkage DB."
    )
    ap.add_argument("--days", type=int, default=30,
                    help="Window of days to pull SoldList for (default 30, eBay max 60).")
    ap.add_argument("--apply", action="store_true",
                    help="Write sold-state to linkage DB. Without this flag, dry-run only.")
    args = ap.parse_args()

    if not CONFIG.exists():
        raise SystemExit(f"Missing {CONFIG}.")
    cfg = json.loads(CONFIG.read_text())

    print(f"Pulling SoldList for the last {args.days} days...")
    token = get_write_token(cfg)
    sold = fetch_sold(cfg, token, args.days)
    print(f"  eBay returned {len(sold)} sold listings in the window.")

    linked, ebay_only = classify_sales(sold)
    print(f"  Matched to CollX (linkage DB): {len(linked)}")
    print(f"  eBay-only (pre-CollX or unlinked): {len(ebay_only)}")

    applied_count = 0
    if args.apply:
        for row in linked:
            ok = linkage_db.mark_sold(
                ebay_item_id=row["ebay_item_id"],
                sold_price=row["sold_price"] or 0.0,
                sold_at=row["sold_at"],
                buyer=row.get("buyer"),
            )
            if ok:
                applied_count += 1
        print(f"  Wrote {applied_count} sold rows to linkage DB.")
    else:
        print("Dry run only. Re-run with --apply to mark sold in linkage DB.")

    write_plan(linked, ebay_only, args.days)

    print()
    print(f"Plan written to: {PLAN_PATH}")

    if linked:
        print()
        print("Cards to mark sold in CollX:")
        for row in linked:
            sp = row.get("sold_price") or 0.0
            print(f"  collx_id={row['collx_id']:<24} "
                  f"item={row['ebay_item_id']:<14} "
                  f"${sp:>7.2f}   {row['title'][:60]}")
    else:
        print()
        print("No CollX-linked sales in this window — nothing to mark in CollX.")


if __name__ == "__main__":
    main()
