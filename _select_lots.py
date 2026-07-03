"""_select_lots.py — 2024/2025 Panini Select lots (Scans 205-218, 119 cards).

Lots are generated programmatically: cards are bucketed by position group, then
greedily packed into 5-card lots such that no lot repeats a player. Titles are
auto-built from the headliner surnames.

  python3 _select_lots.py --pdf
  python3 _select_lots.py --apply [--only key1,key2]
  python3 _select_lots.py --list        # print the generated lots
"""
from __future__ import annotations
import argparse, json, sys, math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

Image.MAX_IMAGE_PIXELS = None
CROPS = Path("output/split_cards")
SET_LABEL = "2024/2025 Panini Select"

def crop(scan, nn):
    return CROPS / f"Scan {scan}" / f"Scan {scan}_{nn:02d}.jpg"

# (scan, idx, player, team, pos, rc)
CARDS = [
    (205,1,"Kyle Pitts","Falcons","TE",False),(205,2,"Xavier Worthy","Chiefs","WR",True),
    (205,3,"Kam Chancellor","Seahawks","DB",False),(205,4,"Ricky Pearsall","49ers","WR",True),
    (205,5,"Jarquez Hunter","Rams","RB",True),(205,6,"Tucker Kraft","Packers","TE",False),
    (205,7,"Blake Corum","Rams","RB",True),(205,8,"Tony Pollard","Titans","RB",False),
    (205,9,"Hunter Henry","Patriots","TE",False),
    (206,1,"Jonathan Taylor","Colts","RB",False),(206,2,"Patrick Queen","Steelers","LB",False),
    (206,3,"Rashod Bateman","Ravens","WR",False),(206,4,"Curtis Samuel","Bills","WR",False),
    (206,5,"Jayden Reed","Packers","WR",False),(206,6,"James Conner","Cardinals","RB",False),
    (206,7,"Aaron Rodgers","Steelers","QB",False),(206,8,"Jalen Royals","Chiefs","WR",True),
    (206,9,"Demetrius Knight Jr","Bengals","LB",True),
    (207,1,"Tyler Lockett","Seahawks","WR",False),(207,2,"KeAndre Lambert-Smith","Chargers","WR",True),
    (207,3,"Cam Little","Jaguars","K",True),(207,4,"Jaylin Lane","Commanders","WR",True),
    (207,5,"Xavier Legette","Panthers","WR",True),(207,6,"Nic Scourton","Panthers","DL",True),
    (207,7,"Trevor Lawrence","Jaguars","QB",False),(207,8,"Isaiah Likely","Ravens","TE",False),
    (207,9,"Greg Rousseau","Bills","DL",False),
    (208,1,"Rashod Bateman","Ravens","WR",False),(208,2,"Pat Freiermuth","Steelers","TE",False),
    (208,3,"Roquan Smith","Ravens","LB",False),(208,4,"Dalton Kincaid","Bills","TE",False),
    (208,5,"Olumuyiwa Fashanu","Jets","DL",True),(208,6,"A.J. Green","Bengals","WR",False),
    (208,7,"Baker Mayfield","Buccaneers","QB",False),(208,8,"Najee Harris","Chargers","RB",False),
    (208,9,"Sam Darnold","Seahawks","QB",False),
    (209,1,"Ollie Gordon II","Dolphins","RB",True),(209,2,"Elic Ayomanor","Titans","WR",True),
    (209,3,"Jared Goff","Lions","QB",False),(209,4,"Dalton Kincaid","Bills","TE",False),
    (209,5,"A.J. Green","Bengals","WR",False),(209,6,"Courtland Sutton","Broncos","WR",False),
    (209,7,"Josh Jacobs","Packers","RB",False),(209,8,"Philip Rivers","Chargers","QB",False),
    (209,9,"Josh Jacobs","Packers","RB",False),
    (210,1,"Bryce Young","Panthers","QB",False),(210,2,"Dak Prescott","Cowboys","QB",False),
    (210,3,"J.J. McCarthy","Vikings","QB",True),(210,4,"Ickey Woods","Bengals","RB",False),
    (210,5,"Michael Pittman Jr","Colts","WR",False),(210,6,"David Montgomery","Lions","RB",False),
    (210,7,"Tyleik Williams","Lions","DL",True),(210,8,"Fred Warner","49ers","LB",False),
    (210,9,"Marvin Harrison Jr","Cardinals","WR",True),
    (211,1,"Ray-Ray McCloud","Falcons","WR",False),(211,2,"Braelon Allen","Jets","RB",True),
    (211,3,"Kyle Pitts","Falcons","TE",False),(211,4,"Tee Higgins","Bengals","WR",False),
    (211,5,"Breece Hall","Jets","RB",False),(211,6,"Michael Pittman Jr","Colts","WR",False),
    (211,7,"Tory Taylor","Bears","K",True),(211,8,"Dan Hampton","Bears","DL",False),
    (211,9,"Savion Williams","Packers","WR",True),
    (212,1,"Gus Edwards","Chargers","RB",False),(212,2,"Patrick Surtain II","Broncos","DB",False),
    (212,3,"Ty Johnson","Bills","RB",False),(212,4,"Demetrius Knight Jr","Bengals","LB",True),
    (212,5,"Josh Allen","Bills","QB",False),(212,6,"Ernest Jones","Seahawks","LB",False),
    (212,7,"Najee Harris","Steelers","RB",False),(212,8,"Elic Ayomanor","Titans","WR",True),
    (212,9,"Julio Jones","Falcons","WR",False),
    (213,1,"Riley Leonard","Colts","QB",True),(213,2,"Deebo Samuel","Commanders","WR",False),
    (213,3,"Trey Hendrickson","Bengals","DL",False),(213,4,"Darnell Washington","Steelers","TE",False),
    (213,5,"Bucky Irving","Buccaneers","RB",False),(213,6,"Jayden Reed","Packers","WR",False),
    (213,7,"Tariq Woolen","Seahawks","DB",False),(213,8,"Jack Bech","Raiders","WR",True),
    (213,9,"Will Reichard","Vikings","K",True),
    (214,1,"Brock Bowers","Raiders","TE",True),(214,2,"Jameson Williams","Lions","WR",False),
    (214,3,"Rashid Shaheed","Saints","WR",False),(214,4,"Jalon Walker","Falcons","LB",True),
    (214,5,"Fred Warner","49ers","LB",False),(214,6,"Brian Urlacher","Bears","LB",False),
    (214,7,"Josaiah Stewart","Rams","LB",True),(214,8,"Carson Steele","Chiefs","RB",True),
    (214,9,"Geno Smith","Raiders","QB",False),
    (215,1,"Jeffery Simmons","Titans","DL",False),(215,2,"Deebo Samuel","Commanders","WR",False),
    (215,3,"Jaydon Blue","Cowboys","RB",True),(215,4,"Marvin Harrison Jr","Cardinals","WR",False),
    (215,5,"Davante Adams","Rams","WR",False),(215,6,"Dak Prescott","Cowboys","QB",False),
    (215,7,"Trevor Etienne","Panthers","RB",True),(215,8,"Michael Penix Jr","Falcons","QB",False),
    (215,9,"Trey Amos","Commanders","DB",True),
    (216,1,"Ezekiel Elliott","Cowboys","RB",False),(216,2,"Josh Jacobs","Packers","RB",False),
    (216,3,"Mo Alie-Cox","Colts","TE",False),(216,4,"Tremaine Edmunds","Bears","LB",False),
    (216,5,"Mike Evans","Buccaneers","WR",False),(216,6,"Bryan Anger","Cowboys","K",False),
    (216,7,"DJ Moore","Bears","WR",False),(216,8,"Christian Gonzalez","Patriots","DB",False),
    (216,9,"Pat Freiermuth","Steelers","TE",False),
    (217,1,"Jahdae Barron","Broncos","DB",True),(217,2,"Marshon Lattimore","Commanders","DB",False),
    (217,3,"Tai Felton","Vikings","WR",True),(217,4,"Woody Marks","Texans","RB",True),
    (217,5,"Calvin Ridley","Titans","WR",False),(217,6,"Trey Benson","Cardinals","RB",False),
    (217,7,"JT Tuimoloau","Colts","DL",True),(217,8,"Demetrius Knight Jr","Bengals","LB",True),
    (217,9,"Bryce Young","Panthers","QB",False),
    (218,1,"DJ Moore","Bears","WR",False),(218,2,"Isaac TeSlaa","Lions","WR",True),
]

