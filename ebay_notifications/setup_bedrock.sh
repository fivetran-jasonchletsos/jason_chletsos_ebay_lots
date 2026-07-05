#!/usr/bin/env bash
# =============================================================================
# setup_bedrock.sh — route Beyond Cards' vision call through AWS Bedrock
# (bills the AWS account, no Anthropic API key needed).
#
#   1) grants the Lambda's IAM role bedrock:InvokeModel
#   2) sets BEDROCK_MODEL_ID on the Lambda (merged; existing env preserved)
#   3) deploys the latest Lambda code
#   4) smoke-tests the endpoint
#
# Usage:
#   ./ebay_notifications/setup_bedrock.sh
#   ./ebay_notifications/setup_bedrock.sh "us.anthropic.claude-sonnet-4-20250514-v1:0"   # override model
# =============================================================================
set -euo pipefail

FN="ebay-account-deletion-notifications"
PROFILE="pokemon-app"; REGION="us-east-1"
# Default: Amazon Nova Lite — first-party (no AWS Marketplace subscription
# needed, unlike Anthropic), vision-capable, cheap. Override with arg 1.
MODEL_ID="${1:-us.amazon.nova-lite-v1:0}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">>> Model: $MODEL_ID"

# --- 1) IAM: allow the Lambda role to invoke Bedrock -------------------------
ROLE_ARN="$(aws lambda get-function-configuration --function-name "$FN" \
  --profile "$PROFILE" --region "$REGION" --query 'Role' --output text)"
ROLE_NAME="${ROLE_ARN##*/}"
echo ">>> Lambda role: $ROLE_NAME"

cat > /tmp/bedrock_policy.json <<'JSON'
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": ["bedrock:InvokeModel"],
    "Resource": [
      "arn:aws:bedrock:*::foundation-model/*",
      "arn:aws:bedrock:*:*:inference-profile/*"
    ]
  }]
}
JSON
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name beyond-cards-bedrock --policy-document file:///tmp/bedrock_policy.json \
  --profile "$PROFILE"
echo ">>> IAM policy attached (bedrock:InvokeModel)"

# --- 2) set BEDROCK_MODEL_ID on the Lambda (merge, preserve existing) --------
export MODEL_ID
export CUR_ENV="$(aws lambda get-function-configuration --function-name "$FN" \
  --profile "$PROFILE" --region "$REGION" --query 'Environment.Variables' --output json)"
python3 - > /tmp/lambda_env.json <<'PY'
import json, os
cur = json.loads(os.environ["CUR_ENV"])
cur["BEDROCK_MODEL_ID"] = os.environ["MODEL_ID"]
print(json.dumps({"Variables": cur}))
PY

# --- 3) deploy latest code + env --------------------------------------------
rm -f /tmp/beyond_lambda.zip
( cd "$ROOT/ebay_notifications" && zip -j /tmp/beyond_lambda.zip lambda_function.py >/dev/null )
aws lambda update-function-code --function-name "$FN" \
  --zip-file fileb:///tmp/beyond_lambda.zip --profile "$PROFILE" --region "$REGION" \
  --query '{Code:LastUpdateStatus}' --output json
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  [ "$st" = "Successful" ] && break; sleep 3
done
aws lambda update-function-configuration --function-name "$FN" \
  --environment file:///tmp/lambda_env.json --profile "$PROFILE" --region "$REGION" \
  --query '{Env:LastUpdateStatus}' --output json
for i in $(seq 1 20); do
  st="$(aws lambda get-function-configuration --function-name "$FN" --profile "$PROFILE" --region "$REGION" --query 'LastUpdateStatus' --output text)"
  echo "    settling: $st"; [ "$st" = "Successful" ] && break; sleep 3
done
rm -f /tmp/lambda_env.json /tmp/bedrock_policy.json

# --- 4) smoke test ----------------------------------------------------------
echo ">>> Smoke test (1x1 image → should return JSON, is_card false is fine)..."
PX="/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
curl -s -X POST "https://jw0hur2091.execute-api.us-east-1.amazonaws.com/ebay/upload-photos" \
  -H "Content-Type: application/json" \
  -d "{\"image\":\"data:image/jpeg;base64,$PX\"}" | head -c 500
echo ""
echo ">>> Done. If you see an access/denied error mentioning Bedrock model access,"
echo "    enable it once: AWS Console → Bedrock → Model access → enable Anthropic Claude."
