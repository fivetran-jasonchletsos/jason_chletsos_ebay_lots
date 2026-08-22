"""
post_spoon.py -- one-off listing for the Easton PA Gorham sterling souvenir spoon.

Deliberately does NOT use post_from_scan's card defaults: this is category
63621 (Antiques > Silver > Sterling (.925) > Souvenir Spoons), multi-photo,
Best Offer enabled, and FREE USPS Ground Advantage shipping (postage ~$5.50
is built into the $49.99 price per the 10-agent panel plan, 2026-08-14).
A rigid metal spoon can never ship eBay Standard Envelope.

Usage: python3 post_spoon.py [--apply]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import requests
from PIL import Image

import ebay_client
import paths
from post_from_scan import upload_image, xml_escape

NS = ebay_client.NS
TRADING_URL = ebay_client.TRADING_URL

CATEGORY_ID = "63621"   # Antiques > Silver > Sterling Silver (.925) > Souvenir Spoons
PRICE = 49.99
BEST_OFFER_AUTO_ACCEPT = 42.00
BEST_OFFER_MINIMUM = 34.00   # auto-declines below this; panel floor $33.99

TITLE = "Sterling Silver Souvenir Spoon Easton PA Gorham George Taylor Declaration 1912"

PHOTO_DIR = Path("/Users/jason.chletsos/Downloads/Photos-1-001 (4)")
# Gallery photo first (full spoon), then bowl etch, hallmarks, handle detail.
PHOTO_ORDER = [
    "20260814_031106.jpg",  # full spoon
    "20260814_031049.jpg",  # bowl etch
    "20260814_031102.jpg",  # bowl etch angled
    "20260814_031051.jpg",  # bowl angle
    "20260814_031141.jpg",  # bowl closeup
    "20260814_031124.jpg",  # hallmarks
    "20260814_031123.jpg",  # hallmarks 2
    "20260814_031127.jpg",  # handle terminal
]

DESCRIPTION_HTML = """
<p><b>Antique Gorham Sterling Souvenir Spoon &mdash; Parsons-Taylor House, Easton PA &mdash;
George Taylor, Signer of the Declaration of Independence</b></p>

<p>The acid-etched bowl of this spoon shows the Parsons-Taylor House at 4th and Ferry
Streets in Easton, Pennsylvania &mdash; the oldest surviving house in Easton and one of the
few standing residences of a signer of the Declaration of Independence. Built 1753-1757
by William Parsons, the surveyor who laid out Easton in 1752 and is remembered as the
town's founder, the house was later home to George Taylor, Declaration signer, who died
there in 1781. The George Taylor Chapter of the DAR purchased the house in 1906 and it
remains their headquarters today. Easton itself hosted one of only three original public
readings of the Declaration on July 8, 1776.</p>

<p>A charming period quirk: the engraver etched "built 1753 by J. PARSONS, Founder of
EASTON" &mdash; the founder was actually William Parsons. The error is original to the spoon
and part of its story.</p>

<p><b>Details:</b></p>
<ul>
<li>Maker: Gorham Manufacturing Co. Reverse of handle stamped "PAT. 1912" with Gorham's
three shield trademarks (lion, anchor, G) and the word STERLING.</li>
<li>Sterling silver (.925), weighed at 15.14 grams on a digital scale.</li>
<li>Souvenir teaspoon size &mdash; measures just over 5 1/4 inches.</li>
<li>Bowl acid-etched with the building scene, "GEORGE TAYLOR BUILDING / built 1753 /
by J. PARSONS / Founder of EASTON" and "EASTON PA." along the edge.</li>
<li>Handle: double-line molded border with a scroll and shell flourish terminal &mdash; a
Gorham design patented in 1912; the spoon dates to the early-1900s souvenir era.</li>
<li>No monogram.</li>
</ul>

<p><b>Condition:</b> overall bright with crisp, well-defined etching. Scattered tarnish
spots and light haze inside the bowl, light utensil scratches, and darkening in the
crevices of the handle ornament consistent with age. No dents, no bends, no repairs.
Please review all photos, including close-ups of the hallmarks and bowl.</p>

<p>Ships boxed with padding &mdash; never in a plain envelope &mdash; so it arrives exactly
as pictured.</p>

