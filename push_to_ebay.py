"""
push_to_ebay.py — push one CollX inventory row to eBay as a live FixedPriceItem.

eBay's APIs do not support creating drafts that appear in Seller Hub's Drafts
tab (verified 2026-05-25 against the Inventory + Trading API docs). The next
closest flow Jason approved: create a live listing with the CollX photo as the
sole image, then revise additional photos via the eBay UI on the live listing.

This script reads `output/inventory_plan.json` (built by `inventory_agent.py`),
finds the target row, builds AddFixedPriceItem XML (mirroring the working
mobile-app client in mobile/src/api/ebay.ts:445), and posts to the Trading API.

Default mode: dry-run — prints the plan and the XML it WOULD send. Pass
`--apply` AND type "yes" at the prompt to actually post.

Examples:
    python push_to_ebay.py --collx-id 1075074383399367680
    python push_to_ebay.py --player "Jared Goff" --price 2.49
    python push_to_ebay.py --row 1 --apply

The script is intentionally one-card-at-a-time. Batch pushing is a separate
script we can build once this round of single-card pushes is verified.
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from pathlib import Path

import requests

import linkage_db

REPO_ROOT  = Path(__file__).parent
PLAN_PATH  = REPO_ROOT / "output" / "inventory_plan.json"
CONFIG     = REPO_ROOT / "configuration.json"
PUSH_LOG   = REPO_ROOT / "output" / "push_to_ebay_log.json"

TRADING_URL  = "https://api.ebay.com/ws/api.dll"
OAUTH_URL    = "https://api.ebay.com/identity/v1/oauth2/token"
COMPAT_LEVEL = "967"
SITE_ID_US   = "0"
NS           = "urn:ebay:apis:eBLBaseComponents"

# Write scopes (broader than promote.py's read-only set). Mirrors the working
# mobile-app scope list at mobile/src/api/ebay.ts:28.
WRITE_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
])

# Condition IDs. The 2024+ trading-card-single categories (261328 etc.) accept
# only 4000 (Ungraded) for raw cards and 1000 for graded — the older numeric
# scale (2750/4000/5000/6000/7000) is rejected. We map all raw / play-condition
# labels coming from CollX or hand-entry to 4000 ("Ungraded") since CollX
# doesn't distinguish grade-eligible-but-raw beyond the single "RAW" flag.
CONDITION_ID = {
    "ungraded":   "4000",
    "near mint":  "4000",
    "excellent":  "4000",
    "good":       "4000",
    "light play": "4000",
    "heavy play": "4000",
    "poor":       "4000",
    "graded":     "1000",
}

# Trading-card-singles category (261328) requires a ConditionDescriptors block
# in addition to the top-level ConditionID 4000 (Ungraded). Descriptor 40001
# ("Card Condition") has SELECTION_ONLY values 400010-400013 sourced from the
# eBay Sell Metadata API (get_item_condition_policies).
CARD_CONDITION_DESCRIPTOR_VALUE = {
    "ungraded":   "400010",  # Near mint or better — default for raw cards
    "near mint":  "400010",
    "excellent":  "400011",
    "good":       "400011",  # eBay's scale has no "Good" — closest is Excellent
    "very good":  "400012",
    "light play": "400012",
    "heavy play": "400013",
    "poor":       "400013",
}


def xml_escape(s) -> str:
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def find_tag(xml: str, tag: str) -> str | None:
    m = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else None


def find_all(xml: str, tag: str) -> list[str]:
    return [m.group(1).strip()
            for m in re.finditer(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)]


def get_write_token(cfg: dict) -> str:
    """OAuth refresh-token grant with write scopes."""
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post(OAUTH_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"], "scope": WRITE_SCOPES},
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


def build_description(item: dict, condition: str) -> str:
    r = item["raw"]
    lines = [f"<h3>{xml_escape(item['title'])}</h3>"]
    meta = []
    if r.get("year"):    meta.append(f"Year: {xml_escape(r['year'])}")
    if r.get("set"):     meta.append(f"Set: {xml_escape(r['set'])}")
    if r.get("card_number"): meta.append(f"Card #: {xml_escape(r['card_number'])}")
    if r.get("parallel"):    meta.append(f"Parallel: {xml_escape(r['parallel'])}")
    if meta:
        lines.append("<p>" + " &middot; ".join(meta) + "</p>")
    lines.append(f"<p>Condition: {xml_escape(condition)}</p>")
    if r.get("notes"):
        lines.append(f"<p>{xml_escape(r['notes'])}</p>")
    lines.append("<p>Ships in a top-loader with team-bag protection. "
                 "Combined shipping available on multiple purchases.</p>")
    return ("\n".join(lines)).replace("]]>", "]]]]><![CDATA[>")


def build_item_specifics_xml(specifics: dict[str, str]) -> str:
    if not specifics:
        return ""
    blocks = []
    for k, v in specifics.items():
        blocks.append(
            f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
        )
    return "<ItemSpecifics>" + "".join(blocks) + "</ItemSpecifics>"


def build_add_xml(item: dict, token: str, price: float, condition: str, duration: str,
                  free_shipping: bool) -> str:
    """Build AddItem XML mirroring the live shape Jason's existing listings use
    (verified 2026-05-26 via GetItem on a live listing): Calculated shipping
    via US_eBayStandardEnvelope, US-only ShipToLocations, PostalCode 19096,
    3-day handling, ReturnsNotAccepted. The `free_shipping` arg is retained for
    API compat but does not change the shape — Calculated shipping is computed
    by eBay from package dims + buyer location, no flat price needed."""
    r = item["raw"]
    description = build_description(item, condition)
    condition_id = CONDITION_ID.get(condition.lower(), "1000")
    category_id = item.get("category_id") or "183454"
    photo = item.get("image_url") or r.get("image_url", "")
    if not photo:
        raise SystemExit("No image_url on this row. eBay requires at least one photo. Add to CollX first.")
    quantity = max(1, int(float(r.get("quantity") or 1)))

    # ConditionDescriptors are required for Trading Card Singles (261328) when
    # ConditionID = 4000 (Ungraded). For graded cards (1000) the descriptors
    # would be Professional Grader + Grade — not handled here yet.
    descriptors_xml = ""
    if condition_id == "4000" and str(category_id) == "261328":
        value_id = CARD_CONDITION_DESCRIPTOR_VALUE.get(condition.lower(), "400010")
        descriptors_xml = (
            "<ConditionDescriptors>"
            "<ConditionDescriptor>"
            f"<Name>40001</Name><Value>{value_id}</Value>"
            "</ConditionDescriptor>"
            "</ConditionDescriptors>"
        )

    return f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <SKU>{xml_escape(r.get('collx_id') or '')}</SKU>
    <Title>{xml_escape(item['title'][:80])}</Title>
    <Description><![CDATA[{description}]]></Description>
    <PrimaryCategory><CategoryID>{category_id}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price:.2f}</StartPrice>
    <ConditionID>{condition_id}</ConditionID>
    {descriptors_xml}
    <Country>US</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>{duration}</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>{quantity}</Quantity>
    <Location>United States</Location>
    <PostalCode>19096</PostalCode>
    <PictureDetails><PictureURL>{xml_escape(photo)}</PictureURL></PictureDetails>
    {build_item_specifics_xml(item.get("specifics", {}))}
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ApplyShippingDiscount>true</ApplyShippingDiscount>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>US_eBayStandardEnvelope</ShippingService>
        <ShippingServiceCost currencyID="USD">1.32</ShippingServiceCost>
      </ShippingServiceOptions>
    </ShippingDetails>
    <ShipToLocations>US</ShipToLocations>
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption>
    </ReturnPolicy>
  </Item>
</AddItemRequest>"""


