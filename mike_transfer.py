"""Move stale unsold cards from harpua2001 to Mike's account (mikeboy-40).

Source pool: output/_mike_transfer_candidates.json — pulled-repository items
over $5, screened (no lots, no Sixers/never-list, no EMT-buyer Sig Class).
For each card: GetItem on JC's account (ended listings readable ~90 days),
then AddFixedPriceItem on Mike's account with the same title/desc/pics/
specifics/shipping. Cards stay physically with JC, so Location stays Wynnewood.

Mike's token lives in .env (MIKE_EBAY_AUTH_TOKEN) — gitignored, never commit.
New eBay accounts usually cap at ~10 items / $500 a month, so batch small.

Dry-run default; --apply posts to Mike's live account (JC gate: he confirms
and physically pulls the cards first)."""
import argparse, json, re
import xml.etree.ElementTree as ET
from pathlib import Path
import requests, ebay_client

NS = {"e": "urn:ebay:apis:eBLBaseComponents"}
CAND = Path("output/_mike_transfer_candidates.json")
LOG = Path("output/mike_transfer_log.json")


def env_token(name="MIKE_EBAY_AUTH_TOKEN"):
    for line in Path(".env").read_text().splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"{name} not found in .env")


def get_item(iid, cfg, tok):
    body = (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<GetItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
            f'<ItemID>{iid}</ItemID><DetailLevel>ReturnAll</DetailLevel>'
            f'<IncludeItemSpecifics>true</IncludeItemSpecifics></GetItemRequest>')
    h = ebay_client.trading_headers("GetItem", cfg, tok)
    r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
    root = ET.fromstring(r.text)
    ack = root.findtext("e:Ack", namespaces=NS)
    if ack not in ("Success", "Warning"):
        return None, ebay_client.find_tag(r.text, "LongMessage") or "GetItem failed"
    return root.find("e:Item", NS), None


def xtext(el, path):
    x = el.find(path, NS)
    return x.text if x is not None else None


