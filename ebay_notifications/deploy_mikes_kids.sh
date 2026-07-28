#!/usr/bin/env bash
# =============================================================================
# deploy_mikes_kids.sh — ship the /ebay/kids-save + /ebay/kids-delete routes
# (Mike's Kids Scanner, docs/mikes_kids/), merge-safe.
# =============================================================================
# Builds the FULL Lambda package (lambda_function.py + every agent module the
# other routes import + vendored requests) exactly like deploy_marvelify.sh —
# shipping only lambda_function.py would delete the vendored `requests` and
# the agent modules and 503 the routes that import them. No env-var changes
# are needed: GITHUB_TOKEN is already set on the live Lambda (pushed by
# deploy_natasha_pokedex.sh), and kids-save/kids-delete need nothing else.
#
# IMPORTANT: this only updates Lambda code. It does NOT register the new API
# Gateway routes — that needs a `terraform apply` in this directory
# ("kids-save"/"kids-delete" are already in local.agent_routes in main.tf).
# Until that apply runs, the smoke test below is expected to fail with a
# routing error (403/404), not a real success:false — that's normal on a
# first deploy.
#
# Usage: ./deploy_mikes_kids.sh
# Requires: aws CLI authenticated via SSO (pokemon-app profile), zip, pip3,
# curl, python3.
# =============================================================================
set -euo pipefail

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"
REGION="us-east-1"
API_BASE="https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
ROOT="$(cd .. && pwd)"
STAGE="$SCRIPT_DIR/.build/lambda_src"
ZIP="$SCRIPT_DIR/.build/mikes_kids_deploy.zip"
SMOKE_BODY="$(mktemp -t mikes_kids_smoke.XXXXXX.json)"
trap 'rm -f "$ZIP" "$SMOKE_BODY"' EXIT

# --- 1) Stage the FULL package (mirror main.tf null_resource.stage_lambda_src) #
echo ">>> Staging Lambda package..."
mkdir -p "$STAGE"
cp "$SCRIPT_DIR/lambda_function.py"        "$STAGE/"
cp "$ROOT/seller_hub_agent.py"             "$STAGE/"
cp "$ROOT/seller_hub_phase2.py"            "$STAGE/"
cp "$ROOT/promoted_listings_agent.py"      "$STAGE/"
cp "$ROOT/best_offer_agent.py"             "$STAGE/"
cp "$ROOT/promote.py"                      "$STAGE/"
for f in card_price_agent.py photo_audit_agent.py specifics_agent.py; do
  [ -f "$ROOT/$f" ] && cp "$ROOT/$f" "$STAGE/" || true
done
# Vendor requests only if it isn't already staged (Lambda runtime lacks it).
if [ ! -d "$STAGE/requests" ]; then
  echo ">>> Vendoring requests..."
  pip3 install --quiet --target "$STAGE" requests || \
    echo "  WARN: pip3 install requests failed — requests-using routes will 503"
fi

echo ">>> Zipping full package..."
rm -f "$ZIP"
( cd "$STAGE" && zip -rq "$ZIP" . -x '*.DS_Store' '*/__pycache__/*' )
echo "    package bytes: $(wc -c < "$ZIP")"
# Guard against ever shipping a suspiciously tiny (1-file) package again.
if [ "$(wc -c < "$ZIP")" -lt 200000 ]; then
  echo "  ABORT: package looks too small (<200KB) — staging likely failed. Not deploying."
  exit 1
fi

echo ">>> Updating function code..."
aws lambda update-function-code \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --zip-file "fileb://$ZIP" \
  --query '{Status:LastUpdateStatus,CodeSize:CodeSize}' --output json
for i in $(seq 1 30); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    code: $st"; [ "$st" = "Successful" ] && break
  [ "$st" = "Failed" ] && { echo "  ABORT: code update failed"; exit 1; }
  sleep 3
done

# --- 2) Smoke test: POST a payload missing required fields, expect a clean --- #
#        JSON success:false response (not a 500/crash).
echo ""
echo ">>> Smoke testing /ebay/kids-save (dummy payload, expect success:false)..."
HTTP_STATUS=$(curl -s -o "$SMOKE_BODY" -w "%{http_code}" \
  -X POST "${API_BASE}/kids-save" \
  -H "Content-Type: application/json" \
  -d '{"image": null}' || true)

SUCCESS_FIELD=$(python3 -c "
import json
try:
    with open('$SMOKE_BODY') as f:
        body = json.load(f)
    print(body.get('success', 'MISSING'))
except Exception as exc:
    print(f'PARSE_ERROR: {exc}')
" || echo "PARSE_ERROR")

if [ "$SUCCESS_FIELD" = "False" ]; then
  echo "    HTTP $HTTP_STATUS, success:false as expected. Route is live and error-handled correctly."
elif [ "$HTTP_STATUS" = "403" ] || [ "$HTTP_STATUS" = "404" ]; then
  echo "    NOTE: HTTP $HTTP_STATUS — the API Gateway route likely isn't registered yet."
  echo "    This is EXPECTED before the terraform apply described below has run."
  echo "    Re-run this smoke test (or just this script) after that apply completes."
elif [ "$HTTP_STATUS" -ge 500 ] 2>/dev/null; then
  echo "    WARNING: Got HTTP $HTTP_STATUS (server error) — check Lambda logs (CloudWatch):"
  cat "$SMOKE_BODY"
else
  echo "    WARNING: Got HTTP $HTTP_STATUS with an unexpected body shape (success=$SUCCESS_FIELD):"
  cat "$SMOKE_BODY"
fi

echo ""
echo "============================================================"
echo "  LAMBDA CODE DEPLOY COMPLETE"
echo "============================================================"
echo ""
echo "  No env-var changes were made (GITHUB_TOKEN already live)."
echo ""
echo "  >>> A 'terraform apply' IN ebay_notifications/ IS STILL REQUIRED to"
echo "  >>> register POST/OPTIONS /ebay/kids-save + /ebay/kids-delete in API"
echo "  >>> Gateway (they're already in local.agent_routes in main.tf)."
echo "============================================================"
