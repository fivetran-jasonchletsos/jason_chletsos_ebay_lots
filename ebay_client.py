"""Low-level eBay Trading API helpers.

Before: push_to_ebay.py owned OAuth, headers, XML helpers, and the AddItem
CLI. end_listing.py imported the low-level pieces from push_to_ebay.py, which
is a CLI script — the import worked but mixed concerns badly. New callers
(refresh_snapshot.py, future Trading API tooling) had to do the same.

After: this module owns the shared primitives. push_to_ebay.py keeps the
AddItem CLI and imports from here. end_listing.py and refresh_snapshot.py
import directly from here, no longer touching push_to_ebay.

Public surface:
    CONFIG           — path to configuration.json (from paths.CONFIG)
    TRADING_URL      — eBay Trading API endpoint
    OAUTH_URL        — eBay OAuth token endpoint
    NS               — eBay XML namespace
    COMPAT_LEVEL     — Trading API compatibility level
    SITE_ID_US       — eBay site ID for US
    WRITE_SCOPES     — OAuth scope list for write-capable Trading API calls

    xml_escape(s)        — XML-safe string
    find_tag(xml, tag)   — first occurrence of <tag>...</tag>
    find_all(xml, tag)   — every occurrence
    get_write_token(cfg) — OAuth refresh-token grant
    trading_headers(call_name, cfg, access_token) — HTTP headers for Trading
"""
from __future__ import annotations
import base64
import re

import requests

import paths

# Re-export for callers that used to import CONFIG from push_to_ebay.
CONFIG = paths.CONFIG

# eBay endpoints + protocol constants
TRADING_URL  = paths.TRADING_URL
OAUTH_URL    = "https://api.ebay.com/identity/v1/oauth2/token"
COMPAT_LEVEL = "967"
SITE_ID_US   = "0"
NS           = "urn:ebay:apis:eBLBaseComponents"

# Write scopes. Mirrors mobile/src/api/ebay.ts:28.
WRITE_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope",
    "https://api.ebay.com/oauth/api_scope/sell.inventory",
    "https://api.ebay.com/oauth/api_scope/sell.account",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment",
    "https://api.ebay.com/oauth/api_scope/sell.marketing",
])


# --------------------------------------------------------------------------- #
# XML helpers                                                                 #
# --------------------------------------------------------------------------- #

def xml_escape(s) -> str:
    """XML-safe string. Handles all five XML entity references."""
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def find_tag(xml: str, tag: str) -> str | None:
    """Return text contents of the first <tag>...</tag> in xml, or None."""
    m = re.search(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)
    return m.group(1).strip() if m else None


def find_all(xml: str, tag: str) -> list[str]:
    """Return text contents of every <tag>...</tag> in xml."""
    return [m.group(1).strip()
            for m in re.finditer(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", xml, re.IGNORECASE)]


# --------------------------------------------------------------------------- #
# OAuth + Trading API headers                                                 #
# --------------------------------------------------------------------------- #

def get_write_token(cfg: dict) -> str:
    """OAuth refresh-token grant returning a write-scoped access token."""
    basic = base64.b64encode(f"{cfg['client_id']}:{cfg['client_secret']}".encode()).decode()
    r = requests.post(OAUTH_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "refresh_token", "refresh_token": cfg["refresh_token"], "scope": WRITE_SCOPES},
        timeout=30,
    )
    if not r.ok:
        raise SystemExit(f"OAuth failed ({r.status_code}): {r.text[:400]}")
    return r.json()["access_token"]


def trading_headers(call_name: str, cfg: dict, access_token: str) -> dict:
    """HTTP headers for an XML Trading API call. `call_name` is the API verb
    (e.g. 'AddItem', 'EndFixedPriceItem', 'GetMyeBaySelling')."""
    return {
        "X-EBAY-API-SITEID":              SITE_ID_US,
        "X-EBAY-API-COMPATIBILITY-LEVEL": COMPAT_LEVEL,
        "X-EBAY-API-CALL-NAME":           call_name,
        "X-EBAY-API-APP-NAME":            cfg["client_id"],
        "X-EBAY-API-DEV-NAME":            cfg.get("dev_id", ""),
        "X-EBAY-API-CERT-NAME":           cfg["client_secret"],
        "X-EBAY-API-IAF-TOKEN":           access_token,
        "Content-Type":                   "text/xml",
    }
