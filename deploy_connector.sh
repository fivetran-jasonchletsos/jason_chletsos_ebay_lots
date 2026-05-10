#!/usr/bin/env bash
# deploy_connector.sh — deploys the Fivetran connector using credentials from .env
set -euo pipefail

ENV_FILE="$(dirname "$0")/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: .env file not found at $ENV_FILE"
  echo "Copy the template and fill in your values:"
  echo "  cp .env.example .env"
  exit 1
fi

# Load .env
set -a
source "$ENV_FILE"
set +a

# Validate all three are set
for var in FIVETRAN_API_KEY FIVETRAN_API_SECRET FIVETRAN_DESTINATION_ID; do
  if [ -z "${!var:-}" ] || [[ "${!var}" == *"your_"* ]]; then
    echo "ERROR: $var is not set in .env"
    exit 1
  fi
done

# The fivetran CLI --api-key flag expects a base64-encoded "key:secret" string
# Use printf (not echo) to avoid a trailing newline corrupting the base64
API_KEY_B64=$(printf '%s:%s' "$FIVETRAN_API_KEY" "$FIVETRAN_API_SECRET" | base64)

echo "Deploying eBay connector to Fivetran..."
echo "  Destination: $FIVETRAN_DESTINATION_ID"
echo ""

fivetran deploy \
  --api-key "$API_KEY_B64" \
  --destination "jason_chletsos_databricks" \
  --connection "jason_chletsos_ebay_api" \
  --force
