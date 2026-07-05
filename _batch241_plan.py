"""_batch241_plan.py — classify Scans 221-240 into SINGLES vs 4-max LOTS.

Rules:
  SINGLE  = printing plate (1/1), marquee player/legend, dual-star Paramount
            Pairings, or a premium insert of a notable rookie/star.
  LOT     = everything else, packed <=4 cards, grouped by product family +
            position, no repeated player in a lot (penny-saver friendly).
Outputs a printed plan + a PDF pull sheet.
"""
import argparse, sys, json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
Image.MAX_IMAGE_PIXELS = None
CROPS = Path("output/split_cards")

def crop(scan, idx): return CROPS / f"Scan {scan}" / f"Scan {scan}_{idx:02d}.jpg"

# (scan, idx, player, team, pos, product, parallel, rc)
C = [
 (221,1,"Pickens/Lamb","Cowboys","Multi","Topps Icons","Paramount Pairings",0),
 (221,2,"Kurt Warner","Rams","Legend","Mosaic","Touchdown Masters Green",0),
 (221,3,"Hurts/Barkley","Eagles","Multi","Topps Icons","Paramount Pairings",0),
 (221,4,"CeeDee Lamb","Cowboys","WR","Topps Icons","The Pick",0),
 (221,5,"Gibbs/Montgomery","Lions","Multi","Topps Icons","Paramount Pairings",0),
 (221,6,"Hurts/Barkley","Eagles","Multi","Topps Icons","Paramount Pairings",0),
 (221,7,"Calvin Johnson","Lions","Legend","Mosaic","Touchdown Masters",0),
 (221,8,"Love/Jacobs","Packers","Multi","Topps Icons","Paramount Pairings",0),
 (221,9,"Kelce/Mahomes","Chiefs","Multi","Topps Icons","Paramount Pairings",0),
 (222,1,"Lamar/Henry","Ravens","Multi","Topps Icons","Paramount Pairings",0),
 (222,2,"Maye/Diggs","Patriots","Multi","Topps Icons","Paramount Pairings",0),
 (222,3,"Brock Bowers","Raiders","TE","Prizm","Fractal",0),
 (222,4,"Caleb Williams/Odunze","Bears","Multi","Topps Icons","Paramount Pairings",0),
 (222,5,"Trevor Lawrence","Jaguars","QB","Prizm","Base",0),
 (222,6,"Tua Tagovailoa","Dolphins","QB","Prizm","Fireworks Green",0),
 (222,7,"Gibbs/Montgomery","Lions","Multi","Topps Icons","Paramount Pairings",0),
 (222,8,"Josh Allen","Bills","QB","Prizm","Fractal",0),
 (222,9,"Pickens/Lamb","Cowboys","Multi","Topps Icons","Paramount Pairings",0),
 (223,1,"J.J. McCarthy","Vikings","QB","Phoenix","Paragon",0),
 (223,2,"TreVeyon Henderson","Patriots","RB","Topps Icons","The Pick",1),
 (223,3,"Jalen Hurts","Eagles","QB","Prizm","Fireworks Green",0),
 (223,4,"Michael Penix Jr","Falcons","QB","Phoenix","Paragon",0),
 (223,5,"Geno Smith","Raiders","QB","Topps Icons","Base",0),
 (223,6,"Emeka Egbuka","Buccaneers","WR","Prizm","Fireworks Green",1),
 (223,7,"Deebo Samuel","Commanders","WR","Topps Icons","Base",0),
 (223,8,"Quinshon Judkins","Browns","RB","Prizm","Fireworks",1),
 (223,9,"Tua Tagovailoa","Dolphins","QB","Prizm","Fireworks",0),
 # Scan 224 was fully shuffled by the auto-ID; corrected below via anchored re-read.
 (224,1,"Ashton Jeanty","Raiders","RB","Phoenix","Paragon Orange",1),
 (224,2,"Xavier Worthy","Chiefs","WR","Select","Select Certified",1),
 (224,3,"TreVeyon Henderson","Patriots","RB","Select","Future",1),
 (224,4,"Zay Flowers","Ravens","WR","Topps Icons","Base",0),
 (224,5,"Malachi Corley","Jets","WR","Select","Select Certified",1),
 (224,6,"Matthew Golden","Packers","WR","Select","Future",1),
 (224,7,"Bo Nix","Broncos","QB","Phoenix","Paragon Orange",0),
 (224,8,"Blake Corum","Rams","RB","Select","Select Certified",1),
 (224,9,"Colston Loveland","Bears","TE","Select","Future",1),
 (225,1,"J.J. McCarthy","Vikings","QB","Select","Numbers",0),
 (225,2,"George Pickens","Cowboys","WR","Topps Class Action","Base",0),
 (225,3,"Jalen Hurts","Eagles","QB","Topps Sunday Showcase","Base",0),
 (225,4,"Jermaine Burton","Bengals","WR","Select","Select Certified",1),
 (225,5,"Cam Ward","Titans","QB","Topps Class Action","Base",1),
 (225,6,"Zach Ertz","Commanders","TE","Mosaic","Purple",0),
 (225,7,"Jalen Milroe","Seahawks","QB","Select","Select Certified",1),
 (225,8,"Joe Burrow","Bengals","QB","Topps Sunday Showcase","Base",0),
 (225,9,"Dylan Sampson","Browns","RB","Mosaic","Green",1),
 (226,1,"Mason Taylor","Jets","TE","Select","Future",1),
 (226,2,"Jordan Love","Packers","QB","Select","Numbers",0),
 (226,3,"Cam Ward","Titans","QB","Select","Numbers",1),
 (226,4,"Davante Adams","Rams","WR","Select","Numbers",0),
 (226,5,"Davante Adams","Rams","WR","Select","Numbers",0),
 (226,6,"Micah Parsons","Packers","Defense","Select","Numbers",0),
 (226,7,"Baker Mayfield","Buccaneers","QB","Select","Numbers",0),
 (226,8,"J.J. McCarthy","Vikings","QB","Select","Numbers",0),
 (226,9,"Michael Penix Jr","Falcons","QB","Select","Numbers",0),
 (227,1,"Jim Zorn","Seahawks","Legend","Phoenix","Fire Burst Blue",0),
 (227,2,"Malachi Moore","Jets","Defense","Topps Chrome Cosmic","Round 4 Pick 28",1),
 (227,3,"Jaylen Warren","Steelers","RB","Topps Chrome Cosmic","Undrafted",0),
 (227,4,"Chris Chambers","Dolphins","Legend","Phoenix","Fire Burst Teal",0),
 (227,5,"Ja'Marr Chase","Bengals","WR","Topps Chrome Cosmic","Round 1 Pick 5",0),
 (227,6,"Donovan Ezeiruaku","Cowboys","Defense","Topps Chrome Cosmic","Round 2 Pick 12",1),
 (227,7,"Nic Scourton","Panthers","Defense","Topps Chrome Cosmic","Round 2 Pick 19",1),
 (227,8,"Davante Adams","Rams","WR","Topps Chrome Cosmic","Round 2 Pick 21",0),
 (227,9,"Zach Ertz","Commanders","TE","Topps Chrome Cosmic","Round 2 Pick 3",0),
 (228,1,"Tyler Shough","Saints","QB","Select","Future",1),
 (228,2,"Tyler Shough","Saints","QB","Select","Future",1),
 (228,3,"Kaleb Johnson","Steelers","RB","Select","Future",1),
 (228,4,"Mason Taylor","Jets","TE","Select","Future",1),
 (228,5,"Ashton Jeanty","Raiders","RB","Select","Select Certified",1),
 (228,6,"Quinshon Judkins","Browns","RB","Select","Select Certified",1),
 (228,7,"Jalon Walker","Falcons","Defense","Select","Select Certified",1),
 (228,8,"Elijah Arroyo","Seahawks","TE","Select","Select Certified",1),
 (228,9,"Matthew Golden","Packers","WR","Select","Select Certified",1),
 (229,1,"Patrick Mahomes","Chiefs","QB","Totally Certified","Franchise Foundations",0),
 (229,2,"DJ Moore","Bears","WR","Totally Certified","Base",0),
 (229,3,"Luther Burden III","Bears","WR","Prizm","Prizmatic",1),
 (229,4,"Dallas Turner","Vikings","Defense","Totally Certified","Intriguing Players",1),
 (229,5,"Sam LaPorta","Lions","TE","Donruss","Base",0),
 (229,6,"Bijan Robinson","Falcons","RB","Select","Numbers",1),
 (229,7,"Aaron Jones","Vikings","RB","Totally Certified","Intriguing Players",0),
 (229,8,"Brock Bowers","Raiders","TE","Revolution","Base",0),
 (229,9,"Jayden Reed","Packers","WR","Select","Select Certified",1),
 (230,1,"Jordan Addison","Vikings","WR","Select","Turbocharged",1),
 (230,2,"Ashton Jeanty","Raiders","RB","Phoenix","Base",1),
 (230,3,"Sam Darnold","Seahawks","QB","Mosaic","Notoriety",0),
 (230,4,"Dalton Kincaid","Bills","TE","Select","Die-Cut",1),
 (230,5,"Davante Adams","Rams","WR","Donruss","Bomb Squad",0),
 (230,6,"Jonnu Smith","Steelers","TE","Topps Chrome","Pink XFractor",0),
 (230,7,"Colston Loveland","Bears","TE","Revolution","Base",1),
 (230,8,"Emeka Egbuka","Buccaneers","WR","Mosaic","Elevate Green",1),
 (230,9,"Joe Alt","Chargers","Defense","Topps Chrome","Pink XFractor",0),
 (231,1,"Kelvin Banks Jr","Saints","Defense","Prizm","Green Shimmer",1),
 (231,2,"Joe Montana","49ers","Legend","Prizm","Prizmatic",0),
 (231,3,"RJ Harvey","Broncos","RB","Prizm","Emergent",1),
 (231,4,"Derwin James Jr","Chargers","Defense","Prizm","Green Shimmer",0),
 (231,5,"Ashton Jeanty","Raiders","RB","Prizm","Prizmatic",1),
 (231,6,"Tai Felton","Vikings","WR","Mosaic","Elevate",1),
 (231,7,"Mike Vrabel","Patriots","Legend","Prizm","Green Shimmer",0),
 (231,8,"Caleb Williams","Bears","QB","Prizm","Global Reach Green",0),
 (231,9,"Arch Manning","Texas","QB","Prizm Draft","Instant Impact",0),
 (232,1,"Ryan Wingo","Texas","WR","Prizm Draft","Red Cracked Ice",1),
 (232,2,"Riley Leonard","Notre Dame","QB","Prizm Draft","New Recruits Green",1),
 (232,3,"Zy Alexander","LSU","Defense","Prizm Draft","Purple Wave",1),
 (232,4,"Omarion Hampton","Chargers","RB","Prizm","Green Cracked Ice",1),
 (232,5,"Xavier Watts","Notre Dame","Defense","Prizm Draft","Green",1),
 (232,6,"T.J. Sanders","South Carolina","Defense","Prizm Draft","Red Cracked Ice",1),
 (232,7,"Jalen Milroe","Alabama","QB","Prizm Draft","Fearless Red Cracked Ice",1),
 (232,8,"Nick Emmanwori","South Carolina","Defense","Prizm Draft","Purple Wave",1),
 (232,9,"Tez Johnson","Buccaneers","WR","Optic","Rated Rookie Purple",1),
 # Scan 233 was a DUPLICATE scan of the Prizm Draft page (Scan 232); its 9
 # "Optic" cards were an auto-ID hallucination and have been removed. The two
 # real Optic Rated Rookie Blue cards come from Scan 241 (JC re-scanned them):
 (241,1,"Robbie Ouzts","Seahawks","TE","Optic","Rated Rookie Blue",1),
 # Optic cards from JC's clean re-scans (241/243):
 (243,1,"Cole Kmet","Bears","TE","Optic","Blue Stars",0),
 (243,2,"Tyleik Williams","Lions","Defense","Optic","Rated Rookie Blue Stars",1),
 (243,3,"Tyleik Williams","Lions","Defense","Optic","Rated Rookie Blue",1),
 (234,1,"Keon Coleman","Bills","WR","Select","Future",1),
 (234,2,"Alvin Kamara","Saints","RB","Select","Turbocharged Orange",0),
 (234,3,"T.J. Watt","Steelers","Defense","Select","Turbocharged Orange",0),
 (234,4,"Travis Hunter","Jaguars","WR","Select","Turbocharged Orange",1),
 (234,5,"Aaron Rodgers","Jets","QB","Select","Turbocharged Green",0),
 (234,6,"T.J. Watt","Steelers","Defense","Select","Turbocharged Orange",0),
 (234,7,"Xavier Worthy","Chiefs","WR","Select","Turbocharged Red",1),
 (234,8,"Aaron Rodgers","Jets","QB","Select","Turbocharged Green",0),
 (234,9,"Justin Fields","Jets","QB","Select","Turbocharged Orange",0),
 (235,1,"Jalen Royals","Chiefs","WR","Prizm Draft","Red Cracked Ice",1),
 (235,2,"Derrick Brown","Panthers","Defense","Topps Chrome","Pulse",0),
 (235,3,"Garrett Bradbury","Patriots","Defense","Topps Chrome","XFractor",0),
 (235,4,"Tuli Tuipulotu","Chargers","Defense","Topps Chrome","XFractor",0),
 (235,5,"Mark Andrews","Ravens","TE","Topps Chrome","XFractor",0),
 (235,6,"Garrett Williams","Cardinals","Defense","Topps Chrome","XFractor",0),
 (235,7,"Henry To'oto'o","Texans","Defense","Topps Chrome","Base",0),
 (235,8,"Tez Johnson","Buccaneers","WR","Topps Chrome","Pulse",1),
 (235,9,"Christian Watson","Packers","WR","Topps Chrome","XFractor",0),
 (236,1,"Joe Montana","49ers","Legend","Prizm","Prizmatic",0),
 (236,2,"Rome Odunze","Bears","WR","Phoenix Contours","Base",0),
 (236,3,"TreVeyon Henderson","Patriots","RB","Phoenix Contours","Printing Plate Cyan",1),
 (236,4,"Tetairoa McMillan","Panthers","WR","Phoenix Contours","Printing Plate Cyan",1),
 (236,5,"Rome Odunze","Bears","WR","Phoenix Contours","Base",0),
 (236,6,"T.J. Watt","Steelers","Defense","Phoenix Contours","Printing Plate Yellow",0),
 (236,7,"Xavier Worthy","Chiefs","WR","Phoenix Contours","Printing Plate Magenta",0),
 (236,8,"TreVeyon Henderson","Patriots","RB","Phoenix Contours","Printing Plate Cyan",1),
 (236,9,"RJ Harvey","Broncos","RB","Phoenix Contours","Printing Plate Black",1),
 (237,1,"Quincy Riley","Saints","Defense","Topps Icons","Base",1),
 (237,2,"Tyler Booker","Cowboys","Defense","Topps Icons","Base",1),
 (237,3,"Marvin Mims Jr","Broncos","WR","Topps Icons","Base",0),
 (237,4,"Kobe Hudson","Panthers","WR","Topps Icons","Base",1),
 (237,5,"Jordan James","49ers","RB","Topps Icons","Base",1),
 (237,6,"Rome Odunze","Bears","WR","Phoenix Contours","Base",0),
 (237,7,"Jack Sawyer","Steelers","Defense","Topps Icons","Base",1),
 (237,8,"David Njoku","Browns","TE","Topps Icons","Base",0),
 (237,9,"T.J. Watt","Steelers","Defense","Phoenix Contours","Printing Plate Yellow",0),
 (238,1,"Malachi Moore","Jets","Defense","Topps Icons","Base",1),
 (238,2,"Kyle Kennard","Chargers","Defense","Topps Icons","Base",1),
 (238,3,"Mike Green","Ravens","Defense","Topps Icons","Base",1),
 (238,4,"Tommy Mellott","Raiders","QB","Topps Icons","Base",1),
 (238,5,"Malachi Moore","Jets","Defense","Topps Icons","Base",1),
 (238,6,"Jonah Savaiinaea","Dolphins","Defense","Topps Icons","Base",1),
 (238,7,"Quincy Riley","Saints","Defense","Topps Icons","Base",1),
 (238,8,"Antwaun Powell-Ryland","Eagles","Defense","Topps Icons","Base",1),
 (238,9,"Jack Bech","Raiders","WR","Select","Select Certified",1),
 (239,1,"Jalen Royals","Chiefs","WR","Mosaic","Green",1),
 (239,2,"Jaydon Blue","Cowboys","RB","Mosaic","Silver",1),
 (239,3,"Chase Brown","Bengals","RB","Phoenix","Orange",0),
 (239,4,"Tommy Mellott","Raiders","QB","Mosaic","Green",1),
 (239,5,"Alex Highsmith","Steelers","Defense","Phoenix","Base",0),
 (239,6,"Nick Emmanwori","Seahawks","Defense","Mosaic","Green",1),
 (240,1,"Anthony Richardson","Colts","QB","Totally Certified","Franchise Foundations",0),
 (240,2,"Mark Andrews","Ravens","TE","Phoenix","Blue",0),
 (240,3,"Marist Liufau","Cowboys","Defense","Totally Certified","Purple",1),
 (240,4,"Calen Bullock","Texans","Defense","Phoenix","Blue",1),
 (240,5,"Christian McCaffrey","49ers","RB","Phoenix","Blue",0),
]

