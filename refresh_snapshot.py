"""Refresh output/listings_snapshot.json from eBay's GetMyeBaySelling API.

The snapshot is the canonical local view of "what listings are currently
live on eBay." It was previously written only by promote.py as part of the
full site rebuild, which made --full refreshes silently stale: the snapshot
readers (cassini_score, photo_audit, repricing, etc.) ran against whatever
the last manual promote.py left behind.

This script extracts just the snapshot refresh into its own callable step
so refresh_pipeline can run it at the start of CASCADE_FULL.

Atomic write: writes to a .tmp file then os.replace so concurrent readers
in the same cascade can never see a half-written JSON.
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path

REPO   = Path(__file__).parent
CONFIG = REPO / "configuration.json"
SNAP   = REPO / "output" / "listings_snapshot.json"


def main() -> int:
    if not CONFIG.is_file():
        print(f"  ERROR: {CONFIG} missing — cannot fetch snapshot.")
        return 1
    cfg = json.loads(CONFIG.read_text())

    # Reuse push_to_ebay's OAuth helper (Trading API scope works for both
    # AddItem and GetMyeBaySelling).
    from push_to_ebay import get_write_token
    print("  Fetching eBay access token...")
    token = get_write_token(cfg)

    # Lazy-import promote because it's heavy.
    import promote
    print("  Calling GetMyeBaySelling...")
    listings = promote.fetch_listings(token, cfg)
    if not listings:
        print(f"  WARNING: 0 listings returned. Not overwriting existing snapshot.")
        return 1

    # Single atomic write through snapshot_store.
    import snapshot_store
    snapshot_store.replace_all(listings)
    print(f"  Wrote {SNAP} ({len(listings)} listings)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
