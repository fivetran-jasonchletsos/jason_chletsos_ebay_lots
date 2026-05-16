"""
eBay Marketplace Account Deletion Notification Handler + OAuth Callback + Title Reviser
=======================================================
AWS Lambda function behind API Gateway.

Routes handled:
  GET  /ebay/notifications?challenge_code=xxx  — eBay ownership verification
  POST /ebay/notifications                     — account deletion notification
  GET  /ebay/oauth/callback?code=xxx           — OAuth authorization code exchange
  POST /ebay/revise                            — revise item titles from title_review.html
  GET  /health                                 — health check

Environment variables:
  EBAY_VERIFICATION_TOKEN   — secret string registered in eBay Developer Portal
  EBAY_ENDPOINT_URL         — full public HTTPS URL of /ebay/notifications
  EBAY_CLIENT_ID            — App ID / Client ID
  EBAY_CLIENT_SECRET        — Cert ID / Client Secret
  EBAY_REFRESH_TOKEN        — OAuth refresh token for Trading API calls
  EBAY_DEV_ID               — eBay Dev ID
  EBAY_RU_NAME              — RuName from eBay Developer Portal
"""

import base64
import hashlib
import json
import logging
import os
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

logger = logging.getLogger()
logger.setLevel(logging.INFO)

VERIFICATION_TOKEN = os.environ.get("EBAY_VERIFICATION_TOKEN", "")
ENDPOINT_URL       = os.environ.get("EBAY_ENDPOINT_URL", "")
CLIENT_ID          = os.environ.get("EBAY_CLIENT_ID", "")
CLIENT_SECRET      = os.environ.get("EBAY_CLIENT_SECRET", "")
REFRESH_TOKEN      = os.environ.get("EBAY_REFRESH_TOKEN", "")
DEV_ID             = os.environ.get("EBAY_DEV_ID", "")
RU_NAME            = os.environ.get("EBAY_RU_NAME", "")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO        = "fivetran-jasonchletsos/jason_chletsos_ebay_lots"
TOKEN_URL          = "https://api.ebay.com/identity/v1/oauth2/token"
TRADING_API_URL    = "https://api.ebay.com/ws/api.dll"
NS_URI             = "urn:ebay:apis:eBLBaseComponents"