def build_add_xml(item, price, mike_tok):
    title = xtext(item, "e:Title") or ""
    desc = xtext(item, "e:Description") or title
    cat = xtext(item, "e:PrimaryCategory/e:CategoryID") or "261328"
    cond = xtext(item, "e:ConditionID") or "4000"
    # trading-card categories require the Card Condition descriptor (40001);
    # copy from source, default Near Mint or Better (400010)
    cdesc = ""
    for cd in item.findall("e:ConditionDescriptors/e:ConditionDescriptor", NS):
        n, v = xtext(cd, "e:Name"), xtext(cd, "e:Value")
        if n and v:
            cdesc += f"<ConditionDescriptor><Name>{n}</Name><Value>{v}</Value></ConditionDescriptor>"
    if not cdesc:
        cdesc = "<ConditionDescriptor><Name>40001</Name><Value>400010</Value></ConditionDescriptor>"
    cdesc = f"<ConditionDescriptors>{cdesc}</ConditionDescriptors>"
    pics = [p.text for p in item.findall("e:PictureDetails/e:PictureURL", NS) if p.text]
    specs = ""
    for nvl in item.findall("e:ItemSpecifics/e:NameValueList", NS):
        n = xtext(nvl, "e:Name")
        vals = [v.text for v in nvl.findall("e:Value", NS) if v.text]
        if n and vals:
            specs += ("<NameValueList><Name>%s</Name>%s</NameValueList>"
                      % (ebay_client.xml_escape(n),
                         "".join("<Value>%s</Value>" % ebay_client.xml_escape(v) for v in vals)))
    ship = ""
    sd = item.find("e:ShippingDetails", NS)
    if sd is not None:
        opt = sd.find("e:ShippingServiceOptions", NS)
        if opt is not None:
            svc = xtext(opt, "e:ShippingService") or "USPSGroundAdvantage"
            cost = xtext(opt, "e:ShippingServiceCost") or "0.0"
            ship = (f"<ShippingDetails><ShippingType>Flat</ShippingType>"
                    f"<ShippingServiceOptions><ShippingServicePriority>1</ShippingServicePriority>"
                    f"<ShippingService>{svc}</ShippingService>"
                    f"<ShippingServiceCost>{cost}</ShippingServiceCost>"
                    f"</ShippingServiceOptions></ShippingDetails>")
    pics_xml = "".join(f"<PictureURL>{ebay_client.xml_escape(p)}</PictureURL>" for p in pics[:12])
    return (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<AddFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<RequesterCredentials><eBayAuthToken>{mike_tok}</eBayAuthToken></RequesterCredentials>'
            f'<Item>'
            f'<Title>{ebay_client.xml_escape(title)}</Title>'
            f'<Description><![CDATA[{desc}]]></Description>'
            f'<PrimaryCategory><CategoryID>{cat}</CategoryID></PrimaryCategory>'
            f'<StartPrice>{price}</StartPrice>'
            f'<ConditionID>{cond}</ConditionID>'
            f'{cdesc}'
            f'<Country>US</Country><Currency>USD</Currency>'
            f'<DispatchTimeMax>3</DispatchTimeMax>'
            f'<ListingDuration>GTC</ListingDuration>'
            f'<ListingType>FixedPriceItem</ListingType>'
            f'<Location>Wynnewood, PA</Location><PostalCode>19096</PostalCode>'
            f'<PictureDetails>{pics_xml}</PictureDetails>'
            f'<Quantity>1</Quantity>'
            f'<ItemSpecifics>{specs}</ItemSpecifics>'
            f'{ship}'
            f'<ReturnPolicy><ReturnsAcceptedOption>ReturnsNotAccepted</ReturnsAcceptedOption></ReturnPolicy>'
            f'</Item></AddFixedPriceItemRequest>')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--top", type=int, default=10, help="take top N by price")
    ap.add_argument("--ids", nargs="*", help="explicit source item ids instead of --top")
    a = ap.parse_args()

    cfg = json.loads(Path("configuration.json").read_text())
    jc_tok = ebay_client.get_write_token(cfg)
    cand = json.load(open(CAND))
    if a.ids:
        pick = [e for e in cand if str(e["item_id"]) in set(a.ids)]
    else:
        pick = sorted(cand, key=lambda e: -float(e["price"]))[:a.top]

    total = sum(float(e["price"]) for e in pick)
    print(f"batch: {len(pick)} cards, ${total:.2f} total (new-account limit is usually 10 items / $500 a month)")

    mike_tok = env_token() if a.apply else None
    log = json.load(open(LOG)) if LOG.exists() else []
    done = {e["source_item_id"] for e in log}
    ok = err = 0
    for e in pick:
        iid = str(e["item_id"])
        if iid in done:
            print(f"  SKIP {iid} already transferred"); continue
        item, msg = get_item(iid, cfg, jc_tok)
        if item is None:
            print(f"  FAIL {iid} GetItem: {msg}"); err += 1; continue
        pics = len(item.findall("e:PictureDetails/e:PictureURL", NS))
        print(f'  ${float(e["price"]):>6.2f}  {pics} pics  {iid}  {e["title"][:56]}')
        if not a.apply:
            continue
        body = build_add_xml(item, e["price"], mike_tok)
        # Mike's token is Auth'n'Auth (in the XML body), not OAuth — no IAF header
        h = ebay_client.trading_headers("AddFixedPriceItem", cfg, mike_tok)
        h.pop("X-EBAY-API-IAF-TOKEN", None)
        r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=90)
        ack = ebay_client.find_tag(r.text, "Ack") or "?"
        new_id = ebay_client.find_tag(r.text, "ItemID")
        if ack in ("Success", "Warning") and new_id:
            ok += 1
            print(f"         -> LIVE on mikeboy-40 as {new_id}")
            log.append({"source_item_id": iid, "mike_item_id": new_id,
                        "title": e["title"], "price": e["price"]})
        else:
            err += 1
            print(f"         -> FAIL: {ebay_client.find_tag(r.text, 'LongMessage')}")
    if a.apply:
        LOG.write_text(json.dumps(log, indent=1))
        print(f"\n=== transferred {ok} · failed {err} · log {LOG} ===")
    else:
        print("\nDRY-RUN. --apply posts these to Mike's live account.")


if __name__ == "__main__":
    main()
