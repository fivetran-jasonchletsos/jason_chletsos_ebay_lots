"""_sig_chrome_lots.py — 2025 Topps Signature Class CHROME (refractor) lots.
Built from clean crops on Scans 175-181 (Scan 182 was misaligned, held out).

  python3 _sig_chrome_lots.py --pdf
  python3 _sig_chrome_lots.py --apply [--only key1,key2]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

CROPS = Path("output/split_cards")
SET_LABEL = "2025 Topps Signature Class Chrome (Refractor)"

def crop(scan, nn):
    return CROPS / f"Scan {scan}" / f"Scan {scan}_{nn:02d}.jpg"

# cards: (scan, idx, "Player", "Team", is_rc)
LOTS = [
    {"key": "ch_qb1", "price": 16.99,
     "title": "2025 Topps Signature Class Chrome QB Lot Burrow Herbert Goff Nix Football",
     "theme": "Quarterback Lot (Stars)",
     "cards": [(180, 6, "Joe Burrow", "Bengals", False),
               (175, 7, "Justin Herbert", "Chargers", False),
               (176, 1, "Jared Goff", "Lions", False),
               (178, 1, "Dak Prescott", "Cowboys", False),
               (181, 8, "Bo Nix", "Broncos", False)]},
    {"key": "ch_qb2", "price": 12.99,
     "title": "2025 Topps Signature Class Chrome QB Lot Young Darnold Jones RC Football",
     "theme": "Quarterback Lot (Young Guns)",
     "cards": [(177, 2, "Bryce Young", "Panthers", False),
               (176, 9, "Sam Darnold", "Seahawks", False),
               (177, 4, "Daniel Jones", "Colts", False),
               (181, 6, "Jalen Milroe", "Seahawks", True),
               (181, 4, "Riley Leonard", "Colts", True)]},
    {"key": "ch_rb", "price": 13.99,
     "title": "2025 Topps Signature Class Chrome RB Lot Gordon Cook Pollard Warren Football",
     "theme": "Running Back Lot",
     "cards": [(179, 6, "Ollie Gordon II", "Dolphins", True),
               (176, 3, "James Cook", "Bills", False),
               (178, 3, "Tony Pollard", "Titans", False),
               (175, 6, "Jaylen Warren", "Steelers", False),
               (176, 8, "Javonte Williams", "Cowboys", False)]},
    {"key": "ch_wr1", "price": 15.99,
     "title": "2025 Topps Signature Class Chrome WR Lot Hill Diggs Harrison Deebo Football",
     "theme": "Wide Receiver Lot (Stars)",
     "cards": [(180, 4, "Tyreek Hill", "Dolphins", False),
               (180, 8, "Stefon Diggs", "Patriots", False),
               (177, 8, "Marvin Harrison Jr", "Cardinals", False),
               (175, 5, "Deebo Samuel", "Commanders", False),
               (177, 6, "Marvin Mims Jr", "Broncos", False)]},
    {"key": "ch_wr2", "price": 9.99,
     "title": "2025 Topps Signature Class Chrome Rookie WR Lot Tez Royals Restrepo RC Football",
     "theme": "Rookie WR Lot",
     "cards": [(180, 1, "Tez Johnson", "Buccaneers", True),
               (177, 5, "Jalen Royals", "Chiefs", True),
               (175, 2, "Xavier Restrepo", "Titans", True),
               (176, 2, "Kobe Hudson", "Panthers", True),
               (177, 9, "Dont'e Thornton Jr", "Raiders", True)]},
    {"key": "ch_te", "price": 12.99,
     "title": "2025 Topps Signature Class Chrome TE Lot Bowers Njoku Ertz RC Football",
     "theme": "TE + Skill Lot",
     "cards": [(179, 1, "Brock Bowers", "Raiders", False),
               (180, 2, "David Njoku", "Browns", False),
               (175, 8, "Zach Ertz", "Commanders", False),
               (177, 1, "Jordan James", "49ers", True),
               (178, 7, "Nick Nash", "Falcons", True)]},
    {"key": "ch_edge1", "price": 8.99,
     "title": "2025 Topps Signature Class Chrome Rookie Edge Sawyer Kennard Green RC Football",
     "theme": "Rookie Pass Rush Lot",
     "cards": [(175, 9, "Antwaun Powell-Ryland", "Eagles", True),
               (176, 4, "Jack Sawyer", "Steelers", True),
               (180, 3, "Donovan Ezeiruaku", "Cowboys", True),
               (178, 5, "Kyle Kennard", "Chargers", True),
               (181, 7, "Mike Green", "Ravens", True)]},
    {"key": "ch_edge2", "price": 8.99,
     "title": "2025 Topps Signature Class Chrome Rookie Edge Burch Turner Baron RC Football",
     "theme": "Rookie Pass Rush Lot #2",
     "cards": [(177, 7, "Jordan Burch", "Cardinals", True),
               (178, 6, "Shemar Turner", "Bears", True),
               (179, 5, "Tyler Baron", "Jets", True),
               (175, 1, "Tyleik Williams", "Lions", True),
               (178, 4, "Antwaun Powell-Ryland", "Eagles", True)]},
    {"key": "ch_db1", "price": 9.99,
     "title": "2025 Topps Signature Class Chrome Rookie DB Lot Starks Moore Winston RC Football",
     "theme": "Rookie DB Lot",
     "cards": [(180, 5, "Malaki Starks", "Ravens", True),
               (176, 6, "Malachi Moore", "Jets", True),
               (179, 4, "Kevin Winston Jr", "Titans", True),
               (181, 1, "Lathan Ransom", "Panthers", True),
               (176, 5, "Billy Bowman Jr", "Falcons", True)]},
    {"key": "ch_db2", "price": 7.99,
     "title": "2025 Topps Signature Class Chrome Rookie DB Lot Riley Higgins Booker RC Football",
     "theme": "Rookie DB + Trenches Lot",
     "cards": [(175, 3, "Quincy Riley", "Saints", True),
               (175, 4, "Jay Higgins IV", "Ravens", True),
               (176, 7, "Danny Stutsman", "Saints", True),
               (177, 3, "Tyler Booker", "Cowboys", True),
               (181, 2, "Josh Simmons", "Chiefs", True)]},
    {"key": "ch_wr3", "price": 18.99,
     "title": "2025 Topps Signature Class Chrome WR Lot Chase Adams Mims RC Football",
     "theme": "WR Stars Lot #2 (Chase / Adams)",
     "cards": [(186, 2, "Ja'Marr Chase", "Bengals", False),
               (186, 1, "Davante Adams", "Rams", False),
               (178, 9, "Marvin Mims Jr", "Broncos", False),
               (179, 3, "Kobe Hudson", "Panthers", True),
               (179, 9, "Tommy Mellott", "Raiders", True)]},
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
        d.rectangle([MARGIN, top, PW - MARGIN, top + 40], fill=(20, 40, 90))
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
            "<li>2025 Topps Signature Class - the CHROME REFRACTOR of each card.</li>"
            "<li>Raw / ungraded, pack-fresh condition.</li>"
            "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
            "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
            "</ul>"
            "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")
        specifics = {"Sport": "Football", "Set": "2025 Topps Signature Class",
                     "Parallel/Variety": "Chrome Refractor", "Type": "Sports Trading Card Lot",
                     "Features": "Lot, Chrome, Rookie", "League": "National Football League (NFL)"}
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
        print(f"  {theme:32s} ${price:6.2f}  {iid or 'FAILED'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated lot keys")
    a = ap.parse_args()
    if a.pdf:
        out = Path("output/signature_class_chrome_lots_pull_sheet.pdf")
        build_pdf(out)
        print(f"PDF: {out}")
    if a.apply:
        do_apply(set(a.only.split(",")) if a.only else None)
    if not (a.pdf or a.apply):
        ap.error("pass --pdf and/or --apply")


if __name__ == "__main__":
    sys.exit(main())
