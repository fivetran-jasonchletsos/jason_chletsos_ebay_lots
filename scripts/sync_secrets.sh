#!/usr/bin/env bash
# =============================================================================
# sync_secrets.sh — One-shot reconciliation of all credential locations.
# =============================================================================
# Reads the canonical credentials from this repo's local files and pushes them
# to every place that needs them:
#
#   - GitHub Actions secret EBAY_CONFIGURATION_JSON (so cron + Refresh work)
#   - AWS Lambda env vars (eBay + Fivetran + Reddit, anything you have)
#   - Triggers a fresh GitHub workflow run + verifies it succeeds
#
# Run this whenever your eBay refresh_token rotates or any cred changes.
# Idempotent — safe to run any time.
#
# Required local files:
#   ./configuration.json   — eBay creds (client_id, client_secret, refresh_token, dev_id)
#   ./.env                 — FIVETRAN_API_KEY/SECRET, optional REDDIT_*
#
# Usage:
#   bash scripts/sync_secrets.sh
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

GH_REPO="fivetran-jasonchletsos/jason_chletsos_ebay_lots"
LAMBDA_FN="ebay-account-deletion-notifications"
AWS_PROFILE="${AWS_PROFILE:-pokemon-app}"
FIVETRAN_CONNECTOR_ID="${FIVETRAN_CONNECTOR_ID:-sentient_ragweed}"

# ---- preflight ----
[ -f configuration.json ] || { echo "ERROR: configuration.json missing in repo root."; exit 1; }
[ -f .env ]               || { echo "ERROR: .env missing in repo root."; exit 1; }
command -v jq >/dev/null  || { echo "Installing jq…"; brew install jq; }
python3 -c "import nacl.public" 2>/dev/null || { echo "Installing pynacl…"; pip3 install --quiet pynacl; }

# ---- 1. AWS SSO ----
echo "▶ 1/5 Verifying AWS SSO ($AWS_PROFILE)…"
if ! aws sts get-caller-identity --profile "$AWS_PROFILE" >/dev/null 2>&1; then
  echo "  Logging in…"
  aws sso login --profile "$AWS_PROFILE"
fi
echo "  ✓ AWS SSO active"

# ---- 2. Update Lambda env vars (preserve existing, overlay new) ----
echo "▶ 2/5 Reconciling Lambda env vars on $LAMBDA_FN…"
set -a; source .env; set +a
EBAY_CFG_RAW=$(cat configuration.json)

# Pull existing Lambda env, overlay every cred we have, write back
EXISTING=$(aws lambda get-function-configuration --function-name "$LAMBDA_FN" --profile "$AWS_PROFILE" --query 'Environment.Variables' --output json)
NEW_VARS=$(python3 - "$EXISTING" <<'PY'
import json, os, sys
env = json.loads(sys.argv[1])

# --- eBay creds ---
cfg = json.load(open('configuration.json'))
env['EBAY_CLIENT_ID']       = cfg.get('client_id', '')
env['EBAY_CLIENT_SECRET']   = cfg.get('client_secret', '')
env['EBAY_REFRESH_TOKEN']   = cfg.get('refresh_token', '')
env['EBAY_DEV_ID']          = cfg.get('dev_id', '')

# --- Fivetran ---
for k in ('FIVETRAN_API_KEY', 'FIVETRAN_API_SECRET'):
    if os.environ.get(k):
        env[k] = os.environ[k]
env['FIVETRAN_CONNECTOR_ID'] = os.environ.get('FIVETRAN_CONNECTOR_ID', 'sentient_ragweed')

# --- Reddit (optional) ---
for k in ('REDDIT_CLIENT_ID', 'REDDIT_CLIENT_SECRET', 'REDDIT_REFRESH_TOKEN', 'REDDIT_USER_AGENT'):
    if os.environ.get(k):
        env[k] = os.environ[k]

print(json.dumps({'Variables': env}))
PY
)
aws lambda update-function-configuration \
  --function-name "$LAMBDA_FN" \
  --profile "$AWS_PROFILE" \
  --environment "$NEW_VARS" \
  --no-cli-pager > /dev/null
echo "  ✓ Lambda env vars updated"

# ---- 3. Update Lambda code (rebuild zip from current lambda_function.py) ----
echo "▶ 3/5 Pushing latest Lambda code…"
mkdir -p ebay_notifications/.build
( cd ebay_notifications/.build && rm -f lambda.zip && zip -j lambda.zip ../lambda_function.py >/dev/null )
aws lambda update-function-code \
  --function-name "$LAMBDA_FN" \
  --profile "$AWS_PROFILE" \
  --zip-file "fileb://$REPO_ROOT/ebay_notifications/.build/lambda.zip" \
  --no-cli-pager > /dev/null
echo "  ✓ Lambda code updated"

