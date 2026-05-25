#!/usr/bin/env python3
"""finish_oauth.py — one-shot wrapper around oauth_remint_helper.

Run from the repo root:

    python3 finish_oauth.py

It prints the consent URL, waits for you to paste the FULL redirect URL
that eBay lands you on, parses the ?code= out, and exchanges it for a
new refresh token via oauth_remint_helper.py.

No shell quoting. No heredocs. No copy-only-the-code gymnastics.
"""
from __future__ import annotations

import subprocess
import sys
import urllib.parse as urlparse
from pathlib import Path

REPO = Path(__file__).resolve().parent

CONSENT_URL = (
    "https://auth.ebay.com/oauth2/authorize"
    "?client_id=JasonChl-jasonchl-PRD-d8f6186d5-ea3d812b"
    "&response_type=code"
    "&redirect_uri=Jason_Chletsos-JasonChl-jasonc-xignp"
    "&scope=" + "%20".join([
        urlparse.quote(s, safe="")
        for s in [
            "https://api.ebay.com/oauth/api_scope",
            "https://api.ebay.com/oauth/api_scope/sell.inventory",
            "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
            "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.marketing",
            "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.account",
            "https://api.ebay.com/oauth/api_scope/sell.account.readonly",
            "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
            "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
        ]
    ])
    + "&prompt=login"
)


def main() -> int:
    print()
    print("=" * 72)
    print("  eBay OAuth re-mint — one-shot helper")
    print("=" * 72)
    print()
    print("STEP 1 — open this URL in your browser, click Agree:")
    print()
    print("  " + CONSENT_URL)
    print()
    print("STEP 2 — eBay redirects you to:")
    print("    https://fivetran.com/connect/ebay/oauth/callback?code=...")
    print("  Copy the FULL URL from your browser's address bar.")
    print()
    print("STEP 3 — paste it below, then press Enter:")
    print()

    raw = input("URL: ").strip()
    if not raw:
        print("(no input — aborting)")
        return 1

    parsed = urlparse.urlparse(raw)
    qs = urlparse.parse_qs(parsed.query)

    if "error" in qs:
        print(f"\n[ERROR] eBay returned: {qs['error'][0]}")
        if "error_description" in qs:
            print(f"        detail: {qs['error_description'][0]}")
        return 2

    if "code" not in qs:
        print("\n[ERROR] No 'code' parameter found in the URL.")
        print("        Make sure you copied the full URL from after eBay redirected.")
        return 3

    code = qs["code"][0]
    # parse_qs already URL-decoded the code. Pass the decoded form to the helper
    # so it doesn't get double-encoded when requests serializes the form body.
    print(f"\n[ok] Extracted code (len={len(code)}). Exchanging for refresh token...")
    print()

    result = subprocess.run(
        [sys.executable, str(REPO / "oauth_remint_helper.py"), "--paste-code", code],
        cwd=str(REPO),
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
