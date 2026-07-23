"""One-off fix: JC confirmed the 'Fortune 15' card is Mike Trout only (no
Ohtani) -- correct the title. He also can't locate the physical Giancarlo
Stanton holiday card -- end that listing (never had the card in hand to ship).
Dry-run default; --apply to push.
"""
import argparse, json
from pathlib import Path
import ebay_client, requests

TROUT_ID = "307080371915"
TROUT_OLD_TITLE = "2025 Topps Chrome Mike Trout Shohei Ohtani Fortune 15 Angels"
TROUT_NEW_TITLE = "2025 Topps Chrome Mike Trout Fortune 15 Insert Angels Baseball"

STANTON_ID = "307080372034"

def revise_title(iid, title, cfg, tok):
    body = (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<ReviseItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
            f'<Item><ItemID>{iid}</ItemID><Title>{ebay_client.xml_escape(title)}</Title></Item>'
            f'</ReviseItemRequest>')
    h = ebay_client.trading_headers("ReviseItem", cfg, tok)
    r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
    ack = ebay_client.find_tag(r.text, "Ack") or "?"
    return ack, (ebay_client.find_tag(r.text, "LongMessage") or r.text[:300])

def end_item(iid, cfg, tok):
    body = (f'<?xml version="1.0" encoding="utf-8"?>'
            f'<EndFixedPriceItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">'
            f'<RequesterCredentials><eBayAuthToken>{tok}</eBayAuthToken></RequesterCredentials>'
            f'<ItemID>{iid}</ItemID><EndingReason>NotAvailable</EndingReason>'
            f'</EndFixedPriceItemRequest>')
    h = ebay_client.trading_headers("EndFixedPriceItem", cfg, tok)
    r = requests.post(ebay_client.TRADING_URL, data=body.encode(), headers=h, timeout=60)
    ack = ebay_client.find_tag(r.text, "Ack") or "?"
    return ack, (ebay_client.find_tag(r.text, "LongMessage") or r.text[:300])

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--apply", action="store_true"); a = ap.parse_args()
    cfg = json.loads(Path("configuration.json").read_text())
    tok = ebay_client.get_write_token(cfg)

    print(f"Trout {TROUT_ID}:")
    print(f"  OLD: {TROUT_OLD_TITLE}")
    print(f"  NEW: {TROUT_NEW_TITLE}  ({len(TROUT_NEW_TITLE)} chars)")
    if a.apply:
        ack, msg = revise_title(TROUT_ID, TROUT_NEW_TITLE, cfg, tok)
        print(f"  -> {ack}  {msg if ack not in ('Success','Warning') else ''}")
    else:
        print("  [dry-run] would revise title")

    print(f"\nStanton {STANTON_ID}: card can't be located, ending listing")
    if a.apply:
        ack, msg = end_item(STANTON_ID, cfg, tok)
        print(f"  -> {ack}  {msg if ack not in ('Success','Warning') else ''}")
    else:
        print("  [dry-run] would end listing")

if __name__ == "__main__":
    main()
