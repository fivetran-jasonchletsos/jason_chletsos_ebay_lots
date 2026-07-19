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
import random
import urllib.request
import urllib.parse
import urllib.error
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

# Anthropic vision + optional live pricing for the "Beyond Cards" appraiser
ANTHROPIC_API_KEY_ENV = os.environ.get("ANTHROPIC_API_KEY", "")
PRICECHARTING_API_KEY = os.environ.get("PRICECHARTING_API_KEY", "")
# If set, Claude vision runs through AWS Bedrock (bills the AWS account) instead
# of the Anthropic API key. Set to a Bedrock model / inference-profile id, e.g.
# "us.anthropic.claude-3-5-sonnet-20241022-v2:0".
BEDROCK_MODEL_ID = os.environ.get("BEDROCK_MODEL_ID", "")

# Google Gemini image generation for the "Hero Pulls" Marvel-ify feature —
# redraws a scanned athlete as a wholesome superhero while keeping their
# likeness. Key stays server-side only (never shipped to the browser page).
GEMINI_API_KEY     = os.environ.get("GEMINI_API_KEY", "")
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GEMINI_URL = (f"https://generativelanguage.googleapis.com/v1beta/models/"
              f"{GEMINI_IMAGE_MODEL}:generateContent")


def _run_vision(system, images, instruction, max_tokens=1200):
    """Send image(s) + an instruction to a vision model; return (text, label).

    `images` is a list of (format, raw_bytes) tuples (format in
    jpeg/png/gif/webp). Uses AWS Bedrock's Converse API when BEDROCK_MODEL_ID
    is set (model-agnostic — Amazon Nova, Claude, etc.; auth via the Lambda's
    IAM role, no API key). Falls back to the Anthropic API key otherwise.
    """
    if BEDROCK_MODEL_ID:
        import boto3
        client = boto3.client("bedrock-runtime")
        content = [{"image": {"format": fmt, "source": {"bytes": raw}}}
                   for (fmt, raw) in images]
        content.append({"text": instruction})
        resp = client.converse(
            modelId=BEDROCK_MODEL_ID,
            system=[{"text": system}],
            messages=[{"role": "user", "content": content}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
        )
        blocks = resp.get("output", {}).get("message", {}).get("content", [])
        text = "".join(b.get("text", "") for b in blocks
                       if isinstance(b, dict) and "text" in b).strip()
        return text, f"bedrock:{BEDROCK_MODEL_ID}"

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("no BEDROCK_MODEL_ID and no ANTHROPIC_API_KEY configured")
    a_content = [{"type": "image", "source": {
        "type": "base64", "media_type": f"image/{fmt}",
        "data": base64.b64encode(raw).decode()}} for (fmt, raw) in images]
    a_content.append({"type": "text", "text": instruction})
    payload = json.dumps({
        "model":      "claude-sonnet-4-6",
        "max_tokens": max_tokens,
        "system":     system,
        "messages":   [{"role": "user", "content": a_content}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "x-api-key":         api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type":      "application/json",
        },
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=50)
    data = json.loads(resp.read().decode())
    text = "".join(
        b.get("text", "") for b in data.get("content", [])
        if isinstance(b, dict) and b.get("type") == "text"
    ).strip()
    return text, data.get("model", "")


# --- Hero Pulls / Marvel-ify --------------------------------------------- #

# Stage 1: Claude vision reads the card and designs a wholesome hero persona.
_MARVELIFY_PERSONA_SYSTEM = (
    "You are a kids'-comic character designer. You are shown a sports trading "
    "card. Identify the athlete and design a WHOLESOME, family-friendly, "
    "Marvel-style superhero version of them for an all-ages trading-card toy.\n"
    "Return ONLY one valid JSON object (no markdown) with exactly these keys:\n"
    '  "is_card"          (true if this is a trading card of a person; false for a plain selfie/face or non-card)\n'
    '  "athlete_name"     (string; "" if unreadable)\n'
    '  "sport"            (string) ,  "position" (string)\n'
    '  "appearance_notes" (ONE sentence: face shape, skin tone, hair, facial hair, '
    "build — the traits to PRESERVE so the hero still looks like this person)\n"
    '  "hero_alias"       (invented wholesome hero name riffing on their sport/team, e.g. "The Gridiron Ghost")\n'
    '  "archetype"        (one of: speedster, powerhouse, tech-armor, elemental, '
    "cosmic, street-vigilante, winged-guardian, shield-sentinel, plasma-gunner, "
    "juggernaut, sorcerer, radiant, beast-form, mutant-brawler)\n"
    '  "powers"           (1-2 wholesome powers, no weapons, no violence)\n'
    '  "costume_colors"   (2-3 colors, prefer their real team colors)\n'
    '  "pose"             (one dynamic, heroic, NON-violent action)\n'
    "Rules: everything strictly G-rated. No weapons, blood, or scary imagery. "
    "If you cannot read a person, set is_card false; still fill the creative "
    "fields generically. Output must be machine-parseable JSON only."
)

# Legendary Marvel artists — one is chosen at random per generation so pulls
# vary in style. Each entry names the artist and the flavor to emulate.
_MARVEL_ARTISTS = [
    "Alex Ross — photorealistic painted gouache realism, cinematic lighting, lifelike rendering",
    "Jim Lee — dynamic, hyper-detailed superhero linework with crisp inks and bold energy",
    "Todd McFarlane — intricate, dramatic, sinewy detail with heavy dynamic shadow",
    "Bill Sienkiewicz — expressive, painterly, textured mixed-media intensity",
    "Arthur Adams — highly detailed, clean, richly rendered heroic figures",
    "Frank Miller — bold high-contrast noir with strong silhouettes",
    "Gabriele Dell'Otto — painted photorealistic cinematic Marvel cover art",
    "Marc Silvestri — sharp, dynamic anatomy with fine detailed rendering",
    "David Finch — gritty, muscular, deeply rendered modern superhero style",
    "Esad Ribic — painterly, epic, atmospheric fine-art comic style",
    "Olivier Coipel — dynamic, elegant, heroic modern Marvel style",
    "Steve McNiven — clean, detailed, realistic blockbuster comic art",
]

# Stage 2: built from the persona JSON + the ORIGINAL photo, sent to Gemini.
# {art_style} is a randomly-chosen legendary Marvel artist to emulate.
_MARVELIFY_IMAGE_TMPL = (
    "Transform the athlete IN THE PROVIDED PHOTO into a wholesome, kid-friendly "
    "Marvel-style comic superhero, KEEPING THE SAME PERSON. Preserve their exact "
    "face, {appearance_notes}. It must be instantly recognizable as the same "
    "individual — do not change their face, skin tone, ethnicity, hair, or body "
    "type, and do not change their apparent age.\n"
    'Redraw them as "{hero_alias}", a {archetype} hero, wearing a heroic, fully-'
    "covered superhero costume in {costume_colors}. Show them {pose}, using their "
    "power of {powers}. Keep the face visible (no full mask).\n"
    "ART STYLE: render in the dramatic, professional style of {art_style}. "
    "Museum-quality Marvel comic-book cover art — masterful anatomy, rich dramatic "
    "lighting, deep rendering and detail, a dynamic action background with subtle "
    "motion and glow. Vertical PORTRAIT trading-card orientation, full-bleed, a "
    "single subject centered, framed head-to-mid-thigh.\n"
    "STRICT: keep the exact same person's likeness; family-friendly and G-rated "
    "only; no weapons, no blood, no gore, no scary or violent imagery, no "
    "realistic firearms, fully clothed and dignified. Do NOT add any text, "
    "letters, numbers, logos, signatures, borders, or watermarks anywhere in the "
    "image. One single character only."
)


def _gemini_image(prompt, img_fmt, img_raw, timeout=30):
    """Identity-preserving hero restyle via Gemini 2.5 Flash Image.

    Returns (out_mime, out_b64, block_reason). On success block_reason is None;
    on a soft failure (safety block / no image) out_b64 is None and block_reason
    carries the cause for logging.
    """
    mime = "jpeg" if img_fmt in ("jpg", "jpeg") else img_fmt
    payload = json.dumps({
        "contents": [{
            "role": "user",
            "parts": [
                {"inline_data": {"mime_type": f"image/{mime}",
                                 "data": base64.b64encode(img_raw).decode()}},
                {"text": prompt},
            ],
        }],
        "generationConfig": {"responseModalities": ["IMAGE"], "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(
        GEMINI_URL, data=payload,
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read().decode())
    cands = data.get("candidates") or []
    if not cands:
        return None, None, (data.get("promptFeedback") or {}).get("blockReason", "no_candidates")
    cand = cands[0]
    for part in cand.get("content", {}).get("parts", []):
        inl = part.get("inlineData") or part.get("inline_data")
        if inl and inl.get("data"):
            return inl.get("mimeType", "image/png"), inl["data"], None
    return None, None, cand.get("finishReason", "no_image")


def _extract_json(text):
    """Pull the first JSON object out of a model reply (handles ``` fences)."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```"):
        parts = t.split("```")
        if len(parts) >= 2:
            t = parts[1]
        if t.lstrip().lower().startswith("json"):
            t = t.lstrip()[4:]
    try:
        return json.loads(t)
    except Exception:
        pass
    start, end = t.find("{"), t.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(t[start:end + 1])
        except Exception:
            return None
    return None


def _scp_comp(title, token):
    """Best-effort live SportsCardsPro raw/graded comp. Returns dict or None."""
    if not (title and token):
        return None
    ua = {"User-Agent": "beyond-cards/1.0"}
    try:
        q = urllib.parse.quote(title[:120])
        surl = f"https://www.sportscardspro.com/api/products?t={urllib.parse.quote(token)}&q={q}"
        with urllib.request.urlopen(urllib.request.Request(surl, headers=ua), timeout=12) as r:
            d = json.loads(r.read().decode())
        if d.get("status") != "success":
            return None
        products = d.get("products") or []
        if not products:
            return None
        pid = products[0].get("id")
        if not pid:
            return None
        purl = f"https://www.sportscardspro.com/api/product?t={urllib.parse.quote(token)}&id={urllib.parse.quote(str(pid))}"
        with urllib.request.urlopen(urllib.request.Request(purl, headers=ua), timeout=12) as r:
            p = json.loads(r.read().decode())
        if p.get("status") != "success":
            return None

        def cents(v):
            return round(v / 100.0, 2) if isinstance(v, (int, float)) and v > 0 else None

        return {
            "product": p.get("product-name") or products[0].get("product-name") or "",
            "raw":     cents(p.get("loose-price")),
            "psa9":    cents(p.get("graded-price")),
            "psa10":   cents(p.get("manual-only-price")),
            "url":     f"https://www.sportscardspro.com/game/sportscardspro/{pid}",
            "source":  "SportsCardsPro",
        }
    except Exception as exc:
        logger.info(f"scp_comp failed: {exc}")
        return None


_BEYOND_SYSTEM_PROMPT = (
    "You are the appraiser behind \"Beyond Cards\", a public tool by the eBay seller "
    "harpua2001 that identifies a trading card from a phone photo and drafts an eBay "
    "listing. You are an expert in modern and vintage sports cards (Panini "
    "Prizm/Select/Optic/Mosaic/Donruss, Topps Chrome/Bowman/Signature Class, Upper "
    "Deck) and Pokemon TCG.\n\n"
    "Look at the photo(s) — a front, and optionally a back — identify the card, then "
    "produce an eBay listing and a realistic value estimate for a RAW (ungraded) copy "
    "in the condition shown, unless it is clearly in a graded slab (PSA/BGS/CGC/SGC), "
    "in which case price for that grade.\n\n"
    "Return ONLY a single valid JSON object (no markdown, no prose, no comments, no "
    "trailing commas) with exactly these keys: is_card (boolean; false if the image is "
    "not a trading card), category (\"sports\"|\"pokemon\"|\"other\"), sport, player "
    "(player or character name), team, year, brand, set_name, parallel, card_number, "
    "serial (only if a serial number is visibly printed, e.g. \"26/249\", else \"\"), "
    "is_rookie (boolean), is_auto (boolean), is_relic (boolean), condition_notes "
    "(brief, only what is visible), ebay_title (<=80 characters, keyword-rich, format: "
    "Year Brand Set Player Parallel #Number RC/Auto/Serial Team Sport), "
    "ebay_description (2-4 factual sentences, plain text), estimated_value_usd (object "
    "with numeric low, typical, high), value_basis (one short sentence), confidence "
    "(\"low\"|\"medium\"|\"high\").\n\n"
    "Rules: Never invent details you cannot see — if a serial number, autograph, or "
    "rookie logo is not visible, use \"\"/false. Keep ebay_title <= 80 characters and "
    "avoid ALL-CAPS words. Be honest and realistic about value — a common base card may "
    "be $1-5; do not inflate. If is_card is false, still return the JSON with empty "
    "fields. The output must be machine-parseable JSON."
)


def _img_bytes(data_url):
    """Turn a data URL (or bare base64) into (format, raw_bytes).

    format is one of jpeg/png/gif/webp (Converse-API image formats). Returns
    (None, None) if it can't decode.
    """
    if not data_url:
        return None, None
    fmt = "jpeg"
    b64 = data_url
    if data_url.startswith("data:"):
        head, _, b64 = data_url.partition(",")
        if ":" in head and ";" in head:
            mime = head[head.index(":") + 1:head.index(";")]
            if mime.startswith("image/"):
                sub = mime.split("/", 1)[1].lower()
                fmt = {"jpg": "jpeg"}.get(sub, sub)
    try:
        raw = base64.b64decode(b64)
    except Exception:
        return None, None
    if fmt not in ("jpeg", "png", "gif", "webp"):
        fmt = "jpeg"
    return fmt, raw


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
    # POST /ebay/sync-promoted — gated behind dry_run flag.
    # Body: {"dry_run": true|false}
    # Dry-run: builds the per-listing ad-rate plan via promoted_listings_agent
    #          and returns "would_apply: N" (N = items with rate > 0).
    # Live:    calls apply_plan() which pushes per-listing bid percentages
    #          to the eBay Marketing API.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/sync-promoted"):
        try:
            body    = json.loads(event.get("body") or "{}")
            dry_run = bool(body.get("dry_run", True))

            try:
                import promoted_listings_agent  # type: ignore
            except Exception as imp_exc:
                logger.error(f"promoted_listings_agent import failed: {imp_exc}")
                return _cors_response(503, {
                    "success": False,
                    "error":   f"promoted_listings_agent module not available: {imp_exc}",
                })

            try:
                cfg = promoted_listings_agent.load_config()
                plan, demoted = promoted_listings_agent.plan_all(cfg)
            except Exception as plan_exc:
                logger.error(f"sync-promoted plan error: {plan_exc}")
                return _cors_response(500, {"success": False, "error": str(plan_exc)})

            would_apply = sum(
                1 for d in plan
                if isinstance(d, dict) and d.get("rate", 0) > 0 and not d.get("blocked")
            )

            if dry_run:
                logger.info(f"sync-promoted DRY-RUN: would apply {would_apply} bids")
                return _cors_response(200, {
                    "success":     True,
                    "dry_run":     True,
                    "would_apply": would_apply,
                    "applied":     0,
                    "errors":      [],
                    "demoted_for_budget_cap": demoted,
                })

            # Live mode — push bids via apply_plan(). It mints its own marketing
            # token from the ebay_cfg dict (sell.marketing scope needed), so we
            # build that dict from the same env vars _get_access_token() uses.
            try:
                ebay_cfg = {
                    "client_id":     CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "refresh_token": REFRESH_TOKEN,
                }
                history = promoted_listings_agent.apply_plan(
                    plan, ebay_cfg, cfg, create_campaign_if_missing=True,
                )
                applied = sum(1 for h in history if h.get("ok"))
                errors  = [
                    {"item_id": h.get("item_id"), "errors": h.get("errors")}
                    for h in history if not h.get("ok")
                ]
                logger.info(f"sync-promoted LIVE: applied {applied}/{len(history)} bids")
                return _cors_response(200, {
                    "success":     True,
                    "dry_run":     False,
                    "would_apply": would_apply,
                    "applied":     applied,
                    "errors":      errors,
                })
            except Exception as live_exc:
                logger.error(f"sync-promoted live error: {live_exc}")
                return _cors_response(500, {"success": False, "error": str(live_exc)})

        except Exception as exc:
            logger.error(f"sync-promoted error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/sync-promoted"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/best-offer-bulk — gated behind dry_run flag.
    # Body: {"dry_run": true|false}
    # Dry-run: proposes per-listing Best Offer auto-accept/decline thresholds
    #          via best_offer_agent.propose_best_offer().
    # Live:    applies the proposal via best_offer_agent.apply_best_offer()
    #          using an access token from _get_access_token().
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/best-offer-bulk"):
        try:
            body    = json.loads(event.get("body") or "{}")
            dry_run = bool(body.get("dry_run", True))

            try:
                import best_offer_agent  # type: ignore
            except Exception as imp_exc:
                logger.error(f"best_offer_agent import failed: {imp_exc}")
                return _cors_response(503, {
                    "success": False,
                    "error":   f"best_offer_agent module not available yet (Agent A still building): {imp_exc}",
                })

            try:
                plan = best_offer_agent.propose_best_offer()
            except Exception as plan_exc:
                logger.error(f"best-offer-bulk propose error: {plan_exc}")
                return _cors_response(500, {"success": False, "error": str(plan_exc)})

            # Count proposed changes — support dict / list plan shapes.
            if isinstance(plan, dict):
                items = (plan.get("items") or plan.get("listings")
                         or plan.get("decisions") or plan.get("proposals") or [])
            elif isinstance(plan, list):
                items = plan
            else:
                items = []
            would_apply = sum(
                1 for it in items
                if isinstance(it, dict) and not it.get("blocked")
                and str(it.get("decision", "apply")).lower() == "apply"
            )

            if dry_run:
                logger.info(f"best-offer-bulk DRY-RUN: would apply {would_apply} offers")
                return _cors_response(200, {
                    "success":     True,
                    "dry_run":     True,
                    "would_apply": would_apply,
                    "applied":     0,
                    "errors":      [],
                    "plan":        plan,
                })

            try:
                access_token = _get_access_token()
                result = best_offer_agent.apply_best_offer(access_token, plan, dry_run=False)
                if isinstance(result, dict):
                    applied = int(result.get("applied", result.get("ok_count", 0)) or 0)
                    errors  = result.get("errors", []) or []
                else:
                    applied = would_apply
                    errors  = []
                logger.info(f"best-offer-bulk LIVE: applied {applied} of {would_apply}")
                return _cors_response(200, {
                    "success":     True,
                    "dry_run":     False,
                    "would_apply": would_apply,
                    "applied":     applied,
                    "errors":      errors,
                })
            except Exception as live_exc:
                logger.error(f"best-offer-bulk live error: {live_exc}")
                return _cors_response(500, {"success": False, "error": str(live_exc)})

        except Exception as exc:
            logger.error(f"best-offer-bulk error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/best-offer-bulk"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/create-listing — create a single fixed-price listing
    # Body: inventory_plan item dict
    #   { title, category_id|ebay_category, store_category, price,
    #     specifics: {k: v, ...}, image_url, store_category_id?,
    #     dry_run?: bool (default true) }
    # Dry-run: returns the XML envelope that WOULD be POSTed.
    # Live:    POSTs Trading API AddItem, returns {success, item_id, ...}.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/create-listing"):
        try:
            body = json.loads(event.get("body") or "{}")
            dry_run = body.get("dry_run", True)
            # Default to dry-run unless explicitly set to False
            if dry_run is not False:
                dry_run = True

            title           = str(body.get("title", "")).strip()[:80]
            category_id     = str(body.get("category_id") or body.get("ebay_category_id") or "").strip()
            store_cat_id    = str(body.get("store_category_id") or body.get("store_category") or "").strip()
            price           = body.get("price")
            quantity        = int(body.get("quantity") or 1)
            image_url       = str(body.get("image_url") or "").strip()
            specifics       = body.get("specifics") or {}
            condition_id    = str(body.get("condition_id") or "4000")  # Used
            shipping_cost   = float(body.get("shipping_cost") or 4.50)

            if not title:
                return _cors_response(400, {"success": False, "error": "title required"})
            if not category_id:
                return _cors_response(400, {"success": False, "error": "category_id required"})
            try:
                price_f = round(float(price), 2)
                if price_f <= 0:
                    raise ValueError
            except (TypeError, ValueError):
                return _cors_response(400, {"success": False, "error": "price must be a positive number"})

            xml_body = _build_additem_xml(
                access_token   = "{{ACCESS_TOKEN}}" if dry_run else _get_access_token(),
                title          = title,
                category_id    = category_id,
                store_cat_id   = store_cat_id,
                price          = price_f,
                quantity       = quantity,
                image_url      = image_url,
                specifics      = specifics,
                condition_id   = condition_id,
                shipping_cost  = shipping_cost,
            )

            if dry_run:
                logger.info(f"create-listing DRY-RUN: title='{title[:40]}...' cat={category_id} price=${price_f:.2f}")
                return _cors_response(200, {
                    "success":  True,
                    "dry_run":  True,
                    "xml":      xml_body,
                    "message":  "Dry run — XML envelope returned, not POSTed to eBay.",
                })

            ok, result = _add_item(xml_body)
            if ok:
                item_id = result.get("item_id", "")
                listing_url = f"https://www.ebay.com/itm/{item_id}" if item_id else ""
                logger.info(f"create-listing LIVE: created {item_id} ('{title[:40]}...')")
                return _cors_response(200, {
                    "success":     True,
                    "item_id":     item_id,
                    "ack":         result.get("ack", ""),
                    "errors":      result.get("errors", []),
                    "listing_url": listing_url,
                })
            else:
                logger.error(f"create-listing LIVE failed: {result.get('errors')}")
                return _cors_response(200, {
                    "success": False,
                    "ack":     result.get("ack", ""),
                    "errors":  result.get("errors", []),
                })

        except Exception as exc:
            logger.error(f"create-listing error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)})

    if method == "OPTIONS" and path.endswith("/ebay/create-listing"):
        return _cors_preflight()

    # ------------------------------------------------------------------
    # POST /ebay/ai-chat — proxy to Anthropic Claude for the assistant page
    # Body: {question: str, context?: dict, history?: list[{role, content}]}
    # Returns: {answer, model, usage, success}
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # POST /ebay/upload-photos — "Beyond Cards" public AI card appraiser.
    # Body: {"image": <data-url or base64>, "back": <optional>}.
    # Identifies the card via Claude vision, drafts an eBay title +
    # description + value estimate, and (if PRICECHARTING_API_KEY is set)
    # attaches a live SportsCardsPro comp. Appraise-only — posts nothing.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/upload-photos"):
        try:
            if not (BEDROCK_MODEL_ID or os.environ.get("ANTHROPIC_API_KEY")):
                logger.error("upload-photos: no BEDROCK_MODEL_ID / ANTHROPIC_API_KEY")
                return _cors_response(503, {
                    "success": False,
                    "error":   "Appraiser not configured — no model backend set on Lambda.",
                }, event)

            body = json.loads(event.get("body") or "{}")
            front = str(body.get("image") or "").strip()
            back  = str(body.get("back") or "").strip()
            if not front:
                return _cors_response(400, {"success": False, "error": "image required"}, event)

            ffmt, fraw = _img_bytes(front)
            if not fraw:
                return _cors_response(400, {"success": False, "error": "invalid image"}, event)
            if len(fraw) > 3_500_000:
                return _cors_response(413, {
                    "success": False,
                    "error":   "Image too large — please use a smaller photo.",
                }, event)

            images = [(ffmt, fraw)]
            if back:
                bfmt, braw = _img_bytes(back)
                if braw and len(braw) <= 3_500_000:
                    images.append((bfmt, braw))
            instruction = ("Identify this trading card and produce the eBay listing JSON. "
                           "Return ONLY the JSON object.")

            try:
                raw, model_label = _run_vision(_BEYOND_SYSTEM_PROMPT, images, instruction, 1200)
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode()[:300]
                logger.error(f"upload-photos vision HTTP {exc.code}: {err_body}")
                return _cors_response(502, {
                    "success": False,
                    "error":   f"AI vision error (HTTP {exc.code}). Please try again.",
                }, event)
            except Exception as exc:
                logger.error(f"upload-photos vision error: {exc}")
                return _cors_response(502, {
                    "success": False,
                    "error":   "AI vision error. Please try again.",
                }, event)

            card = _extract_json(raw)
            logger.info(f"upload-photos: model={model_label} parsed={isinstance(card, dict)}")

            if not isinstance(card, dict):
                return _cors_response(200, {
                    "success":    True,
                    "identified": False,
                    "message":    "Couldn't read the card clearly — try a straight, well-lit photo of the front.",
                }, event)

            comp = None
            if card.get("is_card", True) and card.get("ebay_title"):
                comp = _scp_comp(card.get("ebay_title", ""), PRICECHARTING_API_KEY)

            return _cors_response(200, {
                "success":    True,
                "identified": bool(card.get("is_card", True)),
                "card":       card,
                "comp":       comp,
                "model":      model_label,
            }, event)

        except Exception as exc:
            logger.error(f"upload-photos error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)}, event)

    if method == "OPTIONS" and path.endswith("/ebay/upload-photos"):
        return _cors_preflight(event)

    # POST /ebay/marvelify — "Hero Pulls" Marvel-ify: redraw the scanned athlete
    # as a wholesome superhero (Claude vision persona -> Gemini image restyle).
    if method == "POST" and path.endswith("/ebay/marvelify"):
        try:
            if not GEMINI_API_KEY:
                return _cors_response(503, {
                    "success": False,
                    "error":   "Hero maker not configured yet — no image key set on Lambda.",
                }, event)
            # Require a vision backend too — the persona step IS the kid-safety
            # gate (it flags non-cards / selfies). Without it we'd redraw anything.
            if not (BEDROCK_MODEL_ID or os.environ.get("ANTHROPIC_API_KEY")):
                return _cors_response(503, {
                    "success": False,
                    "error":   "Hero maker not fully configured — no vision backend set.",
                }, event)

            body  = json.loads(event.get("body") or "{}")
            front = str(body.get("image") or "").strip()
            if not front:
                return _cors_response(400, {"success": False, "error": "image required"}, event)
            fmt, raw = _img_bytes(front)
            if not raw:
                return _cors_response(400, {"success": False, "error": "invalid image"}, event)
            if len(raw) > 3_500_000:
                return _cors_response(413, {
                    "success": False,
                    "error":   "Image too large — please use a smaller photo.",
                }, event)

            # Stage 1 — persona (reuse the vision backend; never fatal)
            persona = {}
            try:
                ptext, _lbl = _run_vision(
                    _MARVELIFY_PERSONA_SYSTEM, [(fmt, raw)],
                    "Design the hero persona JSON. Return ONLY JSON.", 700)
                persona = _extract_json(ptext) or {}
            except Exception as exc:
                logger.error(f"marvelify persona error: {exc}")

            # Guard: if the vision step says this is NOT a card of a person
            # (e.g. a kid's selfie), decline gently rather than redraw it.
            # Robust to bool False, the strings "false"/"no", and 0.
            _isc = persona.get("is_card", True)
            if _isc is False or (isinstance(_isc, str) and _isc.strip().lower() in ("false", "no", "0")) or _isc == 0:
                return _cors_response(200, {
                    "success":   True,
                    "generated": False,
                    "persona":   persona,
                    "message":   "Point me at a trading card and I'll make the magic happen!",
                    "reason":    "not_a_card",
                }, event)

            # Sanitize persona fields before splicing into the image prompt:
            # join list values, strip newlines, cap length (defends against a
            # doctored card injecting instructions into the Stage-2 prompt).
            def _clean(key, default):
                v = persona.get(key, default)
                if isinstance(v, (list, tuple)):
                    v = ", ".join(str(x) for x in v)
                v = str(v).replace("\n", " ").replace("\r", " ").strip()
                return (v[:200] or default)

            # Stage 2 — image restyle (random legendary-artist style per pull)
            block = None
            out_mime = out_b64 = None
            try:
                art_style = random.choice(_MARVEL_ARTISTS)
                prompt = _MARVELIFY_IMAGE_TMPL.format(
                    appearance_notes=_clean("appearance_notes",
                                            "the same face, hair, skin tone and build"),
                    hero_alias=_clean("hero_alias", "The Champion"),
                    archetype=_clean("archetype", "powerhouse"),
                    costume_colors=_clean("costume_colors", "bold team colors"),
                    pose=_clean("pose", "leaping heroically toward the viewer"),
                    powers=_clean("powers", "super strength and speed"),
                    art_style=art_style,
                )
                out_mime, out_b64, block = _gemini_image(prompt, fmt, raw, timeout=30)
            except urllib.error.HTTPError as exc:
                logger.error(f"marvelify gemini HTTP {exc.code}: {exc.read().decode()[:300]}")
                block = f"http_{exc.code}"
            except Exception as exc:
                logger.error(f"marvelify gemini error: {exc}")
                block = "error"

            if not out_b64 or len(out_b64) > 5_000_000:
                return _cors_response(200, {
                    "success":   True,
                    "generated": False,
                    "persona":   persona,
                    "message":   "Your hero is shy today — try a clear photo of a single player's card.",
                    "reason":    block,
                }, event)

            return _cors_response(200, {
                "success":    True,
                "generated":  True,
                "persona":    persona,
                "hero_image": f"data:{out_mime};base64,{out_b64}",
                "model":      GEMINI_IMAGE_MODEL,
            }, event)

        except Exception as exc:
            logger.error(f"marvelify error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)}, event)

    if method == "OPTIONS" and path.endswith("/ebay/marvelify"):
        return _cors_preflight(event)

    # ------------------------------------------------------------------
    # POST /ebay/pokedex-save — "Natasha's Pokedex" auto-save.
    # Body: {"image": <data-url>, "card": {...fields from /upload-photos'
    #        "card" object}, "scannedAt": "YYYY-MM-DD" (computed client-side)}
    # Uses the GitHub Contents API (read-modify-write, two commits) to:
    #   1. GET docs/natasha_pokedex/cards.json for the current array + sha
    #   2. next_id = max(existing id) + 1
    #   3. PUT docs/natasha_pokedex/images/card{next_id}.jpg (new commit)
    #   4. append the mapped record to the array
    #   5. PUT (update, with the sha from step 1) the new cards.json
    # Never raises — always returns {success: bool, ...} via _cors_response.
    # ------------------------------------------------------------------
    if method == "POST" and path.endswith("/ebay/pokedex-save"):
        try:
            if not GITHUB_TOKEN:
                logger.error("pokedex-save: GITHUB_TOKEN not configured")
                return _cors_response(503, {
                    "success": False,
                    "error":   "GITHUB_TOKEN not configured",
                }, event)

            body       = json.loads(event.get("body") or "{}")
            image_data = str(body.get("image") or "").strip()
            card       = body.get("card") or {}
            scanned_at = str(body.get("scannedAt") or "").strip()
            if not image_data:
                return _cors_response(400, {"success": False, "error": "image required"}, event)
            if not isinstance(card, dict):
                return _cors_response(400, {"success": False, "error": "card object required"}, event)

            fmt, raw = _img_bytes(image_data)
            if not raw:
                return _cors_response(400, {"success": False, "error": "invalid image"}, event)
            if len(raw) > 8_000_000:
                return _cors_response(413, {
                    "success": False,
                    "error":   "Image too large — please use a smaller photo.",
                }, event)

            cards_path = "docs/natasha_pokedex/cards.json"
            try:
                current_raw, sha = _github_get_json_file(cards_path)
            except urllib.error.HTTPError as exc:
                logger.error(f"pokedex-save cards.json GET HTTP {exc.code}: {exc.read().decode()[:300]}")
                return _cors_response(502, {
                    "success": False,
                    "error":   f"Could not read cards.json (HTTP {exc.code})",
                }, event)

            if current_raw.strip():
                try:
                    cards = json.loads(current_raw.decode("utf-8"))
                except Exception as exc:
                    logger.error(f"pokedex-save: cards.json unparseable, aborting: {exc}")
                    return _cors_response(502, {
                        "success": False,
                        "error":   "cards.json on GitHub is not valid JSON — aborting to avoid data loss",
                    }, event)
            else:
                cards = []
            if not isinstance(cards, list):
                logger.error("pokedex-save: cards.json is not a JSON array, aborting")
                return _cors_response(502, {
                    "success": False,
                    "error":   "cards.json on GitHub is not a JSON array — aborting to avoid data loss",
                }, event)

            existing_ids = [c.get("id") for c in cards if isinstance(c, dict) and isinstance(c.get("id"), (int, float))]
            next_id = int(max(existing_ids)) + 1 if existing_ids else 1

            image_path = f"docs/natasha_pokedex/images/card{next_id}.jpg"
            try:
                _github_put_file(image_path, raw, message=f"Natasha's Pokedex: add card {next_id} image (auto-save)")
            except urllib.error.HTTPError as exc:
                logger.error(f"pokedex-save image PUT HTTP {exc.code}: {exc.read().decode()[:300]}")
                return _cors_response(502, {
                    "success": False,
                    "error":   f"Could not upload card image (HTTP {exc.code})",
                }, event)

            est = card.get("estimated_value_usd") or {}
            try:
                est_value = round(float((est or {}).get("typical") or 0))
            except (TypeError, ValueError):
                est_value = 0

            record = {
                "id":          next_id,
                "name":        card.get("player"),
                "image":       f"images/card{next_id}.jpg",
                "dexNo":       None,
                "hp":          None,
                "type":        None,
                "language":    None,
                "set":         card.get("set_name") or card.get("brand"),
                "cardNumber":  card.get("card_number"),
                "rarity":      None,
                "stage":       None,
                "attacks":     [],
                "illustrator": None,
                "year":        card.get("year") or None,
                "estValue":    est_value,
                "scannedAt":   scanned_at,
            }
            cards.append(record)

            try:
                _github_put_file(
                    cards_path, json.dumps(cards, indent=2).encode("utf-8"),
                    message=f"Natasha's Pokedex: add card {next_id} ({record.get('name') or 'unknown'})",
                    sha=sha,
                )
            except urllib.error.HTTPError as exc:
                logger.error(f"pokedex-save cards.json PUT HTTP {exc.code}: {exc.read().decode()[:300]}")
                return _cors_response(502, {
                    "success": False,
                    "error":   f"Card image saved but cards.json update failed (HTTP {exc.code})",
                }, event)

            logger.info(f"pokedex-save: added card id={next_id} name={record.get('name')}")
            return _cors_response(200, {
                "success":     True,
                "id":          next_id,
                "pokedex_url": "https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/natasha_pokedex/index.html",
            }, event)

        except Exception as exc:
            logger.error(f"pokedex-save error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)}, event)

    if method == "OPTIONS" and path.endswith("/ebay/pokedex-save"):
        return _cors_preflight(event)

    if method == "POST" and path.endswith("/ebay/ai-chat"):
        try:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                logger.error("ai-chat: ANTHROPIC_API_KEY not set")
                return _cors_response(503, {
                    "success": False,
                    "error":   "AI assistant not configured — ANTHROPIC_API_KEY missing on Lambda.",
                }, event)

            body = json.loads(event.get("body") or "{}")
            question = str(body.get("question") or "").strip()
            history  = body.get("history") or []
            if not question:
                return _cors_response(400, {"success": False, "error": "question required"}, event)

            system_prompt = (
                "You are Jason Chletsos's personal sports-card and Pokemon-card assistant. "
                "Jason sells on eBay as 'harpua2001' and runs a dashboard site that surfaces "
                "inventory_plan.json, sold_history.json, pokemon_pikachu_plan.json, and "
                "related JSON data sources. Jason's young son is an avid collector — his "
                "favorites are Pikachu, Charizard, Mew, Mewtwo, and Eevee — so when Pokemon "
                "comes up, mention the son angle where relevant. You are knowledgeable about "
                "card sets, parallels, grading (PSA/BGS/CGC), recent comp pricing, eBay best "
                "practices (titles, item specifics, promoted listings, Best Offer), and the "
                "modern sports-card hobby (Topps Chrome, Panini Prizm, Bowman, etc). "
                "Answer concisely (1-3 short paragraphs unless a list is clearer). Be direct, "
                "card-knowledgeable, and practical — Jason is a working seller, not a beginner."
            )

            messages = []
            for h in history:
                if not isinstance(h, dict):
                    continue
                role = h.get("role")
                content = h.get("content")
                if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                    messages.append({"role": role, "content": content[:8000]})
            messages.append({"role": "user", "content": question[:8000]})

            payload = json.dumps({
                "model":      "claude-opus-4-7",
                "max_tokens": 1024,
                "system":     system_prompt,
                "messages":   messages,
            }).encode()

            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=payload,
                headers={
                    "x-api-key":         api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type":      "application/json",
                },
                method="POST",
            )
            try:
                resp = urllib.request.urlopen(req, timeout=30)
                data = json.loads(resp.read().decode())
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode()[:400]
                logger.error(f"ai-chat Anthropic HTTP {exc.code}: {err_body}")
                return _cors_response(502, {
                    "success": False,
                    "error":   f"Anthropic API HTTP {exc.code}: {err_body}",
                }, event)

            # Extract text from content blocks
            answer_parts = []
            for block in data.get("content", []):
                if isinstance(block, dict) and block.get("type") == "text":
                    answer_parts.append(block.get("text", ""))
            answer = "\n".join(answer_parts).strip()

            logger.info(f"ai-chat: model={data.get('model')} usage={data.get('usage')}")
            return _cors_response(200, {
                "success": True,
                "answer":  answer,
                "model":   data.get("model", ""),
                "usage":   data.get("usage", {}),
            }, event)

        except Exception as exc:
            logger.error(f"ai-chat error: {exc}")
            return _cors_response(500, {"success": False, "error": str(exc)}, event)

    if method == "OPTIONS" and path.endswith("/ebay/ai-chat"):
        return _cors_preflight(event)

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


def _xml_escape(s: str) -> str:
    """Minimal XML escape for text nodes."""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;"))


def _build_additem_xml(access_token, title, category_id, store_cat_id, price,
                       quantity, image_url, specifics, condition_id,
                       shipping_cost) -> str:
    """Build the Trading API AddItem XML envelope (FixedPriceItem, GTC)."""
    # Item specifics — NameValueList nodes
    specifics_xml = ""
    if specifics and isinstance(specifics, dict):
        rows = []
        for name, value in specifics.items():
            if value is None or str(value).strip() == "":
                continue
            rows.append(
                f"      <NameValueList>"
                f"<Name>{_xml_escape(name)}</Name>"
                f"<Value>{_xml_escape(value)}</Value>"
                f"</NameValueList>"
            )
        if rows:
            specifics_xml = "    <ItemSpecifics>\n" + "\n".join(rows) + "\n    </ItemSpecifics>"

    pictures_xml = ""
    if image_url:
        pictures_xml = (
            f"    <PictureDetails>\n"
            f"      <PictureURL>{_xml_escape(image_url)}</PictureURL>\n"
            f"    </PictureDetails>"
        )

    storefront_xml = ""
    if store_cat_id and str(store_cat_id).strip().isdigit():
        storefront_xml = (
            f"    <Storefront>\n"
            f"      <StoreCategoryID>{store_cat_id}</StoreCategoryID>\n"
            f"    </Storefront>"
        )

    return (
        f"<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        f"<AddItemRequest xmlns=\"{NS_URI}\">\n"
        f"  <RequesterCredentials><eBayAuthToken>{access_token}</eBayAuthToken></RequesterCredentials>\n"
        f"  <Item>\n"
        f"    <Title>{_xml_escape(title)}</Title>\n"
        f"    <PrimaryCategory><CategoryID>{_xml_escape(category_id)}</CategoryID></PrimaryCategory>\n"
        f"    <StartPrice currencyID=\"USD\">{price:.2f}</StartPrice>\n"
        f"    <Quantity>{int(quantity)}</Quantity>\n"
        f"    <ListingType>FixedPriceItem</ListingType>\n"
        f"    <ListingDuration>GTC</ListingDuration>\n"
        f"    <Country>US</Country>\n"
        f"    <Currency>USD</Currency>\n"
        f"    <Location>United States</Location>\n"
        f"    <ConditionID>{_xml_escape(condition_id)}</ConditionID>\n"
        f"    <DispatchTimeMax>1</DispatchTimeMax>\n"
        f"{pictures_xml}\n"
        f"{specifics_xml}\n"
        f"{storefront_xml}\n"
        f"    <ShippingDetails>\n"
        f"      <ShippingType>Flat</ShippingType>\n"
        f"      <ApplyShippingDiscount>true</ApplyShippingDiscount>\n"
        f"      <ShippingServiceOptions>\n"
        f"        <ShippingServicePriority>1</ShippingServicePriority>\n"
        f"        <ShippingService>USPSFirstClass</ShippingService>\n"
        f"        <ShippingServiceCost currencyID=\"USD\">{shipping_cost:.2f}</ShippingServiceCost>\n"
        f"      </ShippingServiceOptions>\n"
        f"    </ShippingDetails>\n"
        f"    <ReturnPolicy>\n"
        f"      <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>\n"
        f"      <ReturnsWithinOption>Days_30</ReturnsWithinOption>\n"
        f"      <RefundOption>MoneyBack</RefundOption>\n"
        f"      <ShippingCostPaidByOption>Seller</ShippingCostPaidByOption>\n"
        f"    </ReturnPolicy>\n"
        f"  </Item>\n"
        f"</AddItemRequest>\n"
    )


def _add_item(xml_body: str):
    """POST AddItem XML to Trading API; return (ok, {item_id, ack, errors})."""
    headers = {
        "X-EBAY-API-SITEID":              "0",
        "X-EBAY-API-COMPATIBILITY-LEVEL": "967",
        "X-EBAY-API-CALL-NAME":           "AddItem",
        "X-EBAY-API-APP-NAME":            CLIENT_ID,
        "X-EBAY-API-DEV-NAME":            DEV_ID,
        "X-EBAY-API-CERT-NAME":           CLIENT_SECRET,
        "Content-Type":                   "text/xml",
    }
    try:
        req  = urllib.request.Request(TRADING_API_URL, data=xml_body.encode(), headers=headers, method="POST")
        resp = urllib.request.urlopen(req, timeout=20)
        root = ET.fromstring(resp.read().decode())
    except urllib.error.HTTPError as exc:
        return False, {"ack": "HTTPError", "errors": [f"HTTP {exc.code}: {exc.read().decode()[:300]}"], "item_id": ""}
    except Exception as exc:
        return False, {"ack": "Exception", "errors": [str(exc)], "item_id": ""}

    ack     = root.findtext(f"{{{NS_URI}}}Ack", "")
    item_id = root.findtext(f"{{{NS_URI}}}ItemID", "")
    errors  = []
    for err in root.findall(f".//{{{NS_URI}}}Errors"):
        code  = err.findtext(f"{{{NS_URI}}}ErrorCode", "?")
        short = err.findtext(f"{{{NS_URI}}}ShortMessage", "")
        long_ = err.findtext(f"{{{NS_URI}}}LongMessage", "")
        sev   = err.findtext(f"{{{NS_URI}}}SeverityCode", "")
        errors.append(f"[{code}/{sev}] {short} :: {long_}")
    ok = ack in ("Success", "Warning") and bool(item_id)
    return ok, {"ack": ack, "item_id": item_id, "errors": errors}


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
# Natasha's Pokedex — GitHub Contents API helpers (read-modify-write of
# docs/natasha_pokedex/cards.json + creating docs/natasha_pokedex/images/*.jpg)
# ---------------------------------------------------------------------------
def _github_headers() -> dict:
    return {
        "Authorization":        f"Bearer {GITHUB_TOKEN}",
        "Accept":               "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent":           "natasha-pokedex-lambda",
    }


def _github_get_json_file(path: str):
    """GET a repo file's raw decoded bytes + its blob sha via the Contents API.

    Returns (raw_bytes, sha). Raises urllib.error.HTTPError on any GitHub API
    error (e.g. 404 if the file doesn't exist yet).
    """
    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}?ref=main"
    req = urllib.request.Request(url, headers=_github_headers(), method="GET")
    resp = urllib.request.urlopen(req, timeout=15)
    data = json.loads(resp.read().decode())
    sha = data.get("sha", "")
    b64 = (data.get("content") or "").replace("\n", "")
    raw = base64.b64decode(b64) if b64 else b""
    return raw, sha


def _github_put_file(path: str, raw_bytes: bytes, message: str, sha: str | None = None):
    """PUT (create, or update when `sha` is given) a repo file as a new commit
    on `main` via the Contents API. Raises urllib.error.HTTPError on failure.
    """
    payload = {
        "message": message,
        "content": base64.b64encode(raw_bytes).decode(),
        "branch":  "main",
    }
    if sha:
        payload["sha"] = sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}",
        data=json.dumps(payload).encode(),
        headers={**_github_headers(), "Content-Type": "application/json"},
        method="PUT",
    )
    resp = urllib.request.urlopen(req, timeout=20)
    return json.loads(resp.read().decode())


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
_CORS_DEFAULT_ORIGIN = "https://fivetran-jasonchletsos.github.io"

# Allow-list of additional origins for local dev. Browsers send Origin "null"
# for file:// loads; localhost/127.0.0.1 cover the typical local-server cases.
# Anything not on this list (including production) falls through to the
# default origin in _pick_allowed_origin().
_CORS_ALLOWED_ORIGINS = {
    _CORS_DEFAULT_ORIGIN,
    "null",
}
_CORS_ALLOWED_HOST_PREFIXES = (
    "http://localhost",
    "http://127.0.0.1",
    "https://localhost",
    "https://127.0.0.1",
)

def _pick_allowed_origin(event: dict) -> str:
    """Return the Origin header iff it is on the allow-list, else the
    production default. Browsers compare the response Allow-Origin against
    their request Origin exactly — mismatch = preflight failure."""
    if not isinstance(event, dict):
        return _CORS_DEFAULT_ORIGIN
    headers = event.get("headers") or {}
    # API Gateway preserves header case; some local test events lowercase.
    origin = headers.get("origin") or headers.get("Origin") or ""
    if not origin:
        return _CORS_DEFAULT_ORIGIN
    if origin in _CORS_ALLOWED_ORIGINS:
        return origin
    if origin.startswith(_CORS_ALLOWED_HOST_PREFIXES):
        return origin
    return _CORS_DEFAULT_ORIGIN

def _cors_headers_for(event: dict) -> dict:
    return {
        "Access-Control-Allow-Origin":  _pick_allowed_origin(event),
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

# Static headers kept for routes that only the production site calls (the
# Refresh button, repricing webhook, etc). The AI-chat route uses the dynamic
# variant above so localhost / file:// testing works.
_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  _CORS_DEFAULT_ORIGIN,
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
}

def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json"},
        "body":       json.dumps(body),
    }

def _cors_response(status_code: int, body: dict, event: dict | None = None) -> dict:
    headers = _cors_headers_for(event) if event is not None else dict(_CORS_HEADERS)
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "application/json", **headers},
        "body":       json.dumps(body),
    }

def _cors_preflight(event: dict | None = None) -> dict:
    headers = _cors_headers_for(event) if event is not None else dict(_CORS_HEADERS)
    return {
        "statusCode": 200,
        "headers":    headers,
        "body":       "",
    }

def _html_response(status_code: int, html: str) -> dict:
    return {
        "statusCode": status_code,
        "headers":    {"Content-Type": "text/html"},
        "body":       f"<html><body style='font-family:sans-serif;padding:40px'>{html}</body></html>",
    }
