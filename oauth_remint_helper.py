#!/usr/bin/env python3
"""
oauth_remint_helper.py
======================

Helper for re-minting an eBay user refresh token with the full scope list
that the agents in this repo require (in particular `sell.negotiation`,
needed by watchers_offer_agent.py --apply).

Usage
-----
  # Print consent URL + instructions, after first sanity-checking the
  # current refresh_token against the scopes we actually need:
  python3 oauth_remint_helper.py

  # If you copied an auth code from the Lambda callback page, exchange
  # it for a refresh token without hitting the Lambda:
  python3 oauth_remint_helper.py --paste-code <AUTH_CODE>

The script only reads configuration.json — it never mutates it.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

CONFIG_PATH = Path(__file__).resolve().parent / "configuration.json"

CONSENT_BASE = "https://auth.ebay.com/oauth2/authorize"
TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"

# Full scope list spanning every agent in this repo. `sell.negotiation`
# is the scope the existing refresh_token is missing.
SCOPES: list[str] = [
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
    "https://api.ebay.com/oauth/api_scope/sell.negotiation",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
]


def _load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        print(f"ERROR: {CONFIG_PATH} not found.", file=sys.stderr)
        sys.exit(2)
    try:
        return json.loads(CONFIG_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"ERROR: {CONFIG_PATH} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)


def _require_client_id(cfg: dict[str, Any]) -> str:
    cid = cfg.get("client_id")
    if not cid:
        print("ERROR: configuration.json is missing 'client_id'.", file=sys.stderr)
        sys.exit(2)
    return str(cid)


def _resolve_ru_name(cfg: dict[str, Any]) -> str:
    """
    eBay RuName (redirect URI alias).  Look for any of the common keys.
    If not found, list what we *do* have and prompt the user to add one.
    """
    for key in ("ru_name", "ruName", "RuName", "redirect_uri", "ebay_ru_name"):
        v = cfg.get(key)
        if v:
            return str(v)

    print("ERROR: configuration.json does not contain a RuName.", file=sys.stderr)
    print("       Keys present:", sorted(cfg.keys()), file=sys.stderr)
    print(
        "\nAdd a 'ru_name' field to configuration.json with the RuName from\n"
        "https://developer.ebay.com/my/keys (the value looks like\n"
        "  Jason_Chletsos-JasonChl-jasonc-xxxxxxxxx ).\n"
        "It must match the redirect URI registered for your app — the same\n"
        "RuName that points to your Lambda /ebay/oauth/callback route.",
        file=sys.stderr,
    )
    sys.exit(2)


def build_consent_url(client_id: str, ru_name: str) -> str:
    qs = urllib.parse.urlencode(
        {
            "client_id":     client_id,
            "response_type": "code",
            "redirect_uri":  ru_name,
            "scope":         " ".join(SCOPES),
            "prompt":        "login",
        },
        quote_via=urllib.parse.quote,
    )
    return f"{CONSENT_BASE}?{qs}"


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def sanity_check_existing_token(cfg: dict[str, Any]) -> tuple[bool, str]:
    """
    Try to mint a *user* access token from the stored refresh_token
    requesting the FULL scope list (including sell.negotiation).
    If eBay returns 200 with the negotiation scope in the response,
    the existing token is fine.  Otherwise we report why.
    """
    refresh_token = cfg.get("refresh_token")
    client_id = cfg.get("client_id")
    client_secret = cfg.get("client_secret")
    if not (refresh_token and client_id and client_secret):
        return False, "missing refresh_token / client_id / client_secret in config"

    payload = urllib.parse.urlencode(
        {
            "grant_type":    "refresh_token",
            "refresh_token": refresh_token,
            "scope":         " ".join(SCOPES),
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Authorization": _basic_auth_header(str(client_id), str(client_secret)),
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode()[:300]
        except Exception:
            detail = ""
        return False, f"HTTP {exc.code} from /oauth2/token — {detail}"
    except Exception as exc:
        return False, f"network/error: {exc}"

    granted = body.get("scope", "") or ""
    if "sell.negotiation" in granted:
        return True, "refresh_token already covers sell.negotiation — no re-mint needed"
    return False, (
        "refresh_token minted ok but scope list does NOT include sell.negotiation. "
        f"granted={granted!r}"
    )


def exchange_paste_code(cfg: dict[str, Any], auth_code: str) -> None:
    client_id = _require_client_id(cfg)
    client_secret = cfg.get("client_secret")
    ru_name = _resolve_ru_name(cfg)
    if not client_secret:
        print("ERROR: configuration.json missing 'client_secret'.", file=sys.stderr)
        sys.exit(2)

    payload = urllib.parse.urlencode(
        {
            "grant_type":   "authorization_code",
            "code":         auth_code,
            "redirect_uri": ru_name,
        }
    ).encode()
    req = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={
            "Authorization": _basic_auth_header(client_id, str(client_secret)),
            "Content-Type":  "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode()[:500]
        except Exception:
            pass
        print(f"ERROR: token exchange failed (HTTP {exc.code})\n{body}", file=sys.stderr)
        sys.exit(1)

    new_refresh = data.get("refresh_token")
    if not new_refresh:
        print("ERROR: eBay did not return a refresh_token. Full response:", file=sys.stderr)
        print(json.dumps(data, indent=2), file=sys.stderr)
        sys.exit(1)

    bar = "=" * 72
    expires = data.get("refresh_token_expires_in", "unknown")
    print(
        f"{bar}\nNew refresh token (paste into configuration.json -> 'refresh_token'):\n"
        f"{bar}\n{new_refresh}\n{bar}\n"
        f"refresh_token_expires_in: {expires} seconds  (~18 months typical)\n"
        f"scope: {data.get('scope', '')}"
    )


def print_consent_flow(consent_url: str) -> None:
    bar = "=" * 72
    print(
        f"{bar}\neBay OAuth re-mint — consent URL\n{bar}\n{consent_url}\n\n"
        "Steps:\n"
        "  1. Open the URL above in a browser (signed in as the seller account).\n"
        "  2. When eBay asks, APPROVE all scopes — especially 'Negotiation'.\n"
        "  3. eBay will redirect to your Lambda /ebay/oauth/callback page.\n"
        "     The Lambda displays the new refresh token in a textarea.\n"
        "  4. Copy that refresh token into configuration.json -> 'refresh_token'.\n"
        "  5. Re-run: python3 watchers_offer_agent.py --apply\n\n"
        "Manual fallback: if you have the ?code=... value from the redirect,\n"
        "  python3 oauth_remint_helper.py --paste-code <AUTH_CODE>\n"
        f"{bar}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="eBay OAuth re-mint helper")
    parser.add_argument(
        "--paste-code",
        metavar="AUTH_CODE",
        help="Exchange an eBay authorization code for a new refresh token.",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip the sanity check of the current refresh_token.",
    )
    args = parser.parse_args()

    cfg = _load_config()

    if args.paste_code:
        exchange_paste_code(cfg, args.paste_code.strip())
        return 0

    if not args.skip_check:
        ok, msg = sanity_check_existing_token(cfg)
        print(f"[sanity] {msg}")
        if ok:
            print("Nothing to do — current refresh_token already has the needed scopes.")
            return 0

    client_id = _require_client_id(cfg)
    ru_name = _resolve_ru_name(cfg)
    consent_url = build_consent_url(client_id, ru_name)
    print_consent_flow(consent_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
