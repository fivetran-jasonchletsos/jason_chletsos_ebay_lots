"""
post_from_scan.py — post a card directly from a local scan image to eBay.

Uploads the image to eBay's EPS (UploadSiteHostedPictures), then creates
a live FixedPriceItem listing. No CollX required.

Usage:
    python3 post_from_scan.py --image path/to/card.jpg \
                               --title "2025 Topps Signature Class Travis Hunter RC" \
                               --price 5.99 \
                               --apply

    python3 post_from_scan.py --batch cards.json --apply

Batch JSON format:
    [
      {"image": "output/split_cards/Scan 4/topps_sig_09.jpg",
       "title": "2025 Topps Signature Class Travis Hunter Jaguars RC Football",
       "price": 5.99},
      ...
    ]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

import requests

import ebay_client
import paths

NS           = ebay_client.NS
TRADING_URL  = ebay_client.TRADING_URL
CATEGORY_ID  = "261328"    # Trading Card Singles
CONDITION_ID = "4000"      # Ungraded
SPORT        = "Football"  # overridable via --sport (e.g. Basketball)


def xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;")
             .replace(">", "&gt;").replace('"', "&quot;"))


def upload_image(image_path: Path, token: str, cfg: dict) -> str:
    """Upload a local image to eBay EPS. Returns the hosted picture URL."""
    headers = ebay_client.trading_headers("UploadSiteHostedPictures", cfg, token)
    xml_part = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<UploadSiteHostedPicturesRequest xmlns="{NS}">'
        f'<RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>'
        '<PictureSet>Supersize</PictureSet>'
        '</UploadSiteHostedPicturesRequest>'
    )
    with open(image_path, "rb") as f:
        image_data = f.read()

    response = requests.post(
        TRADING_URL,
        headers=headers,
        data={
            "XML Payload": (None, xml_part, "text/xml"),
        },
        files={
            "image": (image_path.name, image_data, "image/jpeg"),
        },
        timeout=30,
    )
    body = response.text

    # Fallback: try multipart form approach
    if "FullURL" not in body:
        boundary = "----EbayBoundary"
        multipart = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="XML Payload"\r\n'
            f"Content-Type: text/xml;charset=UTF-8\r\n\r\n"
            f"{xml_part}\r\n"
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'
            f"Content-Type: image/jpeg\r\n\r\n"
        ).encode() + image_data + f"\r\n--{boundary}--\r\n".encode()

        upload_headers = dict(headers)
        upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        upload_headers.pop("Content-Type", None)
        upload_headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"

        response = requests.post(
            TRADING_URL,
            headers=upload_headers,
            data=multipart,
            timeout=30,
        )
        body = response.text

    m = re.search(r"<FullURL>(.*?)</FullURL>", body)
    if not m:
        raise RuntimeError(f"Image upload failed:\n{body[:500]}")
    return m.group(1).strip()


def build_description(title: str) -> str:
    return (
        "<ul>"
        f"<li><b>{xml_escape(title)}</b></li>"
        "<li>Raw / ungraded — pack-fresh condition unless noted.</li>"
        "<li>Card pictured is the card you receive.</li>"
        "<li>Ships in penny sleeve + top loader via eBay Standard Envelope.</li>"
        "<li>VOLUME DISCOUNT: Buy 2 save 5%, buy 5 save 12%, buy 10 save 20% — "
        "combine with any cards in our store.</li>"
        "<li>Pack-fresh and grading-ready — pulled, sleeved, never played.</li>"
        "</ul>"
        "<p>Independent collector since 1998. Real cards, real photos, "
        "fast shipping. Check feedback.</p>"
    )


# Brand token -> manufacturer, most specific first. Order matters: "signature
# class" must match before "topps", "prizm draft picks" before "prizm", etc.
BRAND_TOKENS: list[tuple[str, str]] = [
    ("signature class",   "Topps"),
    ("topps chrome",      "Topps"),
    ("bowman",            "Topps"),
    ("stadium club",      "Topps"),
    ("finest",            "Topps"),
    ("topps",             "Topps"),
    ("prizm draft picks", "Panini"),
    ("prizm",             "Panini"),
    ("optic",             "Panini"),
    ("mosaic",            "Panini"),
    ("select",            "Panini"),
    ("donruss",           "Panini"),
    ("contenders",        "Panini"),
    ("absolute",          "Panini"),
    ("phoenix",           "Panini"),
    ("score",             "Panini"),
    ("chronicles",        "Panini"),
    ("rookies & stars",   "Panini"),
    ("rookies and stars", "Panini"),
    ("rookies",           "Panini"),
    ("revolution",        "Panini"),
    ("prestige",          "Panini"),
    ("illusions",         "Panini"),
    ("certified",         "Panini"),
    ("playbook",          "Panini"),
    ("spectra",           "Panini"),
    ("obsidian",          "Panini"),
    ("origins",           "Panini"),
    ("zenith",            "Panini"),
    ("classics",          "Panini"),
    ("legacy",            "Panini"),
    ("playoff",           "Panini"),
    ("immaculate",        "Panini"),
    ("flawless",          "Panini"),
    ("national treasures","Panini"),
    ("gold standard",     "Panini"),
    ("unparalleled",      "Panini"),
    ("luminance",         "Panini"),
    ("panini",            "Panini"),
    ("sage",              "SAGE"),
    ("leaf",              "Leaf"),
    ("upper deck",        "Upper Deck"),
    ("bo jackson battle arena", "Koei Tecmo"),
    ("tecmo bowl",        "Koei Tecmo"),
]

# Matches "092/225" and bare "/225" (e.g. "Teal /225") but not dates like 2024-25.
SERIAL_RE = re.compile(r"(?:\b\d{1,3}\s*)?/\s*(\d{2,4})\b")


def infer_specifics(title: str) -> dict[str, str] | None:
    """Derive ItemSpecifics from the listing title. None if brand unknown."""
    t = title.lower()
    # The product brand appears earliest in the title; parallel names like
    # "Gold Green Prizm" on a Select card come later. Pick the brand token
    # with the lowest title index, tie-broken by token length (most specific).
    hits = [(t.index(tok), -len(tok), tok, brand)
            for tok, brand in BRAND_TOKENS if tok in t]
    if not hits:
        return None
    # Bare manufacturer words ("panini", "topps", "sage") only win when no
    # actual set name is present — "2025 Panini Select" must resolve to Select.
    GENERIC = {"panini", "topps", "sage"}
    specific = [h for h in hits if h[2] not in GENERIC]
    hits = specific or hits
    hits.sort()
    _, _, set_token, mfg = hits[0]

    specifics = {"Sport": SPORT, "Card Manufacturer": mfg}
    year_m = re.search(r"\b(20[0-2]\d)(?:-\d{2})?\b", title)
    season = year_m.group(1) if year_m else None
    if season:
        specifics["Season"] = season
    set_name = " ".join(w.capitalize() for w in set_token.split())
    parts = ([season] if season else []) + [mfg] + set_name.split()
    deduped = [p for i, p in enumerate(parts)
               if i == 0 or p.lower() != parts[i - 1].lower()]
    specifics["Set"] = " ".join(deduped)

    serial = SERIAL_RE.search(title)
    if serial:
        specifics["Features"] = "Serial Numbered"
        specifics["Print Run"] = serial.group(1)
    if re.search(r"\bRC\b|\brookie\b", title, re.IGNORECASE):
        specifics["Features"] = (specifics.get("Features", "") + ", Rookie").strip(", ")
    if re.search(r"\bauto(graph)?\b|\bon-card\b", title, re.IGNORECASE):
        specifics["Features"] = (specifics.get("Features", "") + ", Autograph").strip(", ")
    return specifics


def build_xml(title: str, price: float, picture_url: str, token: str,
              category: str = CATEGORY_ID, condition: str = CONDITION_ID) -> str:
    description = build_description(title)
    # The "Ungraded" ConditionDescriptor sub-value only applies to the
    # Trading Card Singles schema -- other categories (e.g. Trading Card
    # Lots) reject it outright.
    descriptors_xml = (
        "<ConditionDescriptors>"
        "<ConditionDescriptor>"
        "<Name>40001</Name><Value>400010</Value>"
        "</ConditionDescriptor>"
        "</ConditionDescriptors>"
    ) if category == CATEGORY_ID else ""
    specifics = infer_specifics(title)
    if specifics is None:
        raise ValueError(
            f"Cannot determine card manufacturer from title: {title!r}. "
            "Include the brand (Prizm/Select/Topps/etc.) in the title."
        )
    specifics_xml = "".join(
        f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
        for k, v in specifics.items()
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>{xml_escape(title[:80])}</Title>
    <Description><![CDATA[{description}]]></Description>
    <PrimaryCategory><CategoryID>{category}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price:.2f}</StartPrice>
    <ConditionID>{condition}</ConditionID>
    {descriptors_xml}
    <Country>US</Country>
    <Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <Location>United States</Location>
    <PostalCode>19096</PostalCode>
    <PictureDetails><PictureURL>{xml_escape(picture_url)}</PictureURL></PictureDetails>
    <ItemSpecifics>{specifics_xml}</ItemSpecifics>
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


def _norm_title(t: str) -> str:
    return " ".join(t.lower().split())


def _find_live_duplicate(title: str) -> dict | None:
    """Check the listings snapshot for a live listing with the same title."""
    snap_path = Path("output/listings_snapshot.json")
    if not snap_path.exists():
        return None
    try:
        data = json.loads(snap_path.read_text())
    except json.JSONDecodeError:
        return None
    listings = data.get("listings", data) if isinstance(data, dict) else data
    want = _norm_title(title)
    for l in listings:
        if _norm_title(l.get("title", "")) == want:
            return l
    return None


def post_card(image_path: Path, title: str, price: float,
              cfg: dict, token: str, apply: bool, category: str = CATEGORY_ID,
              condition: str = CONDITION_ID) -> dict:
    print(f"\n  Card: {title[:60]}")
    print(f"  Image: {image_path.name}  Price: ${price:.2f}")

    serial = SERIAL_RE.search(title)
    if serial and price < 10:
        print(f"  NOTE: title shows serial /{serial.group(1)} but price is under $10 — "
              "confirm this numbered card isn't underpriced.")

    dupe = _find_live_duplicate(title)
    if dupe and apply and not getattr(post_card, "force", False):
        print(f"  BLOCKED: live listing {dupe['item_id']} already has this title "
              f"(${dupe.get('price', '?')}). Re-run with --force to post anyway.")
        return {"ack": "Blocked", "duplicate_of": dupe["item_id"], "title": title}

    print("  Uploading image to eBay EPS...")
    picture_url = upload_image(image_path, token, cfg)
    print(f"  Picture URL: {picture_url}")

    xml = build_xml(title, price, picture_url, token, category, condition)

    if not apply:
        print("  [dry-run] would post listing")
        return {"dry_run": True, "title": title, "price": price}

    headers = ebay_client.trading_headers("AddItem", cfg, token)
    resp = requests.post(TRADING_URL, headers=headers, data=xml.encode("utf-8"), timeout=30)
    body = resp.text

    ack_m    = re.search(r"<Ack>(.*?)</Ack>", body)
    item_m   = re.search(r"<ItemID>(.*?)</ItemID>", body)
    errors_m = re.findall(r"<ShortMessage>(.*?)</ShortMessage>", body)

    ack     = ack_m.group(1) if ack_m else "Unknown"
    item_id = item_m.group(1) if item_m else None

    if ack in ("Success", "Warning") and item_id:
        print(f"  Ack: {ack}  ItemID: {item_id}")
        print(f"  Live: https://www.ebay.com/itm/{item_id}")
        if errors_m:
            print(f"  Warnings: {errors_m}")
        return {"ack": ack, "item_id": item_id, "title": title, "price": price,
                "picture_url": picture_url}
    else:
        print(f"  FAILED ({ack}): {errors_m}")
        return {"ack": ack, "errors": errors_m, "title": title}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--image",  help="Path to a single card image")
    ap.add_argument("--title",  help="eBay listing title")
    ap.add_argument("--price",  type=float, help="List price in USD")
    ap.add_argument("--batch",  help="Path to JSON batch file")
    ap.add_argument("--apply",  action="store_true", help="Actually post (default: dry-run)")
    ap.add_argument("--force",  action="store_true",
                    help="Post even if a live listing already has this title")
    ap.add_argument("--sport",  default="Football",
                    help="Sport item-specific (default Football; e.g. Basketball)")
    args = ap.parse_args()
    post_card.force = args.force
    global SPORT
    SPORT = args.sport

    cfg   = json.loads(Path(paths.CONFIG).read_text())
    token = ebay_client.get_write_token(cfg)

    if args.batch:
        cards = json.loads(Path(args.batch).read_text())
    elif args.image and args.title and args.price:
        cards = [{"image": args.image, "title": args.title, "price": args.price}]
    else:
        ap.error("Provide --batch or --image + --title + --price")

    results = []
    for c in cards:
        img = Path(c["image"]).expanduser().resolve()
        if not img.exists():
            print(f"  Image not found: {img}")
            results.append({"error": "image not found", "title": c["title"]})
            continue
        r = post_card(img, c["title"], float(c["price"]), cfg, token, args.apply,
                      c.get("category", CATEGORY_ID), c.get("condition", CONDITION_ID))
        results.append(r)
        time.sleep(0.5)

    ok = sum(1 for r in results if r.get("item_id"))
    print(f"\nDone — {ok}/{len(results)} posted successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
