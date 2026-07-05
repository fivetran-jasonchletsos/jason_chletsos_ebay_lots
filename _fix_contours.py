"""Strip the false '1/1 Printing Plate' claim from the 4 live Phoenix Contours
color cards (JC confirmed they aren't serial-numbered 1/1s). Retitle by color,
reprice to $12.99, and clean the item specifics."""
import json
from pathlib import Path
import requests
from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag

# item_id -> (new_title, color, rc, team)
FIX = {
 "307044254082": ("Panini Phoenix Contours TreVeyon Henderson Cyan RC Patriots Football", "Cyan", True),
 "307044254144": ("Panini Phoenix Contours Tetairoa McMillan Cyan RC Panthers Football", "Cyan", True),
 "307044254236": ("Panini Phoenix Contours Xavier Worthy Red Chiefs Football", "Red", False),
 "307044254281": ("Panini Phoenix Contours RJ Harvey Black RC Broncos Football", "Black", True),
}
PRICE = 12.99

cfg = json.loads(Path("configuration.json").read_text())
token = get_write_token(cfg)

def revise(iid, title, color, rc):
    spec = {"Sport":"Football","Type":"Sports Trading Card",
            "League":"National Football League (NFL)","Original/Licensed Reprint":"Original",
            "Card Condition":"Near Mint or Better","Parallel/Variety":f"Contours {color}"}
    if rc: spec["Features"]="Rookie"
    sx = "".join(f"<NameValueList><Name>{xml_escape(k)}</Name><Value>{xml_escape(v)}</Value></NameValueList>"
                 for k,v in spec.items())
    xml = (f'<?xml version="1.0" encoding="utf-8"?>'
           f'<ReviseFixedPriceItemRequest xmlns="{NS}">'
           f'<RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>'
           f'<Item><ItemID>{iid}</ItemID><Title>{xml_escape(title)}</Title>'
           f'<StartPrice currencyID="USD">{PRICE:.2f}</StartPrice>'
           f'<ItemSpecifics>{sx}</ItemSpecifics></Item></ReviseFixedPriceItemRequest>')
    r = requests.post(TRADING_URL, headers=trading_headers("ReviseFixedPriceItem", cfg, token),
                      data=xml.encode("utf-8"), timeout=40)
    return find_tag(r.text,"Ack"), r.text

for iid,(title,color,rc) in FIX.items():
    ack,txt = revise(iid, title, color, rc)
    if ack in ("Success","Warning"):
        print(f"  OK  {iid}  ${PRICE}  {title}")
    else:
        err = txt[txt.find('<ShortMessage>'):txt.find('</ShortMessage>')+15] if '<ShortMessage>' in txt else txt[:200]
        print(f"  FAIL ({ack}) {iid}: {err}")