def find_item(plan: dict, args) -> tuple[int, dict]:
    items = plan["items"]
    if args.row is not None:
        idx = args.row - 1
        if idx < 0 or idx >= len(items):
            raise SystemExit(f"--row {args.row} out of range (have {len(items)} items)")
        return idx, items[idx]
    if args.collx_id:
        for i, it in enumerate(items):
            if (it["raw"].get("collx_id") or "").strip() == args.collx_id.strip():
                return i, it
        raise SystemExit(f"No row with collx_id={args.collx_id}")
    if args.player:
        needle = args.player.lower()
        matches = [(i, it) for i, it in enumerate(items)
                   if needle in (it["raw"].get("player") or "").lower()]
        if not matches:
            raise SystemExit(f"No row matching player '{args.player}'")
        if len(matches) > 1:
            print(f"Multiple matches for '{args.player}':")
            for i, it in matches[:10]:
                print(f"  row {i+1}  collx_id={it['raw'].get('collx_id')}  {it['title']}")
            raise SystemExit("Disambiguate with --collx-id or --row.")
        return matches[0]
    raise SystemExit("Specify --collx-id, --row, or --player.")


def print_plan(idx: int, item: dict, price: float, condition: str, duration: str,
               free_shipping: bool) -> None:
    r = item["raw"]
    print()
    print("=" * 72)
    print(f"  PLAN  (row {idx+1})")
    print("=" * 72)
    print(f"  Title:      {item['title']}  ({len(item['title'])}/80 chars)")
    print(f"  Category:   {item.get('ebay_category','?')}  (eBay {item.get('category_id','?')})")
    print(f"  Condition:  {condition}  (ConditionID={CONDITION_ID.get(condition.lower(), '1000')})")
    print(f"  Price:      ${price:.2f}  (basis: {item['price_basis']})")
    print(f"  Quantity:   {r.get('quantity') or 1}")
    print(f"  Duration:   {duration}")
    print(f"  Shipping:   eBay Standard Envelope (Flat)  buyer pays $1.32")
    print(f"  Returns:    Not accepted  (matches your existing listings)")
    print(f"  Handling:   3 days  (DispatchTimeMax)")
    print(f"  Ships from: 19096")
    print(f"  Photo:      {item.get('image_url','(none)')}")
    print(f"  CollX ID:   {r.get('collx_id') or '(blank)'}")
    print()
    sources = []
    if item.get("collx_market"): sources.append(f"CollX ${item['collx_market']:.2f}")
    if item.get("scp_value"):    sources.append(f"SCP ${item['scp_value']:.2f}")
    if item.get("collx_asking"): sources.append(f"Asking ${item['collx_asking']:.2f}")
    print(f"  Price sources: {', '.join(sources) or 'none — using default'}")
    print()
    print(f"  Item Specifics ({len(item.get('specifics', {}))}):")
    for k, v in item.get("specifics", {}).items():
        print(f"    {k}: {v}")
    print("=" * 72)


