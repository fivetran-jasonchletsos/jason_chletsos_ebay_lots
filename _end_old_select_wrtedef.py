"""End the 15 live WR/TE/Defense Select lots that had the old (up-to-6-card)
groupings, so the corrected 5-max lots can be re-posted without duplicates.
QB lots 1-3 and RB lots 4-8 are NOT touched (JC already pulled those).
"""
import json, sys, requests
from pathlib import Path
from ebay_client import TRADING_URL, NS, get_write_token, trading_headers, xml_escape, find_tag

# Old live item IDs for WR#1-7, TE#1-2, Defense#1-6 (from the first apply run).
OLD_IDS = [
    "307039867941", "307039867960", "307039867993", "307039868021",
    "307039868046", "307039868079", "307039868105",   # WR 1-7
    "307039868131", "307039868146",                     # TE 1-2
    "307039868163", "307039868193", "307039868230",
    "307039868247", "307039868262", "307039868284",     # Defense 1-6
]

def main():
    cfg = json.loads(Path("configuration.json").read_text())
    token = get_write_token(cfg)
    ended, failed = 0, 0
    for iid in OLD_IDS:
        xml = f"""<?xml version="1.0" encoding="utf-8"?>
<EndFixedPriceItemRequest xmlns="{NS}">
  <RequesterCredentials><eBayAuthToken>{xml_escape(token)}</eBayAuthToken></RequesterCredentials>
  <ItemID>{iid}</ItemID>
  <EndingReason>OtherListingError</EndingReason>
</EndFixedPriceItemRequest>"""
        r = requests.post(TRADING_URL, headers=trading_headers("EndFixedPriceItem", cfg, token),
                          data=xml.encode("utf-8"), timeout=40)
        ack = find_tag(r.text, "Ack")
        if ack in ("Success", "Warning"):
            print(f"  ENDED ({ack}) {iid}"); ended += 1
        else:
            print(f"  END FAILED ({ack}) {iid}: {r.text[:200]}"); failed += 1
    print(f"\n  {ended} ended, {failed} failed")

if __name__ == "__main__":
    sys.exit(main())
