"""Post the Mahomes 5-card Icon lot ($5) for the German buyer rimor-33.
Builds a collage from the 5 cards' existing eBay images, uploads it, creates a
FixedPriceItem lot (cat 261329) that SHIPS INTERNATIONALLY, then ends the 3 live
singles so they can't double-sell. Dry-run default; --apply to post + end."""
import argparse, io, json
from pathlib import Path
import requests
from PIL import Image
import post_from_scan as pfs, ebay_client
from ebay_client import xml_escape, trading_headers, find_tag, TRADING_URL

NS = "urn:ebay:apis:eBLBaseComponents"
TITLE = "Patrick Mahomes 5 Card Lot Kansas City Chiefs Panini Icon Collection Football"
PRICE = 5.00
# (description name, image code, live item_id to END or None if already pulled)
CARDS = [
 ("2025 Panini Icon Collection #IC11 Patrick Mahomes II", "9qcAAeSwmT1qD1Sy", "307021791200"),
 ("2025 Panini Icon Collection #21 Patrick Mahomes",       "bykAAeSwEJpqD1OE", None),
 ("2025 Panini Icon Collection Highlights IC-1 Red Parallel Patrick Mahomes", "CC8AAeSw16pqD1Zi", None),
 ("2025 Donruss Optic Icon Connections Rashee Rice / Patrick Mahomes", "fcAAAeSw9SlqLlnd", "307001325778"),
 ("2025 Donruss Optic Icon Connections Clyde Edwards-Helaire / Patrick Mahomes", "MrEAAeSwS9pqLlnW", "307021785375"),
]
IMG_URL = "https://i.ebayimg.com/images/g/{}/s-l1000.jpg"
COLL = Path("output/_mahomes_lot_collage.jpg")

def build_collage():
    imgs=[]
    for _,code,_id in CARDS:
        for suf in ("s-l1000","s-l500"):
            try:
                r=requests.get(f"https://i.ebayimg.com/images/g/{code}/{suf}.jpg",timeout=30)
                if r.ok and r.content:
                    imgs.append(Image.open(io.BytesIO(r.content)).convert("RGB")); break
            except Exception: pass
        else:
            raise SystemExit(f"could not fetch image {code}")
    ch=520
    cells=[im.resize((int(im.width*ch/im.height),ch)) for im in imgs]
    pad,cols=16,3
    rows=[cells[i:i+cols] for i in range(0,len(cells),cols)]
    cw=max(c.width for c in cells)
    W=pad+cols*(cw+pad); H=pad+len(rows)*(ch+pad)
    canvas=Image.new("RGB",(W,H),"white")
    for r,row in enumerate(rows):
        row_w=len(row)*(cw+pad)-pad; x0=(W-row_w)//2; y=pad+r*(ch+pad)
        for im in row:
            canvas.paste(im,(x0+(cw-im.width)//2,y)); x0+=cw+pad
    canvas.save(COLL,"JPEG",quality=90)
    print(f"  collage {W}x{H} -> {COLL}")
    return COLL

def description():
    items="".join(f"<li>{xml_escape(n)}</li>" for n,_,_ in CARDS)
    return (f"<div style='font-family:Arial,sans-serif;font-size:15px'>"
            f"<h2>Patrick Mahomes II - Kansas City Chiefs - 5 Card Lot</h2>"
            f"<p>Five Patrick Mahomes cards (Panini Icon Collection &amp; Donruss Optic Icon Connections):</p>"
            f"<ul>{items}</ul>"
            f"<p>Cards ship in penny sleeves and a protective mailer. Combined discount lot. "
            f"International shipping available. Thanks for looking!</p></div>")

def add_lot(picture_url, tok, cfg, apply):
    specifics={"Sport":"Football","Player/Athlete":"Patrick Mahomes II",
               "Team":"Kansas City Chiefs","Type":"Sports Trading Card Lot","Features":"Lot"}
    sx="".join(f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>" for k,v in specifics.items())
    xml=f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(tok)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <Title>{xml_escape(TITLE[:80])}</Title>
    <Description><![CDATA[{description()}]]></Description>
    <PrimaryCategory><CategoryID>261329</CategoryID></PrimaryCategory>
    <StartPrice currencyID="USD">{PRICE:.2f}</StartPrice>
    <ConditionID>3000</ConditionID>
    <Country>US</Country><Currency>USD</Currency>
    <DispatchTimeMax>3</DispatchTimeMax>
    <ListingDuration>GTC</ListingDuration>
    <ListingType>FixedPriceItem</ListingType>
    <Quantity>1</Quantity>
    <Location>United States</Location><PostalCode>19096</PostalCode>
    <PictureDetails><PictureURL>{xml_escape(picture_url)}</PictureURL></PictureDetails>
    <ItemSpecifics>{sx}</ItemSpecifics>
    <ShippingDetails>
      <ShippingType>Flat</ShippingType>
      <ShippingServiceOptions>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>USPSFirstClass</ShippingService>
        <ShippingServiceCost currencyID="USD">1.32</ShippingServiceCost>
      </ShippingServiceOptions>
      <InternationalShippingServiceOption>
        <ShippingServicePriority>1</ShippingServicePriority>
        <ShippingService>OtherInternational</ShippingService>
        <ShippingServiceCost currencyID="USD">5.99</ShippingServiceCost>
        <ShipToLocation>Worldwide</ShipToLocation>
      </InternationalShippingServiceOption>
    </ShippingDetails>
    <ShipToLocations>Worldwide</ShipToLocations>
    <ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>
  </Item>
</AddItemRequest>"""
    if not apply:
        print(f"  [dry-run] would ADD lot '{TITLE}' @ ${PRICE:.2f} (ships Worldwide)"); return None
    r=requests.post(TRADING_URL,headers=trading_headers("AddItem",cfg,tok),data=xml.encode(),timeout=40)
    ack=find_tag(r.text,"Ack"); nid=find_tag(r.text,"ItemID")
    if ack in ("Success","Warning") and nid:
        print(f"  ADDED lot ({ack}) -> https://www.ebay.com/itm/{nid}"); return nid
    print(f"  ADD FAILED ({ack}): {r.text[:500]}"); return None

def end_item(iid, tok, cfg, apply):
    if not apply:
        print(f"  [dry-run] would END single {iid}"); return
    body=(f'<?xml version="1.0" encoding="utf-8"?><EndFixedPriceItemRequest xmlns="{NS}">'
          f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
          f'<ItemID>{iid}</ItemID><EndingReason>NotAvailable</EndingReason></EndFixedPriceItemRequest>')
    r=requests.post(TRADING_URL,headers=trading_headers("EndFixedPriceItem",cfg,tok),data=body.encode(),timeout=40)
    print(f"  ended {iid}: {find_tag(r.text,'Ack')}")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--apply",action="store_true"); a=ap.parse_args()
    cfg=json.loads(Path("configuration.json").read_text()); tok=ebay_client.get_write_token(cfg)
    print("Building collage from the 5 card images...")
    coll=build_collage()
    pic=None
    if a.apply:
        pic=pfs.upload_image(coll,tok,cfg); print(f"  uploaded -> {pic}")
    nid=add_lot(pic or "https://example.com/placeholder.jpg", tok, cfg, a.apply)
    print("Ending the 3 live singles (IC11, Rashee, Clyde)...")
    for _,_,iid in CARDS:
        if iid: end_item(iid, tok, cfg, a.apply)
    print(f"\n=== {'APPLIED' if a.apply else 'DRY-RUN'} · lot {'posted '+str(nid) if nid else 'not posted'} ===")

if __name__=="__main__": main()
