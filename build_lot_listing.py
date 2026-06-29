"""build_lot_listing.py — consolidate N single-card listings into ONE lot.

For a given player lot: builds a collage from the cards' existing listing photos,
uploads it to eBay EPS, REVISES one surviving listing into the lot (new title,
price, description, collage photo), and ENDS the other listings.

Only touches Title / StartPrice / Description / PictureDetails on the revise, so
it sidesteps the business-policy (legacy shipping/return) error path.

Dry-run by default. Pass --apply to actually mutate eBay.

Usage:
  python3 build_lot_listing.py --lot allen           # dry-run
  python3 build_lot_listing.py --lot allen --apply
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

import requests
from PIL import Image

import ebay_client
from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
from post_from_scan import upload_image

THUMBS = Path("output/_lot_thumbs")
DO_NOT_RELIST = Path("output/do_not_relist.json")


def _record_no_relist(item_id):
    """Add an item id to output/do_not_relist.json so relist_agent never
    resurrects a lot or a lot-component single as a duplicate."""
    try:
        cur = set(json.loads(DO_NOT_RELIST.read_text())) if DO_NOT_RELIST.exists() else set()
    except Exception:
        cur = set()
    cur.add(str(item_id))
    DO_NOT_RELIST.write_text(json.dumps(sorted(cur), indent=2))

# ---- lot definitions: survivor is revised, the rest are ended ----
LOTS = {
    "allen": {
        "title": "Josh Allen 5 Card Lot Buffalo Bills Select Mosaic Inserts Football",
        "price": 12.99,
        "player": "Josh Allen",
        "team": "Buffalo Bills",
        "survivor": "307021784343",
        "cards": [
            ("307021784343", "2024 Panini Select Red/Yellow Prizm Shock #12"),
            ("306993554472", "2024 Panini Select Die-Cut #34"),
            ("306993495460", "2024 Panini Select Numbers Insert #17"),
            ("306993495546", "Panini Select Turbocharged Insert"),
            ("306993495361", "Panini Mosaic Base #17"),
        ],
    },
    "mahomes": {
        "title": "Patrick Mahomes 5 Card Lot Kansas City Chiefs Prizm Select Football",
        "price": 16.99,
        "player": "Patrick Mahomes",
        "team": "Kansas City Chiefs",
        "cards": [
            ("307029578211", "2025 Panini Prizm Prizm Break"),
            ("307021770408", "2025 Panini Select Numbers Game Insert #15"),
            ("307021765688", "2024 Phoenix Thunderbirds"),
            ("307021785258", "2025 Panini Mosaic Base"),
            ("306992916873", "2023 Panini Contenders #51"),
        ],
    },
    "jeanty": {
        "title": "Ashton Jeanty 5 Card Rookie Lot Raiders RC Select Donruss Mosaic Football",
        "price": 12.99,
        "player": "Ashton Jeanty",
        "team": "Las Vegas Raiders",
        "cards": [
            ("306993605582", "2025 Panini Select Turbocharged RC"),
            ("306993602623", "2025 Panini Select RC base"),
            ("306998478666", "2025 Panini Donruss Rated Rookie #305"),
            ("307021794277", "2025 Donruss Optic Hidden Potential #5 RC"),
            ("307021799481", "2025 Panini Mosaic Rookies Silver Prizm RC"),
        ],
    },
    "camward": {
        "title": "Cam Ward 5 Card Rookie Lot Tennessee Titans RC Prizm Select Football",
        "price": 18.99,
        "player": "Cam Ward",
        "team": "Tennessee Titans",
        "cards": [
            ("307029578174", "2025 Panini Prizm Fireworks RC"),
            ("307029578293", "2025 Panini Prizm Fractal Green RC"),
            ("307029578357", "2025 Panini Prizm Emergent Green RC"),
            ("307021759801", "2025 Panini Select Numbers Game Insert #1 RC"),
            ("307021780639", "2025 Panini Select Certified RC"),
        ],
    },
}


# ---- auto-lot: pick a player's 5 cheapest singles from the live snapshot ----
CHASE_KEEP_SOLO = 6.00  # cards priced above this stay listed solo

AUTO_LOTS = {
    "lamar":   {"player_canon": "Lamar Jackson",   "player": "Lamar Jackson",
                "team": "Baltimore Ravens", "price": 12.99,
                "title": "Lamar Jackson 5 Card Lot Baltimore Ravens Prizm Select Football"},
    "daniels": {"player_canon": "Jayden Daniels",  "player": "Jayden Daniels",
                "team": "Washington Commanders", "price": 12.99,
                "title": "Jayden Daniels 5 Card Rookie Lot Washington Commanders RC Football"},
    "stroud":  {"player_canon": "CJ Stroud",       "player": "C.J. Stroud",
                "team": "Houston Texans", "price": 13.99,
                "title": "C.J. Stroud 5 Card Lot Houston Texans Prizm Select Football"},
    "burrow":  {"player_canon": "Joe Burrow",      "player": "Joe Burrow",
                "team": "Cincinnati Bengals", "price": 11.99,
                "title": "Joe Burrow 5 Card Lot Cincinnati Bengals Prizm Select Football"},
    "caleb":   {"player_canon": "Caleb Williams",  "player": "Caleb Williams",
                "team": "Chicago Bears", "price": 12.99,
                "title": "Caleb Williams 5 Card Rookie Lot Chicago Bears RC Football"},
}


def auto_select(player_canon, n=5):
    """Return the n cheapest non-lot, non-chase singles for a player from the snapshot."""
    import browse_index_agent as B
    d = json.loads(Path("output/listings_snapshot.json").read_text())
    L = d.get("listings", d) if isinstance(d, dict) else d
    cands = []
    for x in L:
        t = x.get("title", "")
        if "lot" in t.lower():
            continue
        if player_canon not in B.extract_players(t):
            continue
        pr = float(x.get("price", 0) or 0)
        if pr > CHASE_KEEP_SOLO:
            continue
        cands.append((str(x.get("item_id")), t, x.get("pic"), pr))
    cands.sort(key=lambda c: c[3])
    return cands[:n]


def fetch_thumb_for(item_id, url):
    dest = THUMBS / f"{item_id}.jpg"
    if dest.exists() and dest.stat().st_size > 0:
        return dest
    if not url:
        return None
    try:
        r = requests.get(url, timeout=20)
        if r.ok and r.content:
            dest.write_bytes(r.content)
            return dest
    except Exception:
        return None
    return None


def build_auto_lot(key):
    cfg = AUTO_LOTS[key]
    sel = auto_select(cfg["player_canon"], 5)
    cards = [(iid, title) for iid, title, pic, pr in sel]
    for iid, title, pic, pr in sel:
        fetch_thumb_for(iid, pic)
    return {
        "title": cfg["title"], "price": cfg["price"],
        "player": cfg["player"], "team": cfg["team"],
        "cards": cards,
    }, sel


def build_collage(card_ids, out_path):
    imgs = [Image.open(THUMBS / f"{cid}.jpg").convert("RGB") for cid in card_ids]
    cell_h = 460
    cells = []
    for im in imgs:
        w = int(im.width * cell_h / im.height)
        cells.append(im.resize((w, cell_h)))
    pad, cols = 18, 3
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    cell_w = max(c.width for c in cells)
    canvas_w = pad + cols * (cell_w + pad)
    canvas_h = pad + len(rows) * (cell_h + pad)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    for r, row in enumerate(rows):
        row_w = len(row) * (cell_w + pad) - pad
        x0 = (canvas_w - row_w) // 2
        y = pad + r * (cell_h + pad)
        for im in row:
            x = x0 + (cell_w - im.width) // 2
            canvas.paste(im, (x, y))
            x0 += cell_w + pad
    canvas.save(out_path, "JPEG", quality=90)
    return out_path


def build_description(lot):
    items = "".join(f"<li>{xml_escape(name)}</li>" for _, name in lot["cards"])
    return (
        f"<h3>{xml_escape(lot['player'])} {len(lot['cards'])}-Card Lot — {xml_escape(lot['team'])}</h3>"
        "<p>You receive <b>all the cards pictured</b> in one shipment:</p>"
        f"<ul>{items}</ul>"
        "<ul>"
        "<li>Raw / ungraded, pack-fresh condition.</li>"
        "<li>Cards shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
        "<li>Great way to add multiple cards of your player in one buy.</li>"
        "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
        "</ul>"
        "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>"
    )


def revise_to_lot(lot, picture_url, token, cfg, apply):
    desc = build_description(lot)
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseFixedPriceItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{lot['survivor']}</ItemID>
    <Title>{xml_escape(lot['title'][:80])}</Title>
    <StartPrice currencyID="USD">{lot['price']:.2f}</StartPrice>
    <Description><![CDATA[{desc}]]></Description>
    <PictureDetails><PictureURL>{xml_escape(picture_url)}</PictureURL></PictureDetails>
  </Item>
</ReviseFixedPriceItemRequest>"""
    if not apply:
        print(f"  [dry-run] would REVISE {lot['survivor']} -> '{lot['title']}' @ ${lot['price']:.2f}")
        return True
    h = trading_headers("ReviseFixedPriceItem", cfg, token)
    r = requests.post(TRADING_URL, headers=h, data=xml.encode("utf-8"), timeout=30)
    ack = find_tag(r.text, "Ack")
    if ack in ("Success", "Warning"):
        print(f"  REVISED {lot['survivor']} ({ack}) -> lot live: https://www.ebay.com/itm/{lot['survivor']}")
        return True
    print(f"  REVISE FAILED ({ack}): {r.text[:400]}")
    return False


