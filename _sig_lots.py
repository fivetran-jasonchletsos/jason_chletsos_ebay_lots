"""_sig_lots.py — build 7 themed lots from the 2025 Topps Signature Class Red
scan crops (Scans 168-171). Two modes:

  python3 _sig_lots.py --pdf              # build pull-sheet PDF (no eBay)
  python3 _sig_lots.py --apply            # collage + AddItem each lot live

Reuses ebay_client + post_from_scan.upload_image + build_lot_listing helpers.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CROPS = Path("output/split_cards")

def crop(scan, nn):
    return CROPS / f"Scan {scan}" / f"Scan {scan}_{nn:02d}.jpg"

# (crop scan, crop idx, "Player", "Team", is_rc)
LOTS = [
    {"key": "sig_qb", "price": 16.99,
     "title": "2025 Topps Signature Class Red QB Lot Murray Goff Young RC Football",
     "theme": "Quarterback Lot",
     "cards": [(170, 4, "Kyler Murray", "Cardinals", False),
               (171, 3, "Jared Goff", "Lions", False),
               (168, 5, "Bryce Young", "Panthers", False),
               (168, 7, "Sam Darnold", "Seahawks", False),
               (171, 6, "Quinn Ewers", "Dolphins", True)]},
    {"key": "sig_rb", "price": 16.99,
     "title": "2025 Topps Signature Class Red RB Lot Bijan Mixon Pollard Warren Football",
     "theme": "Running Back Lot",
     "cards": [(171, 9, "Bijan Robinson", "Falcons", False),
               (169, 6, "Joe Mixon", "Texans", False),
               (170, 6, "Tony Pollard", "Titans", False),
               (169, 1, "Jaylen Warren", "Steelers", False),
               (169, 9, "RJ Harvey", "Broncos", True)]},
    {"key": "sig_rookrb", "price": 10.99,
     "title": "2025 Topps Signature Class Red Rookie RB Lot RC Gordon Marks Neal Football",
     "theme": "Rookie RB / Skill Lot",
     "cards": [(169, 3, "Ollie Gordon II", "Dolphins", True),
               (169, 7, "Woody Marks", "Texans", True),
               (169, 5, "Devin Neal", "Saints", True),
               (170, 7, "Jaydon Blue", "Cowboys", True),
               (171, 8, "Jaylin Noel", "Texans", True)]},
    {"key": "sig_wr", "price": 13.99,
     "title": "2025 Topps Signature Class Red WR Lot Olave Diggs Legette RC Football",
     "theme": "Wide Receiver Lot",
     "cards": [(169, 4, "Chris Olave", "Saints", False),
               (171, 5, "Stefon Diggs", "Patriots", False),
               (168, 4, "Xavier Legette", "Panthers", False),
               (170, 5, "Savion Williams", "Packers", True),
               (171, 2, "Tez Johnson", "Buccaneers", True)]},
    {"key": "sig_rookwr", "price": 9.99,
     "title": "2025 Topps Signature Class Red Rookie WR Lot Harris White Gadsden RC Football",
     "theme": "Rookie WR Lot",
     "cards": [(168, 1, "Tre Harris", "Chargers", True),
               (170, 8, "Ricky White III", "Seahawks", True),
               (168, 9, "Oronde Gadsden II", "Chargers", True),
               (171, 4, "Tez Johnson", "Buccaneers", True),
               (170, 1, "Alec Pierce", "Colts", False)]},
    {"key": "sig_trench", "price": 8.99,
     "title": "2025 Topps Signature Class Red Rookie Lot Booker Banks Conerly RC Football",
     "theme": "Rookie Trenches + TE Lot",
     "cards": [(170, 3, "Tyler Booker", "Cowboys", True),
               (169, 8, "Kelvin Banks Jr", "Saints", True),
               (168, 3, "Josh Conerly Jr", "Commanders", True),
               (169, 2, "Ty Robinson", "Eagles", True),
               (168, 8, "Terrance Ferguson", "Rams", True)]},
    {"key": "sig_mix", "price": 11.99,
     "title": "2025 Topps Signature Class Red Rookie Lot Judkins Bowman Burke Blue RC Football",
     "theme": "Rookie Mix Lot",
     "cards": [(171, 7, "Quinshon Judkins", "Browns", True),
               (168, 2, "Billy Bowman Jr", "Falcons", True),
               (168, 6, "Denzel Burke", "Cardinals", True),
               (171, 1, "Jaydon Blue", "Cowboys", True),
               (170, 2, "Jaylen Reed", "Texans", True)]},
    {"key": "sig_wr2", "price": 10.99,
     "title": "2025 Topps Signature Class Red Rookie WR Lot Pittman TeSlaa Bryant RC Football",
     "theme": "Rookie WR Lot #2",
     "cards": [(173, 3, "Michael Pittman Jr", "Colts", False),
               (172, 2, "Isaac TeSlaa", "Lions", True),
               (172, 6, "Pat Bryant", "Broncos", True),
               (172, 7, "Jaylin Lane", "Commanders", True),
               (174, 4, "Elic Ayomanor", "Titans", True)]},
    {"key": "sig_rbtr", "price": 8.99,
     "title": "2025 Topps Signature Class Red Rookie Lot Irving Tuten Zabel Walker RC Football",
     "theme": "Rookie RB + Trenches Lot",
     "cards": [(174, 2, "Bucky Irving", "Buccaneers", False),
               (174, 6, "Bhayshul Tuten", "Jaguars", True),
               (174, 3, "Grey Zabel", "Seahawks", True),
               (172, 5, "Deone Walker", "Bills", True),
               (172, 3, "Bradyn Swinson", "Patriots", True)]},
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
    PW, PH = 1275, 1650  # ~8.5x11 @ 150dpi
    MARGIN = 34
    hf, lf, tf = _font(30), _font(22), _font(20)
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
        # header strip
        d.rectangle([MARGIN, top, PW - MARGIN, top + 40], fill=(150, 20, 20))
        d.text((MARGIN + 12, top + 6),
               f"LOT {i+1}   {lot['theme']}   -   ${lot['price']:.2f} OBO",
               font=hf, fill="white")
        # 5 cards across
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
    import ebay_client
    from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
    from post_from_scan import upload_image
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    results = []
    lots = [l for l in LOTS if not only or l["key"] in only]
    for lot in lots:
        paths = [crop(s, n) for (s, n, *_) in lot["cards"]]
        collage = build_collage(paths, Path(f"output/_lot_{lot['key']}_collage.jpg"))
        print(f"\n=== {lot['theme']} ({lot['title'][:60]}) ===")
        print(f"  collage: {collage}")
        url = upload_image(collage, token, cfg)
        print(f"  picture: {url}")
        items = "".join(
            f"<li>{xml_escape(p)}{' RC' if rc else ''} - {xml_escape(t)}</li>"
            for (_, _, p, t, rc) in lot["cards"])
        desc = (
            f"<h3>{xml_escape(lot['theme'])} - 2025 Topps Signature Class (Red Parallel)</h3>"
            "<p>You receive <b>all 5 cards pictured</b> in one shipment:</p>"
            f"<ul>{items}</ul>"
            "<ul>"
            "<li>2025 Topps Signature Class - the RED parallel of each card.</li>"
            "<li>Raw / ungraded, pack-fresh condition.</li>"
            "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
            "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
            "</ul>"
            "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")
        specifics = {"Sport": "Football", "Set": "2025 Topps Signature Class",
                     "Parallel/Variety": "Red", "Type": "Sports Trading Card Lot",
                     "Features": "Lot, Insert, Rookie", "League": "National Football League (NFL)"}
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
        import requests
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
        print(f"  {theme:26s} ${price:6.2f}  {iid or 'FAILED'}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", help="comma-separated lot keys to apply")
    a = ap.parse_args()
    if a.pdf:
        out = Path("output/signature_class_red_lots_pull_sheet.pdf")
        build_pdf(out)
        print(f"PDF: {out}")
    if a.apply:
        do_apply(set(a.only.split(",")) if a.only else None)
    if not (a.pdf or a.apply):
        ap.error("pass --pdf and/or --apply")


if __name__ == "__main__":
    sys.exit(main())
