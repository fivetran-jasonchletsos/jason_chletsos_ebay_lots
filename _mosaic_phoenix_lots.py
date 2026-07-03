"""_mosaic_phoenix_lots.py — 2025 Panini Mosaic + Phoenix prizm/parallel lots.
Built from Scans 195-200.

  python3 _mosaic_phoenix_lots.py --pdf
  python3 _mosaic_phoenix_lots.py --apply [--only key1,key2]
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None
CROPS = Path("output/split_cards")
SET_LABEL = "2025 Panini Mosaic / Phoenix (Prizm Parallels)"

def crop(scan, nn):
    return CROPS / f"Scan {scan}" / f"Scan {scan}_{nn:02d}.jpg"

# cards: (scan, idx, "Player", "Team", is_rc)
LOTS = [
    {"key": "mp_stars", "price": 19.99,
     "title": "Panini Mosaic Phoenix Prizm Lot McCaffrey Higgins Samuel Godwin Adams Football",
     "theme": "Skill Star Lot",
     "cards": [(195, 6, "Christian McCaffrey", "49ers", False),
               (199, 7, "Tee Higgins", "Bengals", False),
               (196, 2, "Deebo Samuel", "Commanders", False),
               (196, 3, "Chris Godwin", "Buccaneers", False),
               (200, 1, "Davante Adams", "Rams", False)]},
    {"key": "mp_qb", "price": 16.99,
     "title": "Panini Mosaic Phoenix QB Lot Prescott Daniels Penix Richardson Young Football",
     "theme": "Quarterback Lot",
     "cards": [(197, 3, "Dak Prescott", "Cowboys", False),
               (200, 7, "Jayden Daniels", "Commanders", False),
               (200, 5, "Michael Penix Jr", "Falcons", False),
               (198, 2, "Anthony Richardson", "Colts", False),
               (195, 7, "Bryce Young", "Panthers", False)]},
    {"key": "mp_hof1", "price": 17.99,
     "title": "Panini Mosaic HOF Lot Favre Manning Faulk Tim Brown Thurman Thomas Football",
     "theme": "Hall of Fame Lot",
     "cards": [(197, 6, "Brett Favre", "Packers", False),
               (197, 9, "Peyton Manning", "Colts", False),
               (198, 7, "Marshall Faulk", "Rams", False),
               (198, 8, "Tim Brown", "Raiders", False),
               (195, 3, "Thurman Thomas", "Dolphins", False)]},
    {"key": "mp_hof2", "price": 13.99,
     "title": "Panini Mosaic Legends Lot Steve Young Spurrier Kosar Anderson White Football",
     "theme": "Legends Lot",
     "cards": [(195, 4, "Steve Young", "49ers", False),
               (196, 5, "Steve Spurrier", "49ers", False),
               (196, 9, "Bernie Kosar", "Browns", False),
               (196, 6, "Jamal Anderson", "Falcons", False),
               (198, 5, "Roddy White", "Falcons", False)]},
    {"key": "mp_rookwr", "price": 12.99,
     "title": "Panini Mosaic Phoenix Rookie WR Lot Gadsden Higgins Ayomanor Mumpfield Felton",
     "theme": "Rookie WR / TE Lot",
     "cards": [(195, 5, "Oronde Gadsden II", "Chargers", True),
               (198, 3, "Jayden Higgins", "Texans", True),
               (196, 8, "Elic Ayomanor", "Titans", True),
               (198, 4, "Konata Mumpfield", "Rams", True),
               (199, 3, "Tai Felton", "Vikings", True)]},
    {"key": "mp_rook", "price": 12.99,
     "title": "Panini Mosaic Rookie Lot Jaydon Blue Sampson Mellott Royals Emmanwori RC",
     "theme": "Rookie Lot",
     "cards": [(198, 1, "Jaydon Blue", "Cowboys", True),
               (196, 1, "Dylan Sampson", "Browns", True),
               (197, 4, "Tommy Mellott", "Raiders", True),
               (197, 7, "Jalen Royals", "Chiefs", True),
               (197, 1, "Nick Emmanwori", "Seahawks", True)]},
    {"key": "mp_def", "price": 13.99,
     "title": "Panini Phoenix Mosaic Defense Lot Surtain Derwin James Hairston Tuimoloau RC",
     "theme": "Defense / Rookie Lot",
     "cards": [(199, 2, "Patrick Surtain II", "Broncos", False),
               (199, 4, "Derwin James Jr", "Chargers", False),
               (198, 9, "Maxwell Hairston", "Bills", True),
               (200, 3, "JT Tuimoloau", "Colts", True),
               (199, 1, "Andres Borregales", "Patriots", True)]},
    {"key": "mp_wr", "price": 14.99,
     "title": "Panini Phoenix Mosaic WR Lot McConkey Coleman Shakir Watson Pickens Football",
     "theme": "Wide Receiver Lot",
     "cards": [(200, 8, "Ladd McConkey", "Chargers", False),
               (199, 9, "Keon Coleman", "Bills", False),
               (195, 1, "Khalil Shakir", "Bills", False),
               (195, 9, "Christian Watson", "Packers", False),
               (196, 4, "George Pickens", "Cowboys", False)]},
    {"key": "mp_mix1", "price": 13.99,
     "title": "Panini Phoenix Mosaic Lot Andrews Brian Thomas AJ Green Muhammad Lewis Football",
     "theme": "WR / TE Lot",
     "cards": [(199, 6, "Mark Andrews", "Ravens", False),
               (198, 6, "Brian Thomas Jr", "Jaguars", False),
               (199, 5, "A.J. Green", "Bengals", False),
               (200, 2, "Muhsin Muhammad", "Panthers", False),
               (195, 2, "Jamal Lewis", "Browns", False)]},
    {"key": "mp_mix2", "price": 11.99,
     "title": "Panini Mosaic Prizm Lot Hubbard Ertz Bryce Young Highsmith Van Ginkel Football",
     "theme": "Mixed Prizm Lot",
     "cards": [(196, 7, "Chuba Hubbard", "Panthers", False),
               (195, 8, "Zach Ertz", "Commanders", False),
               (197, 8, "Bryce Young", "Panthers", False),
               (200, 4, "Alex Highsmith", "Steelers", False),
               (197, 5, "Andrew Van Ginkel", "Vikings", False)]},
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
            "<li>2025 Panini Mosaic &amp; Phoenix prizm / parallel cards.</li>"
            "<li>Raw / ungraded, pack-fresh condition.</li>"
            "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
            "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
            "</ul>"
            "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")
        specifics = {"Sport": "Football", "Set": "2025 Panini Mosaic",
                     "Type": "Sports Trading Card Lot",
                     "Features": "Lot, Prizm, Parallel", "League": "National Football League (NFL)"}
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
        out = Path("output/mosaic_phoenix_lots_pull_sheet.pdf")
        build_pdf(out)
        print(f"PDF: {out}")
    if a.apply:
        do_apply(set(a.only.split(",")) if a.only else None)
    if not (a.pdf or a.apply):
        ap.error("pass --pdf and/or --apply")


if __name__ == "__main__":
    sys.exit(main())