# Wait for the function update to settle before invoking it for GH token
aws lambda wait function-updated --function-name "$LAMBDA_FN" --profile "$AWS_PROFILE" 2>/dev/null || true

# ---- 4. Update GitHub Actions secret EBAY_CONFIGURATION_JSON ----
echo "▶ 4/5 Updating GitHub secret EBAY_CONFIGURATION_JSON…"
GH_TOKEN=$(aws lambda get-function-configuration --function-name "$LAMBDA_FN" --profile "$AWS_PROFILE" --query 'Environment.Variables.GITHUB_TOKEN' --output text)
if [ -z "$GH_TOKEN" ] || [ "$GH_TOKEN" = "None" ]; then
  echo "  ⚠ GITHUB_TOKEN not set on Lambda; cannot update GitHub secret programmatically."
  echo "     Manually paste configuration.json contents into:"
  echo "     https://github.com/$GH_REPO/settings/secrets/actions"
else
  PUBKEY_JSON=$(curl -s -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/$GH_REPO/actions/secrets/public-key")
  KEY_ID=$(echo "$PUBKEY_JSON"   | jq -r .key_id)
  PUB_KEY=$(echo "$PUBKEY_JSON"  | jq -r .key)
  if [ -z "$KEY_ID" ] || [ "$KEY_ID" = "null" ]; then
    echo "  ⚠ Could not fetch repo public key. GitHub token may lack 'secrets' scope."
    echo "     Update manually at https://github.com/$GH_REPO/settings/secrets/actions"
  else
    ENCRYPTED=$(python3 - "$PUB_KEY" "$EBAY_CFG_RAW" <<'PY'
import sys, base64
from nacl import encoding, public
pub = public.PublicKey(sys.argv[1].encode(), encoding.Base64Encoder())
sealed = public.SealedBox(pub).encrypt(sys.argv[2].encode())
print(base64.b64encode(sealed).decode())
PY
)
    HTTP=$(curl -s -o /tmp/gh_secret_resp.json -w "%{http_code}" -X PUT \
      -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      -H "Content-Type: application/json" \
      "https://api.github.com/repos/$GH_REPO/actions/secrets/EBAY_CONFIGURATION_JSON" \
      -d "$(jq -n --arg v "$ENCRYPTED" --arg k "$KEY_ID" '{encrypted_value:$v, key_id:$k}')")
    if [[ "$HTTP" =~ ^20 ]]; then
      echo "  ✓ GitHub secret updated (HTTP $HTTP)"
    else
      echo "  ✗ GitHub secret update failed (HTTP $HTTP):"; cat /tmp/gh_secret_resp.json; exit 1
    fi
  fi
fi

# ---- 5. Trigger a workflow run and watch it ----
echo "▶ 5/5 Triggering refresh workflow + watching it…"
curl -s -X POST -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$GH_REPO/actions/workflows/refresh.yml/dispatches" \
  -d '{"ref":"main"}'
sleep 4
RUN_ID=$(curl -s -H "Authorization: Bearer $GH_TOKEN" \
  "https://api.github.com/repos/$GH_REPO/actions/workflows/refresh.yml/runs?per_page=1" | jq -r .workflow_runs[0].id)
echo "  Run #$(curl -s -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/$GH_REPO/actions/runs/$RUN_ID" | jq -r .run_number) started — id $RUN_ID"

while true; do
  STATUS=$(curl -s -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/$GH_REPO/actions/runs/$RUN_ID" | jq -r .status)
  [ "$STATUS" = "completed" ] && break
  printf "."
  sleep 6
done
echo
CONCLUSION=$(curl -s -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/$GH_REPO/actions/runs/$RUN_ID" | jq -r .conclusion)
echo "  Status: $CONCLUSION"
if [ "$CONCLUSION" = "success" ]; then
  echo
  echo "✅ All credentials reconciled. Refresh button + cron will now work end-to-end."
  echo "   Live site: https://fivetran-jasonchletsos.github.io/$GH_REPO#"
else
  echo
  echo "❌ Workflow still failing. Pulling step-by-step result:"
  curl -s -H "Authorization: Bearer $GH_TOKEN" "https://api.github.com/repos/$GH_REPO/actions/runs/$RUN_ID/jobs" \
    | jq -r '.jobs[].steps[] | "  \(.conclusion // "-"): \(.name)"'
  echo
  echo "Pull failure log:"
  echo "  curl -sL -H \"Authorization: Bearer \$(aws lambda get-function-configuration --function-name $LAMBDA_FN --profile $AWS_PROFILE --query 'Environment.Variables.GITHUB_TOKEN' --output text)\" \\"
  echo "    \"https://api.github.com/repos/$GH_REPO/actions/runs/$RUN_ID/logs\" -o /tmp/run.zip && unzip -p /tmp/run.zip '*Validate*' | tail"
  exit 1
fi
