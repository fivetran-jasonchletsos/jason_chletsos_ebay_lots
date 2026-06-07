"""Emergency Saturday-night price drop + Best Offer enablement.

Implements the agent consensus plan:
  1. All singles currently ≤$5  → $1.99 BIN
  2. Named high-value items     → specific drop prices
  3. Lots and key BINs          → Best Offer enabled (auto-accept at floor)

Does NOT convert Etienne or Mahomes to auctions here — eBay's Trading API
cannot convert a FixedPriceItem to an Auction mid-listing; you must end the
listing and relist as Chinese/Dutch. That step is logged as instructions.

Run:
    python3 emergency_reprice.py --dry-run   # preview only
    python3 emergency_reprice.py --apply     # push to eBay
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

REPO = Path(__file__).parent
EBAY_NS = "urn:ebay:apis:eBLBaseComponents"
TRADING_URL = "https://api.ebay.com/ws/api.dll"

# ---------------------------------------------------------------------------
# Price plan — agent consensus
# ---------------------------------------------------------------------------

# Named items get specific prices + Best Offer config.
# Format: item_id -> {price, best_offer, auto_accept, auto_decline, label}
NAMED_DROPS: dict[str, dict] = {
    "306913934898": {"price": 24.99,  "best_offer": True,  "auto_accept": 18.00, "auto_decline": 12.00, "label": "Warren Moon 20-card lot"},
    "306985615478": {"price": 34.56,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Travis Etienne AUTO (keep BIN — see auction note below)"},
    "306939333836": {"price":  9.99,  "best_offer": True,  "auto_accept":  7.00, "auto_decline":  5.00, "label": "Cam Ward X-Fractor RC (Mega Exclusive retail pull, not hobby — panel adjusted)"},
    "306904068997": {"price": 12.99,  "best_offer": True,  "auto_accept":  9.00, "auto_decline":  7.00, "label": "Marcus Allen 21-card lot"},
    "306914547105": {"price": 10.99,  "best_offer": True,  "auto_accept":  8.00, "auto_decline":  6.00, "label": "Andre Rison lot"},
    "306962137413": {"price":  8.99,  "best_offer": True,  "auto_accept":  6.50, "auto_decline":  4.00, "label": "Will Howard Silver Prizm RC"},
    "306962126602": {"price":  6.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Matthew Golden Donruss Optic RC"},
    "306985400828": {"price":  6.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Ashton Jeanty Topps Signature Insert"},
    "306953389827": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes Icon Red Parallel (keep BIN — see auction note below)"},
    "306931278274": {"price":  9.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Deion Sanders 1994 Sportflics"},
    "306960410595": {"price":  7.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Tetairoa McMillan Prizm RC"},
    "306967133225": {"price":  7.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Terrance Ferguson Green Prizm RC"},
    "306931303163": {"price":  6.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Darryl Strawberry 4-card lot"},
    "306904078786": {"price":  6.99,  "best_offer": True,  "auto_accept":  5.00, "auto_decline":  3.50, "label": "Steve Atwater 7-card lot"},
    "306913790653": {"price":  6.99,  "best_offer": True,  "auto_accept":  5.00, "auto_decline":  3.50, "label": "Raghib/Quadry Ismail 11-card lot"},
    "306984769329": {"price":  6.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Brian Robinson Topps Chrome lightboard"},
    "306962001495": {"price":  6.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "J.K. Dobbins Optic One Hundred"},
    "306939345538": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Tyler Shough Chrome RC"},
    "306953888258": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Nick Bosa Score Top 100"},
    "306981279666": {"price": 14.99,  "best_offer": True,  "auto_accept": 10.00, "auto_decline":  7.00, "label": "Garrett Nussmeier Wild Card RC 1/2 (scarcity premium — panel raised from $5.99)"},
    # Mahomes Icon Collection parallels — keep at $5.99 (slight drop from $7.99)
    "306953125963": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes Icon MM-1"},
    "306953375292": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes Icon #22"},
    "306953377589": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes Icon #21"},
    "306953380753": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes IC2"},
    "306953382811": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes IC11"},
    "306953384024": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes IC1"},
    "306953391681": {"price":  5.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Mahomes IC11 (2nd)"},
    "306903941543": {"price":  5.99,  "best_offer": True,  "auto_accept":  4.50, "auto_decline":  3.00, "label": "Tim Brown 14-card lot"},
    "306913902750": {"price":  5.99,  "best_offer": True,  "auto_accept":  4.50, "auto_decline":  3.00, "label": "Howie Long 7-card lot"},
    "306984864600": {"price":  5.99,  "best_offer": True,  "auto_accept":  4.50, "auto_decline":  3.00, "label": "Paul Skenes Topps Heritage Logo Variation (Best Offer added — no comp data, do manual check)"},
    "306939316823": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Vita Vea Aqua Wave /199"},
    "306947440872": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Jayden Daniels Checkerboard Chrome"},
    "306953932686": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Alex Highsmith Stars /499"},
    "306967210472": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Bryce Underwood Bowman Chrome Pink"},
    "306913950248": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Willie McGinest 4-card lot (1 auto)"},
    "306930462076": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Bo Nix White Disco Prizm"},
    "306931236773": {"price":  2.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Rickey Henderson 1990 Bowman"},
    "306981451920": {"price":  2.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Marcelo Mayer 1990 Topps Baseball"},
    "306939367849": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Ladd McConkey Chrome Future Stars"},
    "306951619756": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Walter Nolan Pigskin Leather Chrome"},
    "306953923179": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Patrick Surtain II Stars /499"},
    "306903937710": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Jerome Bettis card lot"},
    "306904174454": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Boomer Esiason card lot"},
    "306968539428": {"price":  4.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Nate Landman Phoenician Penmanship AUTO"},
    "306984867488": {"price":  3.99,  "best_offer": False, "auto_accept": None,  "auto_decline": None,  "label": "Max Fried Topps Heritage Banner Variation"},
}

BULK_DROP_PRICE = 1.99   # everything ≤ $5 not in NAMED_DROPS


# ---------------------------------------------------------------------------
# eBay API helpers
# ---------------------------------------------------------------------------

def _cfg() -> dict:
    return json.loads((REPO / "configuration.json").read_text())


def _token(cfg: dict) -> str:
    from ebay_client import get_write_token
    return get_write_token(cfg)


def _headers(call_name: str, cfg: dict) -> dict:
    return {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            cfg["dev_id"],
        "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
        "Content-Type":                   "text/xml",
    }


def _ack(r: requests.Response) -> tuple[bool, list[str]]:
    root = ET.fromstring(r.text)
    ack = root.findtext(f"{{{EBAY_NS}}}Ack", "")
    errors = [
        err.findtext(f"{{{EBAY_NS}}}ShortMessage", "")
        for err in root.findall(f".//{{{EBAY_NS}}}Errors")
    ]
    return ack in ("Success", "Warning"), errors


def revise_price_and_bo(item_id: str, new_price: float,
                        best_offer: bool,
                        auto_accept: float | None,
                        auto_decline: float | None,
                        token: str, cfg: dict) -> tuple[bool, list[str]]:
    """ReviseItem: price + optional BestOfferDetails."""
    if best_offer:
        bo_block = "<BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>"
        if auto_accept is not None:
            bo_block += f"<ListingDetails><BestOfferAutoAcceptPrice currencyID=\"USD\">{auto_accept:.2f}</BestOfferAutoAcceptPrice></ListingDetails>"
        if auto_decline is not None:
            bo_block += f"<ListingDetails><MinimumBestOfferPrice currencyID=\"USD\">{auto_decline:.2f}</MinimumBestOfferPrice></ListingDetails>"
    else:
        # Explicitly disable Best Offer so any existing auto-decline floors are cleared.
        # Without this, listings already having BO with auto-decline >= new_price get rejected.
        bo_block = "<BestOfferDetails><BestOfferEnabled>false</BestOfferEnabled></BestOfferDetails>"

    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{EBAY_NS}">
  <RequesterCredentials><eBayAuthToken>{token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <StartPrice currencyID="USD">{new_price:.2f}</StartPrice>
    {bo_block}
  </Item>
</ReviseItemRequest>"""
    for attempt in range(3):
        try:
            r = requests.post(TRADING_URL,
                              headers=_headers("ReviseItem", cfg),
                              data=xml_body.encode(), timeout=45)
            return _ack(r)
        except requests.exceptions.ReadTimeout:
            if attempt == 2:
                return False, [f"ReadTimeout after 3 attempts"]
            time.sleep(5 * (attempt + 1))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Actually push to eBay (default: dry-run)")
    ap.add_argument("--dry-run", action="store_true", dest="dry_run",
                    help="Preview only, don't push (alias for default behavior)")
    ap.add_argument("--delay", type=float, default=0.4,
                    help="Seconds between API calls (default 0.4)")
    ap.add_argument("--start-from", type=int, default=1, dest="start_from",
                    help="Resume from this 1-based action index (skip earlier items)")
    args = ap.parse_args()
    dry = not args.apply

    # Load snapshot
    snap_path = REPO / "output" / "listings_snapshot.json"
    raw = json.loads(snap_path.read_text())
    listings = list(raw.get("listings", raw) if isinstance(raw, dict) else raw)

    cfg = _cfg()
    token = None
    if not dry:
        print("Getting eBay token...")
        token = _token(cfg)
        print("Token OK.\n")

    named_ids = set(NAMED_DROPS.keys())

    # Build full action list
    actions: list[dict] = []

    # Named drops
    for item_id, plan in NAMED_DROPS.items():
        match = next((l for l in listings if l["item_id"] == item_id), None)
        old_price = float(match["price"]) if match else 0.0
        actions.append({
            "item_id":     item_id,
            "old_price":   old_price,
            "new_price":   plan["price"],
            "best_offer":  plan["best_offer"],
            "auto_accept": plan["auto_accept"],
            "auto_decline":plan["auto_decline"],
            "label":       plan["label"],
            "tier":        "named",
        })

    # Bulk drop: everything ≤$5 not already in named list
    for l in listings:
        if l["item_id"] in named_ids:
            continue
        old = float(l.get("price") or 0)
        if old <= 0:
            continue
        if old <= 5.0:
            actions.append({
                "item_id":     l["item_id"],
                "old_price":   old,
                "new_price":   BULK_DROP_PRICE,
                "best_offer":  False,
                "auto_accept": None,
                "auto_decline":None,
                "label":       l["title"][:55],
                "tier":        "bulk",
            })

    # Print plan
    named_actions = [a for a in actions if a["tier"] == "named"]
    bulk_actions  = [a for a in actions if a["tier"] == "bulk"]

    print(f"{'DRY RUN — ' if dry else ''}Emergency reprice plan")
    print(f"  Named drops : {len(named_actions)} items")
    print(f"  Bulk $1.99  : {len(bulk_actions)} items")
    print(f"  Total       : {len(actions)} items\n")

    print("NAMED DROPS:")
    for a in named_actions:
        bo_str = f" + BestOffer (accept≥${a['auto_accept']:.2f})" if a["best_offer"] and a["auto_accept"] else (" + BestOffer" if a["best_offer"] else "")
        changed = "→" if a["new_price"] != a["old_price"] else "="
        print(f"  [{a['item_id']}] ${a['old_price']:.2f} {changed} ${a['new_price']:.2f}{bo_str}  {a['label'][:50]}")

    print(f"\nBULK: {len(bulk_actions)} singles/lots → $1.99")

    print(f"\n⚠️  MANUAL STEPS (cannot be automated via API):")
    print("  1. Travis Etienne AUTO [306985615478] → End listing → Relist as $0.99 auction (7-day)")
    print("  2. Mahomes Icon Red [306953389827] → End listing → Relist as $0.99 auction (7-day)")
    print("     eBay URL: https://www.ebay.com/itm/306985615478")
    print("     eBay URL: https://www.ebay.com/itm/306953389827")

    if dry:
        print("\n-- DRY RUN complete. Run with --apply to push to eBay. --")
        return 0

    print(f"\nApplying {len(actions)} price changes to eBay...")
    ok_count = 0
    fail_count = 0
    fail_log = []

    for i, a in enumerate(actions, 1):
        if i < args.start_from:
            print(f"  [{i:3d}/{len(actions)}] skipped (resume) — {a['label'][:42]}")
            continue

        if a["new_price"] == a["old_price"] and not a["best_offer"]:
            print(f"  [{i:3d}/{len(actions)}] skip (no change) — {a['label'][:45]}")
            ok_count += 1
            continue

        ok, errors = revise_price_and_bo(
            a["item_id"], a["new_price"],
            a["best_offer"], a["auto_accept"], a["auto_decline"],
            token, cfg,
        )
        if ok:
            bo_tag = " +BO" if a["best_offer"] else ""
            print(f"  [{i:3d}/{len(actions)}] OK  ${a['old_price']:.2f}→${a['new_price']:.2f}{bo_tag}  {a['label'][:42]}")
            ok_count += 1
        else:
            err_str = "; ".join(e for e in errors if e)[:80]
            print(f"  [{i:3d}/{len(actions)}] FAIL {a['item_id']}  {err_str}")
            fail_count += 1
            fail_log.append({"item_id": a["item_id"], "label": a["label"], "errors": errors})

        if i < len(actions):
            time.sleep(args.delay)

    print(f"\nDone: {ok_count} OK, {fail_count} failed")
    if fail_log:
        fail_path = REPO / "output" / "emergency_reprice_failures.json"
        fail_path.write_text(json.dumps(fail_log, indent=2))
        print(f"Failures saved to {fail_path}")

    # Refresh snapshot after price changes
    try:
        import snapshot_store
        for a in actions:
            listing = next((l for l in listings if l["item_id"] == a["item_id"]), None)
            if listing:
                listing["price"] = str(a["new_price"])
        snapshot_store.replace_all(listings)
        import sync_docs_json
        sync_docs_json.publish()
        print("Snapshot + docs/ refreshed.")
    except Exception as exc:
        print(f"Snapshot refresh skipped: {exc}")

    return 0 if fail_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