def add_lot(lot, picture_url, token, cfg, apply):
    """Create the lot as a FRESH FixedPriceItem (AddItem) — the proven path that
    Trading ReviseItem can't do on Inventory-API listings. Returns new item id."""
    desc = build_description(lot)
    specifics = {"Sport": "Football", "Player/Athlete": lot["player"],
                 "Team": lot["team"], "Type": "Sports Trading Card Lot",
                 "Features": "Lot"}
    specifics_xml = "".join(
        f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
        for k, v in specifics.items())
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>{xml_escape(lot['title'][:80])}</Title>
    <Description><![CDATA[{desc}]]></Description>
    <PrimaryCategory><CategoryID>261329</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{lot['price']:.2f}</StartPrice>
    <ConditionID>3000</ConditionID>
    <Country>US</Country><Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <Location>United States</Location><PostalCode>19096</PostalCode>
    <PictureDetails><PictureURL>{xml_escape(picture_url)}</PictureURL></PictureDetails>
    <ItemSpecifics>{specifics_xml}</ItemSpecifics>
    <ShippingDetails>
      <ShippingType>Flat</ShippingType><ApplyShippingDiscount>true</ApplyShippingDiscount>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>US_eBayStandardEnvelope</ShippingService>
        <ShippingServiceCost currencyID="USD">1.32</ShippingServiceCost>
      </ShippingServiceOptions>
    </ShippingDetails>
    <ShipToLocations>US</ShipToLocations>
    <ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>
  </Item>