# Marquee names -> always a single
STARS = {"Patrick Mahomes","Joe Montana","Josh Allen","Lamar/Henry","Jalen Hurts",
 "Joe Burrow","Christian McCaffrey","CeeDee Lamb","Ja'Marr Chase","Bijan Robinson",
 "Brock Bowers","Sam LaPorta","Mark Andrews","Micah Parsons","Kurt Warner",
 "Calvin Johnson","Ashton Jeanty","Travis Hunter","Cam Ward","Tetairoa McMillan",
 "Omarion Hampton","Luther Burden III","Arch Manning","Caleb Williams","Trevor Lawrence",
 "Colston Loveland","Matthew Golden","Quinshon Judkins","Emeka Egbuka","TreVeyon Henderson",
 "Mason Taylor"}

def is_single(c):
    scan,idx,player,team,pos,prod,par,rc = c
    if "Printing Plate" in par: return True          # 1/1 plates
    if pos == "Multi": return True                    # dual-star Paramount Pairings
    if "Touchdown Masters" in par or par=="The Pick": return True
    if player in STARS: return True
    return False

def fam(c):
    """Product family for lot grouping."""
    prod = c[5]
    if prod == "Topps Icons": return "Topps Icons Rookies"
    if prod == "Topps Chrome Cosmic": return "Chrome Cosmic Round-Pick"
    if prod == "Topps Chrome": return "Chrome XFractor"
    if prod.startswith("Select"):
        if "Numbers" in c[6]: return "Select Numbers"
        if "Turbo" in c[6]: return "Select Turbocharged"
        if "Future" in c[6]: return "Select Future"
        return "Select Certified"
    if prod == "Optic": return "Optic Rookies"
    if prod == "Prizm Draft": return "Prizm Draft College"
    if prod == "Prizm": return "Prizm"
    if prod == "Mosaic": return "Mosaic"
    if prod.startswith("Phoenix"): return "Phoenix"
    if prod == "Totally Certified": return "Totally Certified"
    return prod

