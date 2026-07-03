"""_sunday_showcase_lots.py — 2025 Topps Signature Class "Sunday Showcase" QB lots.
Built from Scans 203-204.

  python3 _sunday_showcase_lots.py --pdf
  python3 _sunday_showcase_lots.py --apply [--only key1,key2]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None
CROPS = Path("output/split_cards")
SET_LABEL = "2025 Topps Signature Class - Sunday Showcase"

def crop(scan, nn):
    return CROPS / f"Scan {scan}" / f"Scan {scan}_{nn:02d}.jpg"

# cards: (scan, idx, "Player", "Team", is_rc)
LOTS = [
    {"key": "ss_qb1", "price": 16.99,
     "title": "2025 Topps Signature Class Sunday Showcase QB Lot Burrow Allen Hurts Daniels Stroud",
     "theme": "QB Star Lot #1",
     "cards": [(204, 1, "Joe Burrow", "Bengals", False),
               (204, 4, "Josh Allen", "Bills", False),
               (203, 2, "Jalen Hurts", "Eagles", False),
               (203, 3, "Jayden Daniels", "Commanders", False),
               (203, 6, "C.J. Stroud", "Texans", False)]},
    {"key": "ss_qb2", "price": 14.99,
     "title": "2025 Topps Signature Class Sunday Showcase QB Lot Murray Love Mayfield Young Lawrence",
     "theme": "QB Star Lot #2",
     "cards": [(204, 2, "Kyler Murray", "Cardinals", False),
               (204, 3, "Jordan Love", "Packers", False),
               (203, 1, "Baker Mayfield", "Buccaneers", False),
               (203, 4, "Bryce Young", "Panthers", False),
               (203, 5, "Trevor Lawrence", "Jaguars", False)]},
]


def _font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        if Path(p).exists():
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def build_collage(card_paths, out_path):
    imgs = [Image.open(p).convert("RGB") for p in card_paths]
    cell_h = 520
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


def build_pdf(out_pdf, per_page=4):
    PW, PH = 1275, 1650
    MARGIN = 34
    hf, lf, tf = _font(28), _font(22), _font(20)
    thumb_h, gap = 268, 14
    band_h = (PH - 2 * MARGIN) // per_page
    pages = []

    def new_page():
        pg = Image.new("RGB", (PW, PH), "white")
        return pg, ImageDraw.Draw(pg)

    page, d = new_page()
    for i, lot in enumerate(LOTS):
        slot = i % per_page
        if slot == 0 and i > 0:
            pages.append(page)
            page, d = new_page()
        top = MARGIN + slot * band_h
        d.rectangle([MARGIN, top, PW - MARGIN, top + 40], fill=(70, 20, 90))
        d.text((MARGIN + 12, top + 7),
               f"LOT {i+1}   {lot['theme']}   -   ${lot['price']:.2f} OBO",
               font=hf, fill="white")
        y = top + 52
        x = MARGIN + 8
        for (scan, nn, player, team, rc) in lot["cards"]:
            im = Image.open(crop(scan, nn)).convert("RGB")
            w = int(im.width * thumb_h / im.height)
            im = im.resize((w, thumb_h))
            page.paste(im, (x, y))
            d.text((x, y + thumb_h + 4), player + (" RC" if rc else ""), font=lf, fill="black")
            d.text((x, y + thumb_h + 30), team, font=tf, fill=(110, 110, 110))
            x += w + gap
    pages.append(page)
    pages[0].save(out_pdf, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return out_pdf


def do_apply(only=None):
    import ebay_client, requests
    from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
    from post_from_scan import upload_image
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    results = []
    lots = [l for l in LOTS if not only or l["key"] in only]
    for lot in lots:
        paths = [crop(s, n) for (s, n, *_) in lot["cards"]]
        collage = build_collage(paths, Path(f"output/_lot_{lot['key']}_collage.jpg"))
        print(f"\n=== {lot['theme']} ({lot['title'][:52]}) ===")
        url = upload_image(collage, token, cfg)
        print(f"  picture: {url}")
        items = "".join(
            f"<li>{xml_escape(p)}{' RC' if rc else ''} - {xml_escape(t)}</li>"
            for (_, _, p, t, rc) in lot["cards"])
        desc = (
            f"<h3>{xml_escape(lot['theme'])} - {xml_escape(SET_LABEL)}</h3>"
            "<p>You receive <b>all 5 cards pictured</b> in one shipment:</p>"
            f"<ul>{items}</ul>"
            "<ul>"
            "<li>2025 Topps Signature Class - Sunday Showcase insert of each card.</li>"
            "<li>Raw / ungraded, pack-fresh condition.</li>"
            "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
            "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
            "</ul>"
            "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")
        specifics = {"Sport": "Football", "Set": "2025 Topps Signature Class",
                     "Insert Set": "Sunday Showcase", "Type": "Sports Trading Card Lot",
                     "Features": "Lot, Insert", "League": "National Football League (NFL)"}
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
    <BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>
    <PictureDetails><PictureURL>{xml_escape(url)}</PictureURL></PictureDetails>
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
        r = requests.post(TRADING_URL, headers=trading_headers("AddItem", cfg, token),
                          data=xml.encode("utf-8"), timeout=40)
        ack = find_tag(r.text, "Ack"); new_id = find_tag(r.text, "ItemID")
        if ack in ("Success", "Warning") and new_id:
            print(f"  ADDED ({ack}) -> https://www.ebay.com/itm/{new_id}")
            results.append((lot["theme"], new_id, lot["price"]))
        else:
            print(f"  ADD FAILED ({ack}): {r.text[:400]}")
            results.append((lot["theme"], None, lot["price"]))
    print("\n==== SUMMARY ====")
    for theme, iid, price in results:
        print(f"  {theme:24s} ${price:6.2f}  {iid or 'FAILED'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated lot keys")
    a = ap.parse_args()
    if a.pdf:
        out = Path("output/signature_class_sunday_showcase_lots_pull_sheet.pdf")
        build_pdf(out)
        print(f"PDF: {out}")
    if a.apply:
        do_apply(set(a.only.split(",")) if a.only else None)
    if not (a.pdf or a.apply):
        ap.error("pass --pdf and/or --apply")


if __name__ == "__main__":
    sys.exit(main())