def append_log(entry: dict) -> None:
    PUSH_LOG.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if PUSH_LOG.exists():
        try:
            log = json.loads(PUSH_LOG.read_text())
        except json.JSONDecodeError:
            log = []
    log.append(entry)
    PUSH_LOG.write_text(json.dumps(log, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--collx-id", help="Match by CollX ID from inventory_plan.json")
    g.add_argument("--row",      type=int, help="1-indexed row number from inventory_plan.json")
    g.add_argument("--player",   help="Substring match against player name")
    ap.add_argument("--price",      type=float, help="Override suggested price")
    ap.add_argument("--condition",  default=None, help="Override condition label (e.g. 'Near Mint')")
    ap.add_argument("--duration",   default="GTC",
                    choices=["GTC", "Days_7", "Days_10", "Days_30"],
                    help="ListingDuration. Default GTC (Good Til Cancelled).")
    ap.add_argument("--paid-shipping", action="store_true",
                    help="Charge $4.99 flat. Default is free shipping.")
    ap.add_argument("--apply",      action="store_true",
                    help="Actually push to eBay. Without this, dry-run only.")
    ap.add_argument("--show-xml",   action="store_true",
                    help="Print the full AddFixedPriceItem XML in dry-run mode.")
    args = ap.parse_args()

    if not PLAN_PATH.exists():
        print(f"No plan at {PLAN_PATH}. Run inventory_agent.py first.")
        return 2
    plan = json.loads(PLAN_PATH.read_text())

    idx, item = find_item(plan, args)
    price = args.price if args.price is not None else float(item["price"])
    if price <= 0:
        raise SystemExit("Price must be positive.")
    condition = (args.condition
                 or item["raw"].get("condition")
                 or "Near Mint")
    if condition.lower() not in CONDITION_ID:
        raise SystemExit(f"Unknown condition '{condition}'. Use one of: {', '.join(CONDITION_ID)}")
    free_shipping = not args.paid_shipping

    print_plan(idx, item, price, condition, args.duration, free_shipping)

    if not args.apply:
        print()
        print("DRY RUN — nothing sent to eBay.")
        print("Re-run with --apply to push live. You will be prompted for confirmation.")
        if args.show_xml:
            cfg = json.loads(CONFIG.read_text())
            placeholder_token = "<TOKEN_GOES_HERE_AT_APPLY_TIME>"
            print()
            print(build_add_xml(item, placeholder_token, price, condition, args.duration, free_shipping))
        return 0

    print()
    print("This will create a LIVE eBay listing immediately.")
    print("To proceed, type 'yes' (anything else cancels):")
    confirm = input("> ").strip().lower()
    if confirm != "yes":
        print("Cancelled.")
        return 1

    cfg = json.loads(CONFIG.read_text())
    print("Fetching write-scoped OAuth token…")
    token = get_write_token(cfg)
    print("Building XML…")
    body = build_add_xml(item, token, price, condition, args.duration, free_shipping)
    print(f"POST {TRADING_URL}  (AddItem)…")
    r = requests.post(TRADING_URL,
                      headers=trading_headers("AddItem", cfg, token),
                      data=body.encode("utf-8"),
                      timeout=60)
    response_xml = r.text
    ack = find_tag(response_xml, "Ack") or "?"
    item_id = find_tag(response_xml, "ItemID")
    errors = find_all(response_xml, "Errors")

    print()
    print(f"  Ack:     {ack}")
    print(f"  ItemID:  {item_id or '(none)'}")
    if errors:
        print(f"  Errors ({len(errors)}):")
        for e in errors:
            code = find_tag(e, "ErrorCode")
            short = find_tag(e, "ShortMessage")
            long_ = find_tag(e, "LongMessage")
            sev = find_tag(e, "SeverityCode")
            print(f"    [{sev}] {code}: {short}")
            if long_ and long_ != short:
                print(f"        {long_}")

    if item_id and ack in ("Success", "Warning"):
        url = f"https://www.ebay.com/itm/{item_id}"
        print()
        print(f"  Listing live at: {url}")
        print(f"  Add more photos: https://www.ebay.com/sl/list?mode=ReviseItem&itemId={item_id}")

        # Write linkage row BEFORE the log append so the durable CollX<->eBay
        # mapping survives even if the JSON log write fails. Failures here are
        # logged but non-fatal: the listing is already live on eBay.
        try:
            linkage_db.link_listing(
                collx_id=item["raw"].get("collx_id"),
                ebay_item_id=item_id,
                listed_price=price,
                title=item["title"],
                sku=item["raw"].get("collx_id"),
            )
            print(f"  Linkage:    collx_id={item['raw'].get('collx_id')} -> ItemID {item_id}")
        except Exception as exc:
            print(f"  Linkage WRITE FAILED (non-fatal): {exc}")

        # Append to listings_snapshot.json so dashboards built from the cached
        # snapshot pick up the new listing immediately, without waiting for the
        # next full promote.py refresh. Prevents the "I just listed it but the
        # CollX vs eBay page shows it as unlisted" stale-data problem.
        try:
            import json
            from pathlib import Path
            snap_path = Path(__file__).parent / "output" / "listings_snapshot.json"
            if snap_path.is_file():
                snap = json.loads(snap_path.read_text())
                listings = snap["listings"] if isinstance(snap, dict) else snap
                if not any(str(l.get("item_id")) == str(item_id) for l in listings):
                    listings.append({
                        "item_id":      str(item_id),
                        "title":        item["title"],
                        "price":        float(price),
                        "pic":          item.get("image_url") or item["raw"].get("image_url", ""),
                        "url":          url,
                        "category":     "Trading Card Singles",
                        "condition":    condition,
                        "quantity":     1,
                        "desc":         "",
                        "listing_type": "BIN",
                    })
                    if isinstance(snap, dict):
                        snap["listings"] = listings
                        snap_path.write_text(json.dumps(snap, separators=(",", ":")))
                    else:
                        snap_path.write_text(json.dumps(listings, separators=(",", ":")))
                    print(f"  Snapshot:   appended to listings_snapshot.json ({len(listings)} listings)")
        except Exception as exc:
            print(f"  Snapshot append FAILED (non-fatal): {exc}")

    append_log({
        "row":         idx + 1,
        "collx_id":    item["raw"].get("collx_id"),
        "title":       item["title"],
        "price":       price,
        "condition":   condition,
        "duration":    args.duration,
        "ack":         ack,
        "item_id":     item_id,
        "errors":      [{"code": find_tag(e, "ErrorCode"),
                         "message": find_tag(e, "LongMessage") or find_tag(e, "ShortMessage")}
                        for e in errors],
    })
    return 0 if ack in ("Success", "Warning") else 1


if __name__ == "__main__":
    sys.exit(main())