<p>A genuine early-1900s piece of Lehigh Valley civic pride, well suited to collectors of
Easton and Northampton County history, Gorham souvenir spoons, or Revolutionary War and
Declaration signer memorabilia.</p>
"""

SPECIFICS = {
    "Brand/Maker": "Gorham",
    "Composition": "Sterling Silver (.925)",
    "Age": "1900-1940",
    "Type": "Souvenir Spoon",
    "Theme": "Historical",
    "Region of Origin": "United States",
}


def prep_photos() -> list[Path]:
    out_dir = Path("/tmp/spoon_imgs")
    out_dir.mkdir(exist_ok=True)
    prepped = []
    for name in PHOTO_ORDER:
        src = PHOTO_DIR / name
        if not src.exists():
            print(f"  MISSING photo: {src}")
            continue
        dst = out_dir / name
        if not dst.exists():
            im = Image.open(src)
            im.thumbnail((1600, 1600))
            im.save(dst, quality=88)
        prepped.append(dst)
    return prepped


def build_xml(picture_urls: list[str], token: str, include_condition: bool) -> str:
    pics = "".join(f"<PictureURL>{xml_escape(u)}</PictureURL>" for u in picture_urls)
    specifics_xml = "".join(
        f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
        for k, v in SPECIFICS.items()
    )
    condition_xml = "<ConditionID>3000</ConditionID>" if include_condition else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>{xml_escape(TITLE[:80])}</Title>
    <Description><![CDATA[{DESCRIPTION_HTML}]]></Description>
    <PrimaryCategory><CategoryID>{CATEGORY_ID}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{PRICE:.2f}</StartPrice>
    {condition_xml}
    <Country>US</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <Location>United States</Location>
    <PostalCode>19096</PostalCode>
    <BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>
    <ListingDetails>
      <BestOfferAutoAcceptPrice currencyID="USD">{BEST_OFFER_AUTO_ACCEPT:.2f}</BestOfferAutoAcceptPrice>
      <MinimumBestOfferPrice currencyID="USD">{BEST_OFFER_MINIMUM:.2f}</MinimumBestOfferPrice>
    </ListingDetails>
    <PictureDetails>{pics}</PictureDetails>
    <ItemSpecifics>{specifics_xml}</ItemSpecifics>
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>USPSFirstClass</ShippingService>
        <ShippingServiceCost currencyID="USD">0.00</ShippingServiceCost>
      </ShippingServiceOptions>
    </ShippingDetails>
    <ShipToLocations>US</ShipToLocations>
    <ReturnPolicy>
      <ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption>
    </ReturnPolicy>
  </Item>
</AddItemRequest>"""


def load_config_overrides() -> None:
    """--config path.json overrides the module-level listing globals, so one
    script posts any spoon/antique without editing source each time. Keys:
    title, price, best_offer_auto_accept, best_offer_minimum, photo_dir,
    photo_order, description_html, specifics."""
    if "--config" not in sys.argv:
        return
    g = globals()
    conf = json.loads(Path(sys.argv[sys.argv.index("--config") + 1]).read_text())
    mapping = {
        "title": "TITLE", "price": "PRICE",
        "best_offer_auto_accept": "BEST_OFFER_AUTO_ACCEPT",
        "best_offer_minimum": "BEST_OFFER_MINIMUM",
        "photo_order": "PHOTO_ORDER", "description_html": "DESCRIPTION_HTML",
        "specifics": "SPECIFICS", "category": "CATEGORY_ID",
    }
    for key, gname in mapping.items():
        if key in conf:
            g[gname] = conf[key]
    if "photo_dir" in conf:
        g["PHOTO_DIR"] = Path(conf["photo_dir"])


def main() -> int:
    apply = "--apply" in sys.argv
    load_config_overrides()
    cfg = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)

    photos = prep_photos()
    print(f"Prepared {len(photos)} photos")
    if len(photos) < 8:
        print("WARNING: expected 8 photos")

    urls = []
    for p in photos:
        url = upload_image(p, token, cfg)
        print(f"  uploaded {p.name} -> {url[:60]}...")
        urls.append(url)

    if not apply:
        print(f"[dry-run] title ({len(TITLE)} chars): {TITLE}")
        print(f"[dry-run] would post at ${PRICE:.2f} BIN, Best Offer "
              f"(auto-accept ${BEST_OFFER_AUTO_ACCEPT:.2f}, min ${BEST_OFFER_MINIMUM:.2f}), "
              f"free Ground Advantage, category {CATEGORY_ID}, {len(urls)} photos")
        return 0

    for include_condition in (True, False):
        xml = build_xml(urls, token, include_condition)
        headers = ebay_client.trading_headers("AddItem", cfg, token)
        resp = requests.post(TRADING_URL, headers=headers, data=xml.encode("utf-8"), timeout=60)
        body = resp.text
        ack = re.search(r"<Ack>(.*?)</Ack>", body)
        item = re.search(r"<ItemID>(.*?)</ItemID>", body)
        errors = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", body)
        ack = ack.group(1) if ack else "Unknown"
        if ack in ("Success", "Warning") and item:
            print(f"Ack: {ack}  ItemID: {item.group(1)}")
            print(f"Live: https://www.ebay.com/itm/{item.group(1)}")
            if errors:
                print(f"Warnings: {errors}")
            return 0
        print(f"FAILED ({ack}, condition={'on' if include_condition else 'off'}): {errors}")
        if not any("ondition" in e for e in errors):
            break  # not a condition problem; retrying without it won't help
    return 1


if __name__ == "__main__":
    sys.exit(main())
