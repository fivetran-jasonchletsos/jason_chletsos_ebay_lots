#!/usr/bin/env bash
# =============================================================================
# set_lambda_keys.sh — safely ADD ANTHROPIC_API_KEY (+ PRICECHARTING_API_KEY)
# to the live Lambda WITHOUT wiping any existing environment variables.
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...        # your Anthropic key
#   ./ebay_notifications/set_lambda_keys.sh
#
# The pricecharting key is read automatically from configuration.json.
# =============================================================================
set -euo pipefail

: "${ANTHROPIC_API_KEY:?Set it first:  export ANTHROPIC_API_KEY=sk-ant-...}"

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"
REGION="us-east-1"

# repo root (this script lives in ebay_notifications/)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# pricecharting key from configuration.json (optional; enables live comps)
export PC_KEY="$(python3 -c "import json;print(json.load(open('$ROOT/configuration.json')).get('pricecharting_api_key',''))" 2>/dev/null || echo '')"

echo ">>> Reading current Lambda environment..."
export CUR_ENV="$(aws lambda get-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --query 'Environment.Variables' --output json)"

echo ">>> Merging in ANTHROPIC_API_KEY$([ -n "$PC_KEY" ] && echo ' + PRICECHARTING_API_KEY')..."
python3 - > /tmp/lambda_env.json <<'PY'
import json, os
cur = json.loads(os.environ["CUR_ENV"])
cur["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
if os.environ.get("PC_KEY"):
    cur["PRICECHARTING_API_KEY"] = os.environ["PC_KEY"]
print(json.dumps({"Variables": cur}))
PY

echo ">>> Pushing merged environment (existing vars preserved)..."
aws lambda update-function-configuration \
  --function-name "$FN" --profile "$PROFILE" --region "$REGION" \
  --environment file:///tmp/lambda_env.json \
  --query '{Status:LastUpdateStatus}' --output json

echo ">>> Waiting for update to settle..."
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" \
        --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    status: $st"
  [ "$st" = "Successful" ] && break
  sleep 3
done

rm -f /tmp/lambda_env.json
echo ">>> Done. ANTHROPIC_API_KEY is set (and ai-chat is fixed too)."
