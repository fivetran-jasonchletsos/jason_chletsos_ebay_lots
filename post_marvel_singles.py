"""Post non-sport (Marvel) trading card singles. Category 261324 (Non-Sport
Trading Cards) instead of post_from_scan.py's sports category -- Topps Chrome
Marvel / Marvel Beginnings / vintage 1993 Marvel Battles Masterpieces reprints
don't fit the football/basketball specifics inference in that module.

Dry-run default; --apply posts to eBay."""
import argparse, json, requests
from pathlib import Path
import post_from_scan as pfs, ebay_client

CATEGORY_ID = "183050"  # Non-Sport Trading Card Singles (261324 is a parent/non-leaf category, rejected by AddItem)


def build_and_post(crop, title, price, specs, cfg, tok, apply):
    print(f"\n  Card: {title[:60]}")
    print(f"  Image: {crop.name}  Price: ${price:.2f}")
    if not apply:
        print("  [dry-run] would post listing")
        return {"dry_run": True, "title": title, "price": price}
    picture_url = pfs.upload_image(crop, tok, cfg)
    print(f"  Picture URL: {picture_url}")
    desc = pfs.build_description(title)
    specs_xml = "".join(
        f"<NameValueList><Name>{pfs.xml_escape(k)}</Name><Value>{pfs.xml_escape(v)}</Value></NameValueList>"
        for k, v in specs.items())
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<AddItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
           f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
           f'<Item><Title>{pfs.xml_escape(title)}</Title>'
           f'<Description><![CDATA[{desc}]]></Description>'
           f'<PrimaryCategory><CategoryID>{CATEGORY_ID}</CategoryID></PrimaryCategory>'
           f'<StartPrice>{price}</StartPrice><ConditionID>4000</ConditionID>'
           f'<ConditionDescriptors><ConditionDescriptor><Name>40001</Name><Value>400010</Value></ConditionDescriptor></ConditionDescriptors>'
           f'<Country>US</Country><Currency>USD</Currency><DispatchTimeMax>3</DispatchTimeMax>'
           f'<ListingDuration>GTC</ListingDuration><ListingType>FixedPriceItem</ListingType>'
           f'<Location>Wynnewood, PA</Location><PostalCode>19096</PostalCode>'
           f'<PictureDetails><PictureURL>{pfs.xml_escape(picture_url)}</PictureURL></PictureDetails>'
           f'<Quantity>1</Quantity><ItemSpecifics>{specs_xml}</ItemSpecifics>'
           f'<ShippingDetails><ShippingType>Flat</ShippingType><ShippingServiceOptions>'
           f'<ShippingServicePriority>1</ShippingServicePriority><ShippingService>USPSFirstClass</ShippingService>'
           f'<ShippingServiceCost>0.99</ShippingServiceCost></ShippingServiceOptions></ShippingDetails>'
           f'<ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>'
           f'</Item></AddItemRequest>')
    h = ebay_client.trading_headers("AddItem", cfg, tok)
    r = requests.post(pfs.TRADING_URL, headers=h, data=xml.encode(), timeout=60)
    ack = ebay_client.find_tag(r.text, "Ack")
    item_id = ebay_client.find_tag(r.text, "ItemID")
    err = ebay_client.find_tag(r.text, "LongMessage")
    if ack in ("Success", "Warning") and item_id:
        print(f"  Ack: {ack}  ItemID: {item_id}")
    else:
        print(f"  FAILED ({ack}): {err}")
    return {"ack": ack, "item_id": item_id, "title": title, "price": price, "err": err}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--batch", required=True, help="JSON file: list of {crop,title,price,set,character,insert}")
    a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    tok = ebay_client.get_write_token(cfg)
    batch = json.loads(Path(a.batch).read_text())

    results = []
    for c in batch:
        assert len(c["title"]) <= 80, (len(c["title"]), c["title"])
        specs = {"Character": c.get("character", ""), "Manufacturer": c.get("manufacturer", "Topps"),
                  "Set": c.get("set", ""), "Year": c.get("year", "2024"), "Franchise": "Marvel"}
        if c.get("insert"):
            specs["Insert Set"] = c["insert"]
        if c.get("parallel"):
            specs["Parallel/Variety"] = c["parallel"]
        if c.get("serial"):
            specs["Features"] = "Serial Numbered"
            specs["Print Run"] = c["serial"]
        specs = {k: v for k, v in specs.items() if v}
        r = build_and_post(Path(c["crop"]), c["title"], c["price"], specs, cfg, tok, a.apply)
        r["crop"] = c["crop"]
        results.append(r)

    Path("output/_marvel_singles_result.json").write_text(json.dumps(results, indent=1, default=str))
    ok = [r for r in results if r.get("item_id")]
    print(f"\n=== {'APPLIED' if a.apply else 'DRY-RUN'}: {len(batch)} | posted {len(ok)} "
          f"| total ${sum(float(r['price']) for r in ok):.2f} ===")


if __name__ == "__main__":
    main()