POS_ORDER = {"QB":0,"RB":1,"WR":2,"TE":3,"Defense":4,"Legend":5,"Multi":6}

def build():
    singles = [c for c in C if is_single(c)]
    lot_pool = [c for c in C if not is_single(c)]
    # group by product family ONLY, pack <=4, spread dup players across lots
    from collections import defaultdict
    groups = defaultdict(list)
    for c in lot_pool:
        groups[fam(c)].append(c)
    lots = []
    for family, cards in sorted(groups.items()):
        cards = sorted(cards, key=lambda c: POS_ORDER.get(c[4],9))
        n = max(1, -(-len(cards)//4))  # ceil /4
        buckets = [[] for _ in range(n)]
        for c in cards:
            order = sorted(range(n), key=lambda b:(len(buckets[b]),b))
            placed = False
            for b in order:
                if len(buckets[b]) < 4 and all(x[2]!=c[2] for x in buckets[b]):
                    buckets[b].append(c); placed=True; break
            if not placed:
                # allow into least-full bucket with room (dup player unavoidable)
                cand = [b for b in range(n) if len(buckets[b])<4] or list(range(n))
                min(cand,key=lambda b:len(buckets[b]))
                buckets[min(cand,key=lambda b:len(buckets[b]))].append(c)
        for b in buckets:
            if b: lots.append({"family":family,"pos":"mixed","cards":b})
    return singles, lots

BRAND = {
 "Prizm":"Panini Prizm","Select":"Panini Select","Mosaic":"Panini Mosaic",
 "Optic":"Panini Donruss Optic","Phoenix":"Panini Phoenix",
 "Phoenix Contours":"Panini Phoenix Contours","Totally Certified":"Panini Totally Certified",
 "Topps Icons":"2025 Topps Icons","Topps Chrome":"Topps Chrome",
 "Topps Chrome Cosmic":"2025 Topps Chrome Cosmic","Prizm Draft":"Panini Prizm Draft Picks",
 "Revolution":"Panini Revolution","Donruss":"Panini Donruss",
 "Topps Class Action":"2025 Topps Signature Class","Topps Sunday Showcase":"2025 Topps Signature Class",
}
MARQUEE = {"Patrick Mahomes","Joe Burrow","Josh Allen","Jalen Hurts","Ashton Jeanty",
 "Cam Ward","Travis Hunter","Ja'Marr Chase","Brock Bowers","Bijan Robinson","CeeDee Lamb",
 "Micah Parsons","Christian McCaffrey","Trevor Lawrence","Caleb Williams","Arch Manning",
 "Mark Andrews","Sam LaPorta"}

def _title_single(c):
    scan,idx,player,team,pos,prod,par,rc = c
    b = BRAND.get(prod, prod)
    t = f"{b} {player}"
    if par and par != "Base": t += f" {par}"
    if "Printing Plate" in par: t += " 1/1"
    if rc: t += " RC"
    t += f" {team} Football"
    return t[:80]

def price_single(c):
    if "Printing Plate" in c[6]: return 24.99
    if c[4] == "Legend": return 9.99
    if c[4] == "Multi": return 6.99
    if c[2] in MARQUEE: return 6.99
    return 4.99

def price_lot(l):
    fam = l["family"]
    if "Icons Rookies" in fam or "Cosmic" in fam: return 5.99
    if fam in ("Select Certified","Select Future","Prizm Draft College","Optic Rookies","Mosaic"): return 7.99
    return 6.99

def _surname(n):
    p = n.replace("/"," ").split()
    return p[-1] if p and p[-1] not in ("Jr","Jr.","II","III") else (p[-2] if len(p)>1 else n)

def _lot_title(l):
    fam = l["family"]
    names = " ".join(_surname(c[2]) for c in l["cards"])
    t = f"{len(l['cards'])} Card Lot {fam} {names} Football RC"
    return t[:80]

def build_collage(paths, out):
    imgs = [Image.open(p).convert("RGB") for p in paths]
    ch = 520
    cells = [im.resize((int(im.width*ch/im.height), ch)) for im in imgs]
    pad, cols = 18, min(len(cells), 4)
    cw = max(c.width for c in cells)
    canvas = Image.new("RGB", (pad + cols*(cw+pad), pad + ch + pad), "white")
    x = pad
    for im in cells:
        canvas.paste(im, (x + (cw-im.width)//2, pad)); x += cw + pad
    canvas.save(out, "JPEG", quality=90); return out

def do_apply(mode):
    import requests
    from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
    from post_from_scan import upload_image
    cfg = json.loads(Path("configuration.json").read_text()); token = get_write_token(cfg)
    singles, lots = build()

    def add(title, price, url, desc, category, cond, specifics):
        sx = "".join(f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
                     for k,v in specifics.items())
        # Trading Card Singles (261328) require the Card Condition descriptor.
        cd = ("<ConditionDescriptors><ConditionDescriptor>"
              "<Name>40001</Name><Value>400010</Value>"
              "</ConditionDescriptor></ConditionDescriptors>") if category == "261328" else ""
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>{xml_escape(title)}</Title>
    <Description><![CDATA[{desc}]]></Description>
    <PrimaryCategory><CategoryID>{category}</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{price:.2f}</StartPrice>
    <ConditionID>{cond}</ConditionID>{cd}
    <Country>US</Country><Currency>USD</Currency><DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration><ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity><Location>United States</Location><PostalCode>19096</PostalCode>
    <BestOfferDetails><BestOfferEnabled>true</BestOfferEnabled></BestOfferDetails>
    <PictureDetails><PictureURL>{xml_escape(url)}</PictureURL></PictureDetails>
    <ItemSpecifics>{sx}</ItemSpecifics>
    <ShippingDetails><ShippingType>Flat</ShippingType><ApplyShippingDiscount>true</ApplyShippingDiscount>
      <ShippingServiceOptions><ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>US_eBayStandardEnvelope</ShippingService>
        <ShippingServiceCost currencyID="USD">1.32</ShippingServiceCost>
      </ShippingServiceOptions></ShippingDetails>
    <ShipToLocations>US</ShipToLocations>
    <ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>
  </Item>
</AddItemRequest>"""
        r = requests.post(TRADING_URL, headers=trading_headers("AddItem", cfg, token),
                          data=xml.encode("utf-8"), timeout=40)
        return find_tag(r.text,"Ack"), find_tag(r.text,"ItemID"), r.text

    ok = fail = 0
    if mode in ("singles","all"):
        for c in singles:
            title = _title_single(c); price = price_single(c)
            try:
                url = upload_image(crop(c[0],c[1]), token, cfg)
            except Exception as e:
                print(f"  UPLOAD FAIL {c[2]}: {e}"); fail+=1; continue
            desc = (f"<h3>{xml_escape(title)}</h3><p>You receive the <b>exact card pictured</b>.</p>"
                    "<ul><li>Raw / ungraded, pack-fresh condition.</li>"
                    "<li>Shipped in a penny sleeve + top loader (or team bag) via eBay Standard Envelope.</li>"
                    "<li>Combine with any other cards in our store for one shipping charge.</li></ul>")
            spec = {"Sport":"Football","Type":"Sports Trading Card",
                    "League":"National Football League (NFL)","Original/Licensed Reprint":"Original",
                    "Card Condition":"Near Mint or Better"}
            if "Printing Plate" in c[6]: spec["Features"]="1/1, Printing Plate"; spec["Parallel/Variety"]="Printing Plate"
            elif c[7]: spec["Features"]="Rookie"
            ack,iid,txt = add(title, price, url, desc, "261328", 4000, spec)
            if ack in ("Success","Warning") and iid:
                print(f"  S  ${price:5.2f} {iid}  {title[:52]}"); ok+=1
            else:
                print(f"  S  FAIL ({ack}) {title[:48]}: {txt[:160]}"); fail+=1
    if mode in ("lots","all"):
        for l in lots:
            paths = [crop(c[0],c[1]) for c in l["cards"]]
            key = (l['family']+l['cards'][0][2]).replace(' ','')[:24]
            collage = build_collage(paths, Path(f"output/_lot241_{key}.jpg"))
            try:
                url = upload_image(collage, token, cfg)
            except Exception as e:
                print(f"  LOT UPLOAD FAIL {l['family']}: {e}"); fail+=1; continue
            title = _lot_title(l); price = price_lot(l); n=len(l['cards'])
            items = "".join(f"<li>{xml_escape(c[2])}{' RC' if c[7] else ''} - {xml_escape(c[3])} ({xml_escape(BRAND.get(c[5],c[5]))} {xml_escape(c[6])})</li>" for c in l["cards"])
            desc = (f"<h3>{xml_escape(l['family'])} - {n} Card Lot</h3>"
                    f"<p>You receive <b>all {n} cards pictured</b>:</p><ul>{items}</ul>"
                    "<ul><li>Raw / ungraded, pack-fresh.</li>"
                    "<li>Shipped together sleeved in a penny sleeve + top loader via eBay Standard Envelope.</li>"
                    "<li>Combine with our other listings for one shipping charge.</li></ul>")
            spec = {"Sport":"Football","Type":"Sports Trading Card Lot","Features":"Lot",
                    "League":"National Football League (NFL)"}
            ack,iid,txt = add(title, price, url, desc, "261329", 3000, spec)
            if ack in ("Success","Warning") and iid:
                print(f"  L  ${price:5.2f} {iid}  {title[:52]}"); ok+=1
            else:
                print(f"  L  FAIL ({ack}) {title[:48]}: {txt[:160]}"); fail+=1
    print(f"\n  ==== {ok} posted, {fail} failed ====")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--pdf",action="store_true")
    ap.add_argument("--apply",choices=["singles","lots","all"]); a=ap.parse_args()
    if a.apply:
        return do_apply(a.apply)
    singles, lots = build()
    print(f"\n=== SINGLES ({len(singles)}) ===")
    for c in sorted(singles,key=lambda x:(x[4],x[2])):
        tag = "PLATE 1/1" if "Printing Plate" in c[6] else ("DUAL" if c[4]=="Multi" else c[4])
        print(f"  [{tag:9s}] {c[2]:26s} {c[5]} {c[6]}  (Scan {c[0]}#{c[1]})")
    nlot_cards=sum(len(l['cards']) for l in lots)
    print(f"\n=== LOTS ({len(lots)} lots, {nlot_cards} cards, <=4 each) ===")
    for i,l in enumerate(lots,1):
        names=", ".join(c[2] for c in l["cards"])
        print(f"  Lot {i:2d} [{l['family']} - {l['pos']}] ({len(l['cards'])}): {names}")
    print(f"\nTOTAL: {len(C)} cards -> {len(singles)} singles + {len(lots)} lots ({nlot_cards} cards)")
    if a.pdf:
        render(singles, lots)

def _font(s,b=False):
    for p in (("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if b else
               "/System/Library/Fonts/Supplemental/Arial.ttf"),):
        if Path(p).exists():
            try: return ImageFont.truetype(p,s)
            except: pass
    return ImageFont.load_default()

def render(singles, lots):
    PW,PH,M=1275,1650,40; th=150; gap=10
    hf,lf,tf=_font(26,True),_font(15),_font(13)
    pages=[]; page=Image.new("RGB",(PW,PH),"white"); d=ImageDraw.Draw(page); y=M
    def newpage():
        nonlocal page,d,y; pages.append(page); page=Image.new("RGB",(PW,PH),"white"); d=ImageDraw.Draw(page); y=M
    def band(txt,color):
        nonlocal y
        if y>PH-M-th-60: newpage()
        d.rectangle([M,y,PW-M,y+34],fill=color); d.text((M+10,y+6),txt,font=hf,fill="white"); y+=44
    def row(cards,label):
        nonlocal y
        if y>PH-M-th-30: newpage()
        d.text((M,y),label,font=_font(16,True),fill=(60,20,90)); y+=22
        x=M
        for c in cards:
            try:
                im=Image.open(crop(c[0],c[1])).convert("RGB"); w=int(im.width*th/im.height); im=im.resize((w,th))
            except: w=int(th*0.7); im=Image.new("RGB",(w,th),(230,230,230))
            if x+w>PW-M: x=M; y+=th+34
            page.paste(im,(x,y)); d.text((x,y+th+2),c[2][:16],font=tf,fill="black")
            d.text((x,y+th+16),(c[6] or c[5])[:18],font=tf,fill=(120,120,120)); x+=w+gap
        y+=th+40
    band(f"SINGLES — {len(singles)} cards","#5a1470".replace("#","") and (90,20,110))
    for c in sorted(singles,key=lambda x:(x[4],x[2])):
        row([c], ("PLATE 1/1 " if "Printing Plate" in c[6] else "")+c[2])
    band(f"LOTS — {len(lots)} lots (4 max)",(20,90,60))
    for i,l in enumerate(lots,1):
        row(l["cards"], f"Lot {i}: {l['family']} · {l['pos']} ({len(l['cards'])})")
    pages.append(page)
    out=Path("output/batch241_plan.pdf")
    pages[0].save(out,"PDF",save_all=True,append_images=pages[1:],resolution=150)
    import shutil
    try: shutil.copy(out, Path.home()/"Downloads"/"batch241_plan.pdf")
    except: pass
    print(f"PDF: {out} ({len(pages)} pages) + copied to ~/Downloads")

if __name__=="__main__": sys.exit(main())
