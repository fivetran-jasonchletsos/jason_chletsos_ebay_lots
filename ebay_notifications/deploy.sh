#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Full automated deploy of eBay notification endpoint to AWS
# =============================================================================
# Usage: ./deploy.sh
# Requires: terraform, aws CLI authenticated via SSO (pokemon-app profile)
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ---------------------------------------------------------------------------
# Prompt for the verification token (only secret needed from you)
# ---------------------------------------------------------------------------
if [ -z "${EBAY_VERIFICATION_TOKEN:-}" ]; then
  echo ""
  echo "Enter a verification token (any random string — you'll paste this into"
  echo "the eBay Developer Portal alongside the endpoint URL):"
  read -r -s EBAY_VERIFICATION_TOKEN
  echo ""
fi

export TF_VAR_ebay_verification_token="$EBAY_VERIFICATION_TOKEN"

# ---------------------------------------------------------------------------
# Ensure .build dir exists for Lambda zip
# ---------------------------------------------------------------------------
mkdir -p .build

# ---------------------------------------------------------------------------
# Step 1 — terraform init + first apply (creates all resources)
# ---------------------------------------------------------------------------
echo ">>> Step 1: terraform init"
terraform init -upgrade -input=false

echo ">>> Step 2: First apply — creating Lambda + API Gateway"
terraform apply -auto-approve \
  -var="ebay_verification_token=$EBAY_VERIFICATION_TOKEN" \
  -var="ebay_endpoint_url="

# ---------------------------------------------------------------------------
# Step 2 — capture the endpoint URL and inject it back into Lambda env
# ---------------------------------------------------------------------------
ENDPOINT_URL=$(terraform output -raw endpoint_url)
echo ""
echo ">>> API Gateway endpoint: $ENDPOINT_URL"

echo ">>> Step 3: Second apply — injecting endpoint URL into Lambda env var"
terraform apply -auto-approve \
  -var="ebay_verification_token=$EBAY_VERIFICATION_TOKEN" \
  -var="ebay_endpoint_url=$ENDPOINT_URL"

# ---------------------------------------------------------------------------
# Step 3 — smoke test the endpoint (GET challenge verification)
# ---------------------------------------------------------------------------
echo ""
echo ">>> Step 4: Smoke testing endpoint..."
TEST_CHALLENGE="testchallenge12345"
HTTP_STATUS=$(curl -s -o /tmp/ebay_test_response.json -w "%{http_code}" \
  "${ENDPOINT_URL}?challenge_code=${TEST_CHALLENGE}")

if [ "$HTTP_STATUS" == "200" ]; then
  CHALLENGE_RESPONSE=$(cat /tmp/ebay_test_response.json | python3 -c "import json,sys; print(json.load(sys.stdin).get('challengeResponse','MISSING'))")
  echo "    HTTP 200 OK"
  echo "    challengeResponse: $CHALLENGE_RESPONSE"
  echo "    Endpoint is live and responding correctly."
else
  echo "    WARNING: Got HTTP $HTTP_STATUS — check Lambda logs"
  cat /tmp/ebay_test_response.json
fi

# ---------------------------------------------------------------------------
# Done — print what to paste into eBay Developer Portal
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""
echo "  Register these in eBay Developer Portal:"
echo "  → My Account > Application Keysets > Production > Edit"
echo "  → Notifications > Marketplace Account Deletion"
echo ""
echo "  HTTPS Endpoint URL:"
echo "  $ENDPOINT_URL"
echo ""
echo "  Verification Token:"
echo "  $EBAY_VERIFICATION_TOKEN"
echo ""
echo "  Email: jason.chletsos@fivetran.com"
echo ""
echo "  After saving: click 'Send Test Notification'"
echo "  Green checkmark = Production keys unlocked."
echo "============================================================"