# Reddit OAuth — set via Terraform env vars. See README "Reddit posting setup".
REDDIT_CLIENT_ID     = os.environ.get("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = os.environ.get("REDDIT_CLIENT_SECRET", "")
REDDIT_REFRESH_TOKEN = os.environ.get("REDDIT_REFRESH_TOKEN", "")
REDDIT_USER_AGENT    = os.environ.get("REDDIT_USER_AGENT", "harpua2001-crosspost/1.0 by harpua2001")
REDDIT_TOKEN_URL     = "https://www.reddit.com/api/v1/access_token"
REDDIT_SUBMIT_URL    = "https://oauth.reddit.com/api/submit"

# Fivetran (eBay → warehouse sync) — triggered from Refresh button
FIVETRAN_API_KEY      = os.environ.get("FIVETRAN_API_KEY", "")
FIVETRAN_API_SECRET   = os.environ.get("FIVETRAN_API_SECRET", "")
FIVETRAN_CONNECTOR_ID = os.environ.get("FIVETRAN_CONNECTOR_ID", "")

# Admin-login alerting — publishes to SNS when a NEW device/IP unlocks the gate
ADMIN_ALERT_SNS_TOPIC  = os.environ.get("ADMIN_ALERT_SNS_TOPIC", "")
ADMIN_KNOWN_DEVICES    = [d.strip() for d in os.environ.get("ADMIN_KNOWN_DEVICES", "").split(",") if d.strip()]
ADMIN_KNOWN_IP_PREFIXES = [p.strip() for p in os.environ.get("ADMIN_KNOWN_IP_PREFIXES", "").split(",") if p.strip()]


def lambda_handler(event, context):
    method = event.get("httpMethod") or event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path   = event.get("path") or event.get("requestContext", {}).get("http", {}).get("path", "/")
    params = event.get("queryStringParameters") or {}

    logger.info(f"Request: {method} {path} params={list(params.keys())}")

    # ------------------------------------------------------------------
    # GET /health
    # ------------------------------------------------------------------
    if path.endswith("/health"):
        return _response(200, {"status": "ok"})

    # ------------------------------------------------------------------
    # POST /ebay/revise — apply title changes from title_review.html
    # Body: { "items": [{ "item_id": "...", "title": "..." }, ...] }
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/revise"):
        try:
            body  = json.loads(event.get("body") or "{}")
            items = body.get("items", [])
            if not items:
                return _cors_response(400, {"success": False, "error": "No items provided"})

            access_token = _get_access_token()
            updated = 0
            errors  = []

            for it in items:
                item_id   = str(it.get("item_id", "")).strip()
                new_title = str(it.get("title", "")).strip()[:80]
                if not item_id or not new_title:
                    continue

                ok, msg = _revise_item_title(access_token, item_id, new_title)
                if ok:
                    updated += 1
                    logger.info(f"Revised {item_id}: {new_title}")
                else:
                    errors.append({"item_id": item_id, "error": msg})
                    logger.error(f"Failed {item_id}: {msg}")

            return _cors_response(200, {"success": True, "updated": updated, "errors": errors})

        except Exception as exc:
            logger.error(f"Revise error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    # ------------------------------------------------------------------
    # POST /ebay/reprice — update a single listing's price
    # Body: { "item_id": "...", "price": 9.99 }
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/reprice"):
        try:
            body    = json.loads(event.get("body") or "{}")
            item_id = str(body.get("item_id", "")).strip()
            price   = body.get("price")
            if not item_id or price is None:
                return _cors_response(400, {"success": False, "error": "item_id and price required"})
            try:
                price_f = round(float(price), 2)
                if price_f <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return _cors_response(400, {"success": False, "error": "price must be a positive number"})

            access_token = _get_access_token()
            ok, msg = _revise_item_price(access_token, item_id, price_f)
            if ok:
                logger.info(f"Repriced {item_id} to ${price_f:.2f}")
                return _cors_response(200, {"success": True, "item_id": item_id, "price": price_f})
            else:
                logger.error(f"Failed reprice {item_id} to ${price_f:.2f}: {msg}")
                return _cors_response(200, {"success": False, "item_id": item_id, "error": msg})

        except Exception as exc:
            logger.error(f"Reprice error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    # ------------------------------------------------------------------
    # POST /ebay/preview-store-categories — read-only.
    # Imports seller_hub_agent and returns the derived store-category plan.
    # No eBay writes.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/preview-store-categories"):
        try:
            try:
                import seller_hub_agent  # type: ignore
            except Exception as imp_exc:
                logger.error(f"seller_hub_agent import failed: {imp_exc}")
                return _cors_response(503, {
                    "success": False,
                    "error":   f"seller_hub_agent module not available: {imp_exc}",
                })

            plan = seller_hub_agent.build_plan()
            logger.info(f"preview-store-categories: plan built (type={type(plan).__name__})")
            return _cors_response(200, {"success": True, "plan": plan})

        except Exception as exc:
            logger.error(f"preview-store-categories error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/preview-store-categories"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/sync-store-categories — gated behind dry_run flag.
    # Body: {"dry_run": true|false}
    # Dry-run: returns the plan + "would set N categories."
    # Live:    imports seller_hub_phase2 and applies the plan via eBay.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/sync-store-categories"):
        try:
            body    = json.loads(event.get("body") or "{}")
            dry_run = bool(body.get("dry_run", True))

            try:
                import seller_hub_agent  # type: ignore
            except Exception as imp_exc:
                logger.error(f"seller_hub_agent import failed: {imp_exc}")
                return _cors_response(503, {
                    "success": False,
                    "error":   f"seller_hub_agent module not available: {imp_exc}",
                })

            plan = seller_hub_agent.build_plan()
            # Count categories in the plan (support dict / list shapes).
            if isinstance(plan, dict):
                count = len(plan.get("categories", plan))
            elif isinstance(plan, list):
                count = len(plan)
            else:
                count = 0

            if dry_run:
                logger.info(f"sync-store-categories DRY-RUN: would set {count} categories")
                return _cors_response(200, {
                    "success": True,
                    "dry_run": True,
                    "plan":    plan,
                    "message": f"would set {count} categories.",
                })

            # Live mode — requires seller_hub_phase2 (Agent A's module).
            try:
                import seller_hub_phase2  # type: ignore
            except Exception as imp_exc:
                logger.error(f"seller_hub_phase2 import failed: {imp_exc}")
                return _cors_response(503, {
                    "success": False,
                    "error":   f"seller_hub_phase2 module not available yet (Agent A still building): {imp_exc}",
                })

            try:
                access_token = _get_access_token()
                sync_result = seller_hub_phase2.sync_store_categories(access_token, plan, dry_run=False)
                listings = (plan.get("listings", []) if isinstance(plan, dict) else [])
                mapping  = (plan.get("mapping",  {})  if isinstance(plan, dict) else {})
                assign_result = seller_hub_phase2.assign_items_to_categories(
                    access_token, listings, mapping, dry_run=False,
                )
                logger.info(f"sync-store-categories LIVE: synced {count} categories")
                return _cors_response(200, {
                    "success":       True,
                    "dry_run":       False,
                    "sync_result":   sync_result,
                    "assign_result": assign_result,
                })
            except Exception as live_exc:
                logger.error(f"sync-store-categories live error: {live_exc}")
                return _cors_response(500, {"success": False, "error": str(live_exc)})

        except Exception as exc:
            logger.error(f"sync-store-categories error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/sync-store-categories"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/promotion-rollup — read-only.
    # The two source JSON files (output/promotions_plan.json and
    # output/promoted_listings_plan.json) live in the repo, NOT on the
    # Lambda's filesystem, so the static page POSTs their parsed contents
    # in the request body. We echo them back with a `summary` block:
    # apply_count, total_proposed_discount, etc.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/promotion-rollup"):
        try:
            body = json.loads(event.get("body") or "{}")
            promotions_plan        = body.get("promotions_plan")        or {}
            promoted_listings_plan = body.get("promoted_listings_plan") or {}

            def _iter_items(plan):
                if isinstance(plan, list):
                    return plan
                if isinstance(plan, dict):
                    for key in ("items", "listings", "promotions", "plan"):
                        v = plan.get(key)
                        if isinstance(v, list):
                            return v
                return []

            def _summarize(plan):
                items = _iter_items(plan)
                apply_count = 0
                total_discount = 0.0
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    if str(it.get("decision", "")).lower() == "apply":
                        apply_count += 1
                        for key in ("proposed_discount", "discount", "discount_amount", "discount_value"):
                            v = it.get(key)
                            if v is None:
                                continue
                            try:
                                total_discount += float(v)
                                break
                            except (TypeError, ValueError):
                                pass
                return {
                    "total_items":              len(items),
                    "apply_count":              apply_count,
                    "total_proposed_discount":  round(total_discount, 2),
                }

            summary = {
                "promotions":        _summarize(promotions_plan),
                "promoted_listings": _summarize(promoted_listings_plan),
            }
            summary["apply_count_total"] = (
                summary["promotions"]["apply_count"]
                + summary["promoted_listings"]["apply_count"]
            )
            summary["total_proposed_discount"] = round(
                summary["promotions"]["total_proposed_discount"]
                + summary["promoted_listings"]["total_proposed_discount"],
                2,
            )

            logger.info(
                f"promotion-rollup: apply_total={summary['apply_count_total']} "
                f"discount_total={summary['total_proposed_discount']:.2f}"
            )
            return _cors_response(200, {
                "success":                True,
                "promotions_plan":        promotions_plan,
                "promoted_listings_plan": promoted_listings_plan,
                "summary":                summary,
            })

        except Exception as exc:
            logger.error(f"promotion-rollup error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/promotion-rollup"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/rebuild — trigger GitHub Actions workflow_dispatch
    # Rebuilds the GitHub Pages site with fresh eBay listings
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/rebuild"):
        results = {"fivetran": None, "github": None}

        # 1) Trigger the Fivetran eBay sync first — this populates the warehouse
        if FIVETRAN_API_KEY and FIVETRAN_API_SECRET and FIVETRAN_CONNECTOR_ID:
            try:
                creds = base64.b64encode(f"{FIVETRAN_API_KEY}:{FIVETRAN_API_SECRET}".encode()).decode()
                fv_url = f"https://api.fivetran.com/v1/connectors/{FIVETRAN_CONNECTOR_ID}/force"
                fv_req = urllib.request.Request(
                    fv_url,
                    data=b"",
                    headers={
                        "Authorization": f"Basic {creds}",
                        "Content-Type":  "application/json",
                    },
                    method="POST",
                )
                fv_resp = urllib.request.urlopen(fv_req, timeout=10)
                fv_body = json.loads(fv_resp.read().decode() or "{}")
                results["fivetran"] = {
                    "ok":      fv_body.get("code") == "Success",
                    "message": fv_body.get("message"),
                    "code":    fv_body.get("code"),
                }
                logger.info(f"Fivetran sync triggered: {fv_body.get('code')} — {fv_body.get('message')}")
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode()[:300]
                results["fivetran"] = {"ok": False, "error": f"HTTP {exc.code}: {err_body}"}
                logger.error(f"Fivetran trigger HTTP error: {exc.code} — {err_body}")
            except Exception as exc:
                results["fivetran"] = {"ok": False, "error": str(exc)}
                logger.error(f"Fivetran trigger error: {exc}")
        else:
            results["fivetran"] = {"ok": False, "error": "Fivetran credentials not configured (FIVETRAN_API_KEY / SECRET / CONNECTOR_ID)"}

        # 2) Then trigger the GitHub Actions workflow to rebuild the site
        if not GITHUB_TOKEN:
            results["github"] = {"ok": False, "error": "GITHUB_TOKEN not configured"}
            return _cors_response(500, {"success": False, "error": "GITHUB_TOKEN not configured", "results": results})
        try:
            payload = json.dumps({"ref": "main"}).encode()
            req = urllib.request.Request(
                f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/refresh.yml/dispatches",
                data=payload,
                headers={
                    "Authorization":        f"Bearer {GITHUB_TOKEN}",
                    "Accept":               "application/vnd.github+json",
                    "Content-Type":         "application/json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                method="POST",
            )
            resp = urllib.request.urlopen(req, timeout=10)
            results["github"] = {"ok": True, "status": resp.status}
            logger.info(f"GitHub Actions dispatch triggered, status={resp.status}")
        except Exception as exc:
            results["github"] = {"ok": False, "error": str(exc)}
            logger.error(f"Rebuild trigger error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc), "results": results})

        # Compose a friendly user-facing summary
        msgs = []
        if results["fivetran"] and results["fivetran"].get("ok"):
            msgs.append("Fivetran sync started (warehouse refresh: ~1-3 min)")
        elif results["fivetran"]:
            msgs.append(f"Fivetran skipped: {results['fivetran'].get('error') or results['fivetran'].get('message')}")
        if results["github"] and results["github"].get("ok"):
            msgs.append("Site rebuild triggered (live in ~2 min)")
        return _cors_response(200, {"success": True, "message": " · ".join(msgs), "results": results})

    # ------------------------------------------------------------------
    # POST /ebay/admin-login — log + alert when someone unlocks the admin gate
    # Body: {device_id, user_agent}
    # Lambda compares the source IP + device fingerprint against the trusted
    # allowlists (ADMIN_KNOWN_DEVICES, ADMIN_KNOWN_IP_PREFIXES). If neither
    # matches, publishes an alert to the SNS topic so the owner gets an email.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/admin-login"):
        try:
            body  = json.loads(event.get("body", "{}") or "{}")
            device_id  = (body.get("device_id")  or "")[:64]
            user_agent = (body.get("user_agent") or "")[:200]
            # Source IP from API Gateway HTTP API event context
            req_ctx    = event.get("requestContext", {})
            http_ctx   = req_ctx.get("http", {})
            source_ip  = http_ctx.get("sourceIp") or req_ctx.get("identity", {}).get("sourceIp", "")
            now_iso    = __import__("datetime").datetime.utcnow().isoformat() + "Z"

            # Decide if this is a known device/IP
            is_known_device = bool(device_id) and device_id in ADMIN_KNOWN_DEVICES
            is_known_ip     = any(source_ip.startswith(p) for p in ADMIN_KNOWN_IP_PREFIXES) if source_ip else False
            trusted = is_known_device or is_known_ip
            logger.info(f"Admin login: ip={source_ip} device={device_id[:8]}... ua={user_agent[:60]}... trusted={trusted}")

            if trusted:
                return _cors_response(200, {"success": True, "trusted": True})

            # Publish SNS alert (best effort — failures don't break the login)
            published = False
            if ADMIN_ALERT_SNS_TOPIC:
                try:
                    # Tiny inline boto3 — Lambda has boto3 pre-installed
                    import boto3
                    sns = boto3.client("sns")
                    msg = (
                        f"⚠ NEW ADMIN LOGIN to Harpua2001 site\n\n"
                        f"Time:       {now_iso} UTC\n"
                        f"Source IP:  {source_ip or 'unknown'}\n"
                        f"Device ID:  {device_id or '(none)'}\n"
                        f"User-Agent: {user_agent or '(none)'}\n\n"
                        f"If this was you, add to ADMIN_KNOWN_DEVICES or ADMIN_KNOWN_IP_PREFIXES on the Lambda to silence future alerts.\n\n"
                        f"If NOT you, rotate the password in admin.json + run promote.py to invalidate the salt."
                    )
                    sns.publish(
                        TopicArn=ADMIN_ALERT_SNS_TOPIC,
                        Subject="Harpua2001 site — new admin login",
                        Message=msg,
                    )
                    published = True
                except Exception as exc:
                    logger.error(f"SNS publish failed: {exc}")
            return _cors_response(200, {"success": True, "trusted": False, "alerted": published})

        except Exception as exc:
            logger.error(f"Admin-login alert error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/admin-login"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/reddit-post — submit a self-post to a chosen subreddit
    # Body: {item_id, subreddit, title, body}
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/reddit-post"):
        if not (REDDIT_CLIENT_ID and REDDIT_CLIENT_SECRET and REDDIT_REFRESH_TOKEN):
            return _cors_response(503, {"success": False, "error": "Reddit Lambda not deployed yet — credentials missing. See README setup."})
        try:
            body = json.loads(event.get("body", "{}") or "{}")
            subreddit = (body.get("subreddit") or "").strip()
            title     = (body.get("title")     or "").strip()
            text      = (body.get("body")      or "").strip()

            if not (subreddit and title and text):
                return _cors_response(400, {"success": False, "error": "subreddit, title, and body are required"})
            if len(title) > 300:
                return _cors_response(400, {"success": False, "error": "title exceeds Reddit 300-char limit"})

            ok, result = _reddit_submit(subreddit, title, text)
            if ok:
                return _cors_response(200, {"success": True, "url": result})
            return _cors_response(502, {"success": False, "error": result})

        except Exception as exc:
            logger.error(f"Reddit post error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/reddit-post"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # GET /ebay/oauth/callback
    # ------------------------------------------------------------------
    if path.endswith("/ebay/oauth/callback"):
        error = params.get("error", "")
        if error:
            desc = params.get("error_description", "unknown error")
            logger.error(f"OAuth declined: {error} — {desc}")
            return _html_response(400, f"""
                <h2>Authorization Declined</h2>
                <p><b>Error:</b> {error}</p>
                <p>{desc}</p>
            """)

        auth_code = params.get("code", "")
        if not auth_code:
            return _html_response(400, "<h2>Missing authorization code</h2>")

        try:
            token_data    = _exchange_code_for_token(auth_code)
            refresh_token = token_data.get("refresh_token", "NOT_RETURNED")
            access_token  = token_data.get("access_token", "")
            expires_in    = token_data.get("refresh_token_expires_in", "unknown")
            logger.info(f"OAuth success — refresh_token obtained, expires_in={expires_in}s")
            return _html_response(200, f"""
                <h2 style="color:green">Authorization Successful</h2>
                <p>Copy your <b>Refresh Token</b> and paste it into configuration.json</p>
                <hr>
                <p><b>Refresh Token</b> (valid ~18 months):</p>
                <textarea rows="6" cols="80" onclick="this.select()"
                  style="font-family:monospace;font-size:12px;word-break:break-all">{refresh_token}</textarea>
                <hr>
                <p style="color:grey;font-size:12px">
                  expires_in: {expires_in} seconds &nbsp;|&nbsp;
                  access_token prefix: {access_token[:20]}...
                </p>
            """)
        except Exception as exc:
            logger.error(f"Token exchange failed: {exc}")
            return _html_response(500, f"<h2>Token exchange failed</h2><pre>{exc}</pre>")

    # ------------------------------------------------------------------
    # GET /ebay/notifications — eBay challenge/verification handshake
    # ------------------------------------------------------------------
    if method == "GET" and path.endswith("/ebay/notifications"):
        challenge_code = params.get("challenge_code", "")
        if not challenge_code:
            return _response(400, {"error": "missing challenge_code"})
        hash_input         = challenge_code + VERIFICATION_TOKEN + ENDPOINT_URL
        challenge_response = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
        logger.info(f"Challenge verification — code prefix: {challenge_code[:8]}...")
        return _response(200, {"challengeResponse": challenge_response})

    # ------------------------------------------------------------------
    # POST /ebay/notifications — account deletion notification
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/notifications"):
        try:
            body     = json.loads(event.get("body") or "{}")
            meta     = body.get("metadata", {})
            notif    = body.get("notification", {})
            data     = notif.get("data", {})
            topic    = meta.get("topic", "UNKNOWN")
            username = data.get("username", "UNKNOWN")
            user_id  = data.get("userId", "UNKNOWN")
            logger.info(f"Account deletion | topic={topic} | username={username} | userId={user_id}")
        except Exception as exc:
            logger.error(f"Error parsing notification: {exc}")
        return _response(200, {"status": "received"})

    # ------------------------------------------------------------------
    # OPTIONS — CORS preflight for browser requests from GitHub Pages
    # ------------------------------------------------------------------
    if method == "OPTIONS":
        return _cors_preflight()

    return _response(405, {"error": "method not allowed", "path": path, "method": method})


# ---------------------------------------------------------------------------
# eBay Trading API helpers
# ---------------------------------------------------------------------------

def _get_access_token() -> str:
    credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    payload = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": REFRESH_TOKEN,
        "scope":         "https://api.ebay.com/oauth/api_scope/sell.inventory",
    }).encode()
    req  = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type":  "application/x-www-form-urlencoded"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode())["access_token"]


def _revise_item_title(access_token: str, item_id: str, new_title: str):
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS_URI}">
  <RequesterCredentials><eBayAuthToken>{access_token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <Title>{new_title}</Title>
  </Item>
</ReviseItemRequest>"""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "ReviseItem",
        "X-EBAY-API-APP-NAME":            CLIENT_ID,
        "X-EBAY-API-DEV-NAME":            DEV_ID,
        "X-EBAY-API-CERT-NAME":           CLIENT_SECRET,
        "Content-Type":                   "text/xml",
    }
    req  = urllib.request.Request(TRADING_API_URL, data=xml_body.encode(), headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=15)
    root = ET.fromstring(resp.read().decode())
    ack  = root.findtext(f"{{{NS_URI}}}Ack", "")
    if ack in ("Success", "Warning"):
        return True, ""
    # Capture every error: code, short, long
    errors = []
    for err in root.findall(f".//{{{NS_URI}}}Errors"):
        code  = err.findtext(f"{{{NS_URI}}}ErrorCode", "?")
        short = err.findtext(f"{{{NS_URI}}}ShortMessage", "")
        long_ = err.findtext(f"{{{NS_URI}}}LongMessage", "")
        errors.append(f"[{code}] {short} :: {long_}")
    msg = " | ".join(errors) if errors else "Unknown error (no Errors node)"
    return False, msg


def _revise_item_price(access_token: str, item_id: str, price: float):
    """Update the BuyItNow price of a fixed-price listing via ReviseItem."""
    xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<ReviseItemRequest xmlns="{NS_URI}">
  <RequesterCredentials><eBayAuthToken>{access_token}</eBayAuthToken></RequesterCredentials>
  <Item>
    <ItemID>{item_id}</ItemID>
    <StartPrice>{price:.2f}</StartPrice>
  </Item>
</ReviseItemRequest>"""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "ReviseItem",
        "X-EBAY-API-APP-NAME":            CLIENT_ID,
        "X-EBAY-API-DEV-NAME":            DEV_ID,
        "X-EBAY-API-CERT-NAME":           CLIENT_SECRET,
        "Content-Type":                   "text/xml",
    }
    req  = urllib.request.Request(TRADING_API_URL, data=xml_body.encode(), headers=headers, method="POST")
    resp = urllib.request.urlopen(req, timeout=15)
    root = ET.fromstring(resp.read().decode())
    ack  = root.findtext(f"{{{NS_URI}}}Ack", "")
    if ack in ("Success", "Warning"):
        return True, ""
    errors = []
    for err in root.findall(f".//{{{NS_URI}}}Errors"):
        code  = err.findtext(f"{{{NS_URI}}}ErrorCode", "?")
        short = err.findtext(f"{{{NS_URI}}}ShortMessage", "")
        long_ = err.findtext(f"{{{NS_URI}}}LongMessage", "")
        errors.append(f"[{code}] {short} :: {long_}")
    msg = " | ".join(errors) if errors else "Unknown error (no Errors node)"
    return False, msg


# ---------------------------------------------------------------------------
# Token exchange helper
# ---------------------------------------------------------------------------
def _exchange_code_for_token(auth_code: str) -> dict:
    credentials = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    payload = urllib.parse.urlencode({
        "grant_type":   "authorization_code",
        "code":         auth_code,
        "redirect_uri": f"https://{ENDPOINT_URL.split('/')[2]}/ebay/oauth/callback",
    }).encode()
    req  = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Authorization": f"Basic {credentials}",
                 "Content-Type":  "application/x-www-form-urlencoded"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=15)
    return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Reddit posting (refresh-token OAuth → submit self post)
# ---------------------------------------------------------------------------
def _reddit_access_token() -> str:
    creds = base64.b64encode(f"{REDDIT_CLIENT_ID}:{REDDIT_CLIENT_SECRET}".encode()).decode()
    payload = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": REDDIT_REFRESH_TOKEN,
    }).encode()
    req = urllib.request.Request(
        REDDIT_TOKEN_URL,
        data=payload,
        headers={
            "Authorization": f"Basic {creds}",
            "Content-Type":  "application/x-www-form-urlencoded",
            "User-Agent":    REDDIT_USER_AGENT,
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode())
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"reddit token error: {data}")
    return token


def _reddit_submit(subreddit: str, title: str, text: str):
    """Submit a Reddit self post. Returns (ok, url_or_error)."""
    try:
        token = _reddit_access_token()
    except Exception as exc:
        return False, f"reddit auth: {exc}"

    payload = urllib.parse.urlencode({
        "sr":           subreddit,
        "kind":         "self",
        "title":        title,
        "text":         text,
        "api_type":     "json",
        "sendreplies":  "true",
        "resubmit":     "true",
    }).encode()
    req = urllib.request.Request(
        REDDIT_SUBMIT_URL,
        data=payload,
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type":  "application/x-www-form-urlencoded",
            "User-Agent":    REDDIT_USER_AGENT,
        },
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=20)
        body = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return False, f"reddit http {exc.code}: {exc.read().decode()[:200]}"

    json_node = body.get("json", {})
    errors    = json_node.get("errors") or []
    if errors:
        return False, "; ".join(f"{e[0]}: {e[1]}" for e in errors[:3])
    url = json_node.get("data", {}).get("url")
    return (True, url) if url else (False, f"unexpected response: {json.dumps(body)[:300]}")


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "https://fivetran-jasonchletsos.github.io",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body),
    }

def _cors_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json", **_CORS_HEADERS},
        "body":       json.dumps(body),
    }

def _cors_preflight() -> dict:
    return {
        "statusCode": 200,
        "headers":    _CORS_HEADERS,
        "body":       "",
    }

def _html_response(status_code: int, html: str) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "text/html"},
        "body":       f"<html><body style='font-family:sans-serif;padding:40px'>{html}</body></html>",
    }
