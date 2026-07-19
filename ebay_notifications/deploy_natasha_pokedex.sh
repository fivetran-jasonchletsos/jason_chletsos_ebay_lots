#!/usr/bin/env bash
# =============================================================================
# deploy_natasha_pokedex.sh — ship the /ebay/pokedex-save route, merge-safe.
# =============================================================================
# The pokedex-save handler only needs stdlib (urllib.request) to call the
# GitHub Contents API, so — unlike deploy_marvelify.sh — it does NOT need the
# full vendored-dependency package. This mirrors deploy.sh's simple packaging
# (just lambda_function.py), but reuses deploy_marvelify.sh's env-var-merge
# pattern so existing secrets (GEMINI_API_KEY, BEDROCK_MODEL_ID,
# ANTHROPIC_API_KEY, etc.) on the live Lambda are never wiped out.
#
# IMPORTANT: this only updates Lambda code + config. It does NOT register the
# new API Gateway route — that needs a separate, human-run `terraform apply`
# in this directory (see local.agent_routes in main.tf). Until that apply
# runs, the smoke test below is expected to fail with a routing error, not a
# real success:false — that's normal on a first deploy.
#
# Usage:
#   export GITHUB_TOKEN=ghp_...     # PAT with contents:write on
#                                    # fivetran-jasonchletsos/jason_chletsos_ebay_lots
#   ./deploy_natasha_pokedex.sh
#
# Requires: aws CLI authenticated via SSO (pokemon-app profile), zip, curl, python3.
# =============================================================================
set -euo pipefail

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"
REGION="us-east-1"
API_BASE="https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
mkdir -p "$SCRIPT_DIR/.build"
ENV_JSON="$(mktemp -t pokedex_env.XXXXXX.json)"
ZIP="$SCRIPT_DIR/.build/pokedex_deploy.zip"
SMOKE_BODY="$(mktemp -t pokedex_smoke.XXXXXX.json)"
# Always clean up the temp env file (it contains all Lambda secrets) + the zip
# + the smoke-test response scratch file.
trap 'rm -f "$ENV_JSON" "$ZIP" "$SMOKE_BODY"' EXIT

# ---------------------------------------------------------------------------
# Require GITHUB_TOKEN from the calling shell's env. Never hardcode it, never
# prompt (a prompt without -s would risk echoing it; simplest safe option is
# to just require it be exported ahead of time, like GEMINI_API_KEY above).
# ---------------------------------------------------------------------------
: "${GITHUB_TOKEN:?Set it first:  export GITHUB_TOKEN=ghp_...   (fine-grained PAT, contents:write on fivetran-jasonchletsos/jason_chletsos_ebay_lots)}"

# --- 1) Package just lambda_function.py (mirror deploy.sh's simple case) --- #
echo ">>> Zipping lambda_function.py..."
rm -f "$ZIP"
zip -j "$ZIP" "$SCRIPT_DIR/lambda_function.py"
echo "    package bytes: $(wc -c < "$ZIP")"

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

# --- 2) Merge GITHUB_TOKEN into the existing env vars (preserve everything else) #
echo ">>> Reading current Lambda environment..."
export CUR_ENV="$(aws lambda get-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --query 'Environment.Variables' --output json)"
python3 - > "$ENV_JSON" <<'PY'
import json, os
cur = json.loads(os.environ["CUR_ENV"])
cur["GITHUB_TOKEN"] = os.environ["GITHUB_TOKEN"]
print(json.dumps({"Variables": cur}))
PY

echo ">>> Pushing merged env vars..."
aws lambda update-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --environment "file://$ENV_JSON" \
  --query '{Status:LastUpdateStatus}' --output json
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    config: $st"; [ "$st" = "Successful" ] && break; sleep 3
done

# --- 3) Smoke test: POST a payload missing required fields, expect a clean --- #
#        JSON success:false response (not a 500/crash). Modeled on deploy.sh's
#        curl -w "%{http_code}" convention (deploy_marvelify.sh has no curl
#        smoke test of its own to copy from).
echo ""
echo ">>> Smoke testing /ebay/pokedex-save (dummy payload, expect success:false)..."
HTTP_STATUS=$(curl -s -o "$SMOKE_BODY" -w "%{http_code}" \
  -X POST "${API_BASE}/pokedex-save" \
  -H "Content-Type: application/json" \
  -d '{"image": null}' || true)

# Parse the body first — pass/fail is keyed on the JSON shape, NOT the HTTP
# status code. The handler may legitimately return 400 (matching this file's
# existing "bad request" convention, e.g. the /ebay/revise and /ebay/reprice
# handlers) or 200 with success:false — either is a correctly-handled
# rejection, not a broken route.
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
echo "  LAMBDA CODE + CONFIG DEPLOY COMPLETE"
echo "============================================================"
echo ""
echo "  GITHUB_TOKEN merged into the live Lambda's env vars; all other"
echo "  existing env vars (GEMINI_API_KEY, BEDROCK_MODEL_ID, etc.) preserved."
echo ""
echo "  >>> A SEPARATE, HUMAN-RUN 'terraform apply' IN ebay_notifications/ IS"
echo "  >>> STILL REQUIRED to actually register the POST/OPTIONS"
echo "  >>> /ebay/pokedex-save route in API Gateway (add \"pokedex-save\" to"
echo "  >>> local.agent_routes in main.tf first). This script only updates"
echo "  >>> the Lambda's code and environment — it does NOT touch API Gateway."
echo "============================================================"
