#!/usr/bin/env bash
# =============================================================================
# deploy_marvelify.sh — ship the "Hero Pulls" Marvel-ify feature, merge-safe.
# =============================================================================
# Builds the FULL Lambda package (lambda_function.py + every agent module the
# other routes import + vendored requests), pushes the code, sets GEMINI_API_KEY
# merged so existing keys (ANTHROPIC/BEDROCK/PRICECHARTING) are PRESERVED, and
# bumps timeout/memory. No terraform, so it never wipes the out-of-band keys.
#
# IMPORTANT: this MUST package the whole staged tree. Shipping only
# lambda_function.py would delete the vendored `requests` and the agent modules
# (seller_hub_agent, promote, promoted_listings_agent, best_offer_agent, ...)
# that /ebay/sync-promoted, /ebay/best-offer-bulk, /ebay/*-store-categories
# import, 503-ing those routes. Keep the staging list in sync with the
# null_resource.stage_lambda_src block in main.tf.
#
# Usage:
#   export GEMINI_API_KEY=AQ...            # from https://aistudio.google.com/apikey
#   ./deploy_marvelify.sh
#
# Requires: aws CLI authenticated via SSO (pokemon-app profile), zip, pip3.
# =============================================================================
set -euo pipefail

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"
REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
ROOT="$(cd .. && pwd)"
STAGE="$SCRIPT_DIR/.build/lambda_src"
ENV_JSON="$(mktemp -t marvelify_env.XXXXXX.json)"
ZIP="$SCRIPT_DIR/.build/marvelify_deploy.zip"
# Always clean up the temp env file (it contains all Lambda secrets) + the zip.
trap 'rm -f "$ENV_JSON" "$ZIP"' EXIT

: "${GEMINI_API_KEY:?Set it first:  export GEMINI_API_KEY=...   (get one at https://aistudio.google.com/apikey)}"

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

# --- 2) Merge GEMINI_API_KEY (preserve existing env) + bump limits ---------- #
echo ">>> Reading current Lambda environment..."
export CUR_ENV="$(aws lambda get-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --query 'Environment.Variables' --output json)"
python3 - > "$ENV_JSON" <<'PY'
import json, os
cur = json.loads(os.environ["CUR_ENV"])
cur["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY"]
print(json.dumps({"Variables": cur}))
PY

echo ">>> Pushing merged env + timeout=40 + memory=512..."
aws lambda update-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --environment "file://$ENV_JSON" --timeout 40 --memory-size 512 \
  --query '{Status:LastUpdateStatus,Timeout:Timeout,Memory:MemorySize}' --output json
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    config: $st"; [ "$st" = "Successful" ] && break; sleep 3
done

echo ""
echo ">>> Done. /ebay/marvelify is live and the full package (agent modules +"
echo "    requests) is intact. Test from the Hero Pulls page."