# Cards pulled OUT of the lots to sell individually (serialized / high value).
# Removed AFTER bucketing so the remaining lots stay identical to what posted.
PULL_SINGLES = {(213, 5)}  # Bucky Irving 026/249 serial — post as a single

GROUP = {"QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE",
         "DL": "Defense", "DB": "Defense", "LB": "Defense", "K": "Defense"}
GROUP_PRICE = {"QB": 15.99, "RB": 14.99, "WR": 14.99, "TE": 13.99, "Defense": 12.99}
GROUP_ORDER = ["QB", "RB", "WR", "TE", "Defense"]


def _surname(name):
    return name.split()[-1] if name.split()[-1] not in ("Jr", "II", "III") else name.split()[-2]


def build_lots():
    """Bucket by group, greedily pack into <=5-card lots with no repeated player."""
    lots = []
    for g in GROUP_ORDER:
        cards = [c for c in CARDS if GROUP[c[4]] == g]
        # Place each card in the LEAST-FULL lot that doesn't already hold that
        # player. ceil(n/5) buckets guarantees a HARD MAX of 5 cards per lot
        # (JC's rule — never 6), while keeping sizes balanced (no singletons).
        n_lots = max(1, math.ceil(len(cards) / 5))
        buckets = [[] for _ in range(n_lots)]
        for c in cards:
            order = sorted(range(n_lots), key=lambda bi: (len(buckets[bi]), bi))
            for bi in order:
                if all(x[2] != c[2] for x in buckets[bi]):
                    buckets[bi].append(c); break
            else:
                min(buckets, key=len).append(c)
        for i, b in enumerate(buckets, 1):
            b = [c for c in b if (c[0], c[1]) not in PULL_SINGLES]
            names = " ".join(_surname(c[2]) for c in b)
            title = f"Panini Select {g} Lot {names} Football"
            lots.append({
                "key": f"sel_{g.lower()}{i}",
                "price": GROUP_PRICE[g],
                "theme": f"{g} Lot #{i}",
                "cards": [(c[0], c[1], c[2], c[3], c[5]) for c in b],
                "title": title,
            })
    return lots

