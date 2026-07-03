"""Revise the live RB Lot #1 (item 307039867632) down to 4 cards after pulling
Bucky Irving (026/249 serial) out to sell individually. New collage + description
+ title. Reuses the (now Bucky-free) sel_rb1 lot from _select_lots.
"""
import json, sys, requests
from pathlib import Path
from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag
from post_from_scan import upload_image
import _select_lots as S

ITEM_ID = "307039867632"

def main():
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    lot = next(l for l in S.LOTS if l["key"] == "sel_rb1")
    n = len(lot["cards"])
    print(f"sel_rb1 now has {n} cards: " + ", ".join(p for (_, _, p, _, _) in lot["cards"]))
    assert n == 4, "expected 4 cards after Bucky pull"

    paths = [S.crop(s, c) for (s, c, *_) in lot["cards"]]
    collage = S.build_collage(paths, Path("output/_lot_sel_rb1_collage.jpg"))
    url = upload_image(collage, token, cfg)
    print(f"  new picture: {url}")

    items = "".join(
        f"<li>{xml_escape(p)}{' RC' if rc else ''} - {xml_escape(t)}</li>"
        for (_, _, p, t, rc) in lot["cards"])
    desc = (
        f"<h3>{xml_escape(lot['theme'])} - {xml_escape(S.SET_LABEL)}</h3>"
        f"<p>You receive <b>all {n} cards pictured</b> in one shipment:</p>"
        f"<ul>{items}</ul>"
        "<ul>"
        "<li>2024 / 2025 Panini Select prizm / parallel cards.</li>"
        "<li>Raw / ungraded, pack-fresh condition.</li>"
        "<li>Shipped together sleeved + in a top loader via eBay Standard Envelope.</li>"
        "<li>VOLUME DISCOUNT: combine with any other cards in our store.</li>"
        "</ul>"
        "<p>Independent collector since 1998. Real cards, real photos, fast shipping.</p>")

    xml = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{ITEM_ID}</ItemID>
    <Title>{xml_escape(lot['title'][:80])}</Title>
    <Description><![CDATA[{desc}]]></Description>
    <PictureDetails><PictureURL>{xml_escape(url)}</PictureURL></PictureDetails>
  </Item>
</ReviseItemRequest>"""
    r = requests.post(TRADING_URL, headers=trading_headers("ReviseItem", cfg, token),
                      data=xml.encode("utf-8"), timeout=40)
    ack = find_tag(r.text, "Ack")
    if ack in ("Success", "Warning"):
        print(f"  REVISED ({ack}) -> https://www.ebay.com/itm/{ITEM_ID}")
        print(f"  new title: {lot['title'][:80]}")
    else:
        print(f"  REVISE FAILED ({ack}): {r.text[:500]}")

if __name__ == "__main__":
    sys.exit(main())
