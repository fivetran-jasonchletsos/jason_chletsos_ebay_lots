#!/usr/bin/env bash
# =============================================================================
# deploy_marvelify.sh — ship the "Hero Pulls" Marvel-ify feature, merge-safe.
# =============================================================================
# Pushes the updated lambda_function.py code, sets GEMINI_API_KEY (merged so
# existing keys like ANTHROPIC/BEDROCK/PRICECHARTING are PRESERVED), and bumps
# the function timeout/memory so image generation has room. No terraform, so it
# never wipes the out-of-band keys.
#
# Usage:
#   export GEMINI_API_KEY=AIza...        # from https://aistudio.google.com/apikey
#   ./deploy_marvelify.sh
#
# Requires: aws CLI authenticated via SSO (pokemon-app profile), zip.
# =============================================================================
set -euo pipefail

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"
REGION="us-east-1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

: "${GEMINI_API_KEY:?Set it first:  export GEMINI_API_KEY=AIza...   (get one at https://aistudio.google.com/apikey)}"

# --- 1) Package + push the code -------------------------------------------- #
echo ">>> Zipping lambda_function.py..."
mkdir -p .build
ZIP=".build/marvelify_deploy.zip"
rm -f "$ZIP"
zip -j "$ZIP" lambda_function.py >/dev/null

echo ">>> Updating function code..."
aws lambda update-function-code \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --zip-file "fileb://$ZIP" \
  --query '{Status:LastUpdateStatus,Runtime:Runtime}' --output json

echo ">>> Waiting for code update to settle..."
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    status: $st"; [ "$st" = "Successful" ] && break; sleep 3
done

# --- 2) Merge GEMINI_API_KEY (preserve existing env) + bump limits ---------- #
echo ">>> Reading current Lambda environment..."
export CUR_ENV="$(aws lambda get-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --query 'Environment.Variables' --output json)"

echo ">>> Merging in GEMINI_API_KEY (existing keys preserved)..."
python3 - > /tmp/marvelify_env.json <<'PY'
import json, os
cur = json.loads(os.environ["CUR_ENV"])
cur["GEMINI_API_KEY"] = os.environ["GEMINI_API_KEY"]
print(json.dumps({"Variables": cur}))
PY

echo ">>> Pushing merged env + timeout=40 + memory=512..."
aws lambda update-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --environment file:///tmp/marvelify_env.json \
  --timeout 40 --memory-size 512 \
  --query '{Status:LastUpdateStatus,Timeout:Timeout,Memory:MemorySize}' --output json

echo ">>> Waiting for config update to settle..."
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    status: $st"; [ "$st" = "Successful" ] && break; sleep 3
done

rm -f /tmp/marvelify_env.json "$ZIP"
echo ""
echo ">>> Done. /ebay/marvelify is live. Test it from the Hero Pulls page,"
echo "    or: curl -s -X POST <endpoint>/ebay/marvelify -d '{\"image\":\"...\"}'"