LOTS = build_lots()


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
    cells = [im.resize((int(im.width * cell_h / im.height), cell_h)) for im in imgs]
    pad, cols = 18, 3
    rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
    cell_w = max(c.width for c in cells)
    canvas_w = pad + cols * (cell_w + pad)
    canvas_h = pad + len(rows) * (cell_h + pad)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    for r, row in enumerate(rows):
        x0 = (canvas_w - (len(row) * (cell_w + pad) - pad)) // 2
        y = pad + r * (cell_h + pad)
        for im in row:
            canvas.paste(im, (x0 + (cell_w - im.width) // 2, y))
            x0 += cell_w + pad
    canvas.save(out_path, "JPEG", quality=90)
    return out_path


def build_pdf(out_pdf, per_page=4):
    PW, PH = 1275, 1650
    MARGIN = 34
    hf, lf, tf = _font(26), _font(21), _font(19)
    thumb_h, gap = 268, 14
    band_h = (PH - 2 * MARGIN) // per_page
    pages = []
    page = Image.new("RGB", (PW, PH), "white"); d = ImageDraw.Draw(page)
    for i, lot in enumerate(LOTS):
        slot = i % per_page
        if slot == 0 and i > 0:
            pages.append(page)
            page = Image.new("RGB", (PW, PH), "white"); d = ImageDraw.Draw(page)
        top = MARGIN + slot * band_h
        d.rectangle([MARGIN, top, PW - MARGIN, top + 40], fill=(70, 20, 90))
        d.text((MARGIN + 12, top + 8), f"LOT {i+1}   {lot['theme']}   -   ${lot['price']:.2f} OBO",
               font=hf, fill="white")
        y = top + 52; x = MARGIN + 8
        for (scan, nn, player, team, rc) in lot["cards"]:
            im = Image.open(crop(scan, nn)).convert("RGB")
            w = int(im.width * thumb_h / im.height)
            im = im.resize((w, thumb_h))
            page.paste(im, (x, y))
            d.text((x, y + thumb_h + 4), player + (" RC" if rc else ""), font=lf, fill="black")
            d.text((x, y + thumb_h + 28), team, font=tf, fill=(110, 110, 110))
            x += w + gap
    pages.append(page)
    pages[0].save(out_pdf, "PDF", save_all=True, append_images=pages[1:], resolution=150)
    return out_pdf


def do_apply(only=None):
    import requests
    from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
    from post_from_scan import upload_image
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    results = []
    lots = [l for l in LOTS if not only or l["key"] in only]
    for lot in lots:
        paths = [crop(s, n) for (s, n, *_) in lot["cards"]]
        collage = build_collage(paths, Path(f"output/_lot_{lot['key']}_collage.jpg"))
        print(f"\n=== {lot['theme']} ({lot['title'][:50]}) ===")
        url = upload_image(collage, token, cfg)
        n = len(lot["cards"])
        items = "".join(
            f"<li>{xml_escape(p)}{' RC' if rc else ''} - {xml_escape(t)}</li>"
            for (_, _, p, t, rc) in lot["cards"])
        desc = (
            f"<h3>{xml_escape(lot['theme'])} - {xml_escape(SET_LABEL)}</h3>"
            f"<p>You receive <b>all {n} cards pictured</b> in one shipment:</p>"
            f"<ul>{items}</ul>"
            "<ul>"
            "<li>2024 / 2025 Panini Select prizm / parallel cards.</li>"
            "<li>Raw / ungraded, pack-fresh condition.</li>"
            "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
            "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
            "</ul>"
            "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")
        specifics = {"Sport": "Football", "Set": "2025 Panini Select",
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
            print(f"  ADD FAILED ({ack}): {r.text[:300]}")
            results.append((lot["theme"], None, lot["price"]))
    print("\n==== SUMMARY ====")
    ok = sum(1 for _, i, _ in results if i)
    for theme, iid, price in results:
        print(f"  {theme:16s} ${price:6.2f}  {iid or 'FAILED'}")
    print(f"  {ok}/{len(results)} lots posted")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdf", action="store_true")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--only", help="comma-separated lot keys")
    a = ap.parse_args()
    if a.list:
        for i, l in enumerate(LOTS, 1):
            print(f"{i:2d} {l['key']:10s} ${l['price']:.2f}  " +
                  ", ".join(f"{p}" for (_, _, p, _, _) in l["cards"]))
        print(f"total {len(LOTS)} lots, {sum(len(l['cards']) for l in LOTS)} cards")
    if a.pdf:
        out = Path("output/select_lots_pull_sheet.pdf"); build_pdf(out); print(f"PDF: {out}")
    if a.apply:
        do_apply(set(a.only.split(",")) if a.only else None)
    if not (a.pdf or a.apply or a.list):
        ap.error("pass --pdf, --apply, or --list")


if __name__ == "__main__":
    sys.exit(main())