</AddItemRequest>"""
    if not apply:
        print(f"  [dry-run] would ADD lot '{lot['title']}' @ ${lot['price']:.2f}")
        return None
    h = trading_headers("AddItem", cfg, token)
    r = requests.post(TRADING_URL, headers=h, data=xml.encode("utf-8"), timeout=30)
    ack = find_tag(r.text, "Ack")
    new_id = find_tag(r.text, "ItemID")
    if ack in ("Success", "Warning") and new_id:
        print(f"  ADDED lot ({ack}) -> https://www.ebay.com/itm/{new_id}")
        _record_no_relist(new_id)
        return new_id
    print(f"  ADD FAILED ({ack}): {r.text[:400]}")
    return None


def end_item(item_id, token, cfg, apply):
    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <ItemID>{xml_escape(item_id)}</ItemID>
  <EndingReason>OtherListingError</EndingReason>
</EndFixedPriceItemRequest>"""
    if not apply:
        print(f"  [dry-run] would END {item_id}")
        return True
    h = trading_headers("EndFixedPriceItem", cfg, token)
    r = requests.post(TRADING_URL, headers=h, data=xml.encode("utf-8"), timeout=30)
    ack = find_tag(r.text, "Ack")
    ok = ack in ("Success", "Warning")
    if ok:
        _record_no_relist(item_id)
    print(f"  {'ENDED' if ok else 'END FAILED'} {item_id} ({ack})"
          + ("" if ok else f": {r.text[:200]}"))
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lot", choices=list(LOTS))
    ap.add_argument("--auto", choices=list(AUTO_LOTS),
                    help="Auto-build a lot from a player's 5 cheapest live singles")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if not args.lot and not args.auto:
        ap.error("provide --lot or --auto")
    if args.auto:
        lot, sel = build_auto_lot(args.auto)
        print(f"Auto-selected {len(sel)} cheapest singles for {lot['player']}:")
        for iid, title, pic, pr in sel:
            print(f"  ${pr:5.2f}  {iid}  {title[:60]}")
    else:
        lot = LOTS[args.lot]

    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)

    key = args.lot or args.auto
    collage = build_collage([cid for cid, _ in lot["cards"]],
                            Path(f"output/_lot_{key}_collage.jpg"))
    print(f"Collage: {collage}")

    if args.apply:
        print("Uploading collage to eBay EPS...")
        picture_url = upload_image(collage, token, cfg)
        print(f"  Picture URL: {picture_url}")
    else:
        picture_url = "https://example.com/dry-run-collage.jpg"

    print(f"\n=== {lot['player']} lot ({'APPLY' if args.apply else 'DRY-RUN'}) ===")
    # Create the lot FIRST (AddItem in the Lots category), THEN end the singles —
    # so the cards are never un-listed if the lot creation fails.
    new_id = add_lot(lot, picture_url, token, cfg, args.apply)
    if args.apply and not new_id:
        print("Lot creation FAILED — leaving all singles live, nothing ended.")
        return
    print(f"Ending {len(lot['cards'])} singles folded into the lot:")
    for cid, _ in lot["cards"]:
        end_item(cid, token, cfg, args.apply)


if __name__ == "__main__":
    sys.exit(main())
