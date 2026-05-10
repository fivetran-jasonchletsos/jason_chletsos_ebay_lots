# eBay Seller Fivetran Connector

Custom Fivetran connector built with the **Fivetran Connector SDK (Python)** that syncs eBay seller data for account **Harpua2001** into your data warehouse for listing visibility and buyer engagement analysis.

---

## Project Structure

```
.
├── connector.py                          # Main connector — schema() + update() functions
├── requirements.txt                      # Python dependencies
├── configuration.json                    # Credential template (DO NOT commit real values)
├── analysis_views.sql                    # Downstream SQL views / dbt-ready models
├── README.md
└── ebay_notifications/
    ├── lambda_function.py                # AWS Lambda — handles eBay GET challenge + POST deletion
    └── main.tf                           # Terraform — API Gateway + Lambda + IAM + CloudWatch
```

---

## Tables Synced

| Table | Source API | Sync Strategy | PK |
|---|---|---|---|
| `active_listings` | Inventory + Offer API | Incremental (last_modified_date) | `listing_id` |
| `listing_performance` | Analytics Traffic + Sales | Rolling 30-day window | `listing_id` + `date` |
| `orders` | Fulfillment API | Incremental (creationdate) | `order_id` |
| `promoted_listings` | Marketing Campaigns + Ads | Full refresh | `campaign_id` + `ad_id` |
| `seller_standards` | Analytics Standards Profile | Daily snapshot | `snapshot_date` |

---

## Authentication Setup

This connector uses **eBay OAuth 2.0 Authorization Code flow**. You need to complete a one-time manual step to get a `refresh_token`, then the connector handles token renewal automatically.

### Step 1 — Create an eBay Developer App

1. Go to [developer.ebay.com](https://developer.ebay.com) and sign in with `jchletsos@gmail.com`
2. Navigate to **My Account → Application Keysets**
3. Create a **Production** keyset — note your:
   - `App ID` → this is your `client_id`
   - `Cert ID` → this is your `client_secret`
   - `Dev ID` → this is your `dev_id`

### Step 2 — Configure OAuth Scopes

In your app's **Auth Accepted OAuth Scopes**, add:

```
https://api.ebay.com/oauth/api_scope/sell.inventory.readonly
https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly
https://api.ebay.com/oauth/api_scope/sell.analytics.readonly
https://api.ebay.com/oauth/api_scope/sell.marketing.readonly
https://api.ebay.com/oauth/api_scope/commerce.identity.readonly
```

### Step 3 — Get a User Refresh Token

The `refresh_token` is a long-lived token tied to your eBay user account (Harpua2001). Generate it once via the eBay OAuth flow:

1. In the Developer Portal, go to **User Tokens → Get a Token from eBay via Your Application**
2. Select **Production** environment
3. Add all 5 scopes listed above
4. Click **Sign In** — this redirects you through eBay's OAuth consent screen
5. After authorizing, copy the **Refresh Token** (valid for 18 months)
6. Store it securely — paste it into your Fivetran configuration

### Step 4 — Populate configuration.json (local testing only)

```json
{
  "client_id":     "YourAppID-YourSuffix",
  "client_secret": "YourCertID",
  "refresh_token": "v^1.1#i^1#r^1#...",
  "dev_id":        "YourDevID",
  "environment":   "PRODUCTION"
}
```

> **Never commit real credentials.** `configuration.json` is for local `fivetran debug` runs only. In production, inject via Fivetran's configuration UI.

---

## Local Development & Testing

### Install dependencies

```bash
pip install fivetran_connector_sdk requests
```

Or with a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run locally

```bash
fivetran debug --port 50051
```

This reads `configuration.json` and runs a full sync locally, printing all upserted records and checkpoints to stdout. Useful for validating API responses before deploying.

---

## Deployment to Fivetran

### 1. Install the Fivetran CLI

```bash
pip install fivetran
```

### 2. Deploy the connector

```bash
fivetran deploy --api-key <YOUR_FIVETRAN_API_KEY> --api-secret <YOUR_FIVETRAN_API_SECRET>
```

This packages `connector.py` + `requirements.txt` and uploads them to Fivetran.

### 3. Configure in the Fivetran UI

1. Go to **Connectors → Add Connector → Custom SDK**
2. Select the deployed connector
3. Paste your configuration JSON (with real credentials)
4. Set the destination (BigQuery / Snowflake / Postgres)
5. Set sync frequency:
   - `active_listings`, `orders`, `promoted_listings` → every **6 hours**
   - `listing_performance`, `seller_standards` → **daily** (analytics APIs are slower to update)

---

## Incremental Sync State

The connector stores cursors in Fivetran's state dict:

```json
{
  "active_listings_cursor": "2025-01-01T00:00:00Z",
  "orders_cursor":          "2025-01-01T00:00:00Z"
}
```

- **active_listings**: filters by offer `listing.startDate` / `endDate` — on first run pulls all, subsequent runs pull only changed records
- **orders**: uses `creationdate` range filter — defaults to 90 days back on first run
- **listing_performance**: always pulls a rolling 30-day window (eBay analytics APIs don't support cursor-based incremental sync); upserts are idempotent via the composite PK `(listing_id, date)`
- **promoted_listings** + **seller_standards**: full refresh on each sync run

---

## Error Handling

| HTTP Status | Behavior |
|---|---|
| `429 Rate Limited` | Exponential backoff, up to 3 retries (max 60s wait) |
| `500 / 503` | Retry after 2s, up to 3 attempts |
| `401 Unauthorized` | Fatal — logs clearly, raises `RuntimeError` |
| `403 Forbidden` | Fatal — logs scope issue, raises `RuntimeError` |
| Network errors | Exponential backoff, up to 3 retries |

---

## Downstream Analysis (analysis_views.sql)

Five SQL views ready to run against your warehouse or adapt as dbt models:

### 1. `listing_health_dashboard`
Flags each active listing with one of:
- `HIGH_IMPRESSIONS_LOW_CTR` — title or images need work
- `HIGH_CTR_LOW_CONVERSION` — price or description problem
- `WATCHERS_NO_SALES` — buyers on the fence; try a price nudge or Best Offer
- `LOW_VISIBILITY` — buried in search; check item specifics + promoted listings
- `HEALTHY`

### 2. `category_pricing_analysis`
Revenue by category + price positioning (`PRICED_HIGH` / `PRICED_LOW` / `COMPETITIVELY_PRICED`) vs. your own sold history.

### 3. `promotion_roi`
For promoted listings: **ROAS** (return on ad spend) and **cost per sale**.
For non-promoted listings: flags candidates that would benefit from promotion based on CTR and impression volume.

### 4. `listing_quality_flags`
Surfaces listings that hurt eBay Cassini search ranking:
- Fewer than 2 images (eBay recommends 8–12)
- Title shorter than 60 characters
- Missing `item_specifics` (brand, size, color, material — critical for search)
- Missing condition

### 5. `sales_velocity`
- **Fast movers** with low stock → `RESTOCK_URGENTLY` / `RESTOCK_SOON`
- **Zero sales in 30+ days** → `RELIST_OR_PRICE_DROP` / `REVIEW_PRICING`
- Days-until-stockout estimate at current velocity

---

## Key Implementation Notes

### SKU ↔ Listing ID Cross-Reference
eBay's Inventory API is SKU-based; the Offer API maps SKUs to `listingId` (the actual eBay item number visible on ebay.com). The connector fetches both and joins them in `sync_active_listings()`.

### Item Specifics
Stored as a JSON string column (`item_specifics`). These map directly to eBay's Cassini search ranking signals — brand, size, color, material, etc. The `listing_quality_flags` view surfaces listings missing these.

### Analytics API Notes
- The Traffic Report API (`/sell/analytics/v1/traffic_report`) returns a dimension-metric matrix. The connector parses `dimensionValues` and `metricValues` arrays into flat records.
- The Item Sales Report API (`/sell/analytics/v1/item_sales_report`) returns `salesReportRecords`. Both are merged on `(listing_id, date)`.
- If either analytics endpoint returns no data (common for new apps or accounts with limited history), the connector logs a warning and continues — it won't fail the sync.

### Promoted Listings Metrics
Ad-level metrics (impressions, clicks, sales) are returned inline in the ad object when available. If your account uses the newer campaign reporting API, you may need to add a separate call to `/sell/marketing/v1/ad_campaign/{id}/report` — the structure is identical, just add another `_request()` call in `sync_promoted_listings()`.

---

---

## eBay Production Key Compliance — Account Deletion Endpoint

eBay **requires** a public HTTPS webhook before granting Production API access. The
`ebay_notifications/` folder contains everything needed to satisfy this with AWS.

### Architecture

```
eBay Developer Portal
        │  GET ?challenge_code=xxx  (ownership verification)
        │  POST { account deletion payload }
        ▼
AWS API Gateway (HTTP API)
        │
        ▼
AWS Lambda  (ebay_notifications/lambda_function.py)
        │  logs to CloudWatch (30-day retention)
        ▼
Returns 200 — eBay is satisfied
```

### One-time Setup

#### 1. Authenticate with AWS SSO

```bash
aws sso login --profile your-profile
# or if using environment credentials:
export AWS_PROFILE=your-profile
```

#### 2. Choose a verification token

Pick any random string — you'll use it in two places:

```bash
export TF_VAR_ebay_verification_token="my-secret-verification-token-abc123"
```

#### 3. Deploy with Terraform (first apply)

```bash
cd ebay_notifications
terraform init
terraform apply
```

Terraform outputs the public endpoint URL, e.g.:
```
endpoint_url = "https://abc123xyz.execute-api.us-east-1.amazonaws.com/ebay/notifications"
```

#### 4. Update Lambda with its own URL (second apply)

The Lambda needs to know its own URL for the SHA-256 challenge hash:

```bash
terraform apply \
  -var="ebay_verification_token=$TF_VAR_ebay_verification_token"
```

Then update the Lambda env var directly (or add `ebay_endpoint_url` as a variable and re-apply):

```bash
aws lambda update-function-configuration \
  --function-name ebay-account-deletion-notifications \
  --environment "Variables={
    EBAY_VERIFICATION_TOKEN=$TF_VAR_ebay_verification_token,
    EBAY_ENDPOINT_URL=https://abc123xyz.execute-api.us-east-1.amazonaws.com/ebay/notifications
  }"
```

#### 5. Register in eBay Developer Portal

1. Go to [developer.ebay.com](https://developer.ebay.com) → **My Account → Application Keysets → Production**
2. Click **Edit** next to your Production keyset
3. Scroll to **Notifications → Marketplace Account Deletion**
4. Fill in:
   - **HTTPS endpoint**: `https://abc123xyz.execute-api.us-east-1.amazonaws.com/ebay/notifications`
   - **Verification token**: the same string you set in `EBAY_VERIFICATION_TOKEN`
   - **Email**: `jason.chletsos@fivetran.com`
5. Click **Send Test Notification** — eBay sends a GET with a challenge code
6. If the response shows a green checkmark, you're verified ✓
7. Save — your Production keys are now fully unlocked

### AWS Resource Tags Applied

All resources are tagged automatically via Terraform `default_tags`:

| Tag | Value |
|---|---|
| `username` | `jason.chletsos@fivetran.com` |
| `expires_on` | `2027-01-01` |
| `department` | `sales` |
| `team` | `sales_engineering` |
| `project` | `ebay-fivetran-connector` |
| `managed_by` | `terraform` |

### Cost

Essentially **free** — API Gateway HTTP API + Lambda at this call volume (a few
verification pings + rare deletion events) falls well within the AWS free tier.

---

## Refresh Token Expiry

eBay refresh tokens are valid for **18 months**. When one expires:
1. Repeat Step 3 above (User Tokens flow) to get a new refresh token
2. Update the `refresh_token` value in Fivetran's connector configuration UI
3. No code changes needed

---

## Reddit Cross-Post Setup (`reddit.html` page)

The site includes a Reddit cross-post page that lets you select a listing and post it to a sales subreddit (`r/SportsCardSales` is the primary target — strict format, highest traffic for sports cards). The actual POST happens server-side via the same AWS Lambda.

### One-time Reddit app registration

1. Go to https://www.reddit.com/prefs/apps and click **create another app**
2. Name: `harpua2001-crosspost` (or anything)
3. App type: **script**
4. Description: optional
5. About URL: leave blank
6. Redirect URI: `http://localhost:8080` (only needed once for the token flow)
7. Click **create app**
8. Note:
   - **client_id** — short string under "personal use script" header
   - **client_secret** — labelled "secret"

### Get a Reddit refresh token (one-time)

Use this minimal Python script (paste into a temp file):

```python
import requests, urllib.parse, webbrowser, http.server, threading
CID, CSEC = "YOUR_CLIENT_ID", "YOUR_CLIENT_SECRET"
state = "x"
auth_url = ("https://www.reddit.com/api/v1/authorize"
            f"?client_id={CID}&response_type=code&state={state}"
            "&redirect_uri=http://localhost:8080"
            "&duration=permanent&scope=submit identity")
print("Opening:", auth_url)
code = []
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s):
        q = urllib.parse.parse_qs(s.path.split("?", 1)[-1])
        code.append(q["code"][0])
        s.send_response(200); s.end_headers()
        s.wfile.write(b"OK — close this tab.")
threading.Thread(target=lambda: http.server.HTTPServer(("", 8080), H).serve_forever(), daemon=True).start()
webbrowser.open(auth_url)
input("Press Enter once you've authorized…")
r = requests.post("https://www.reddit.com/api/v1/access_token",
    auth=(CID, CSEC),
    headers={"User-Agent": "harpua2001-crosspost/1.0"},
    data={"grant_type": "authorization_code", "code": code[0],
          "redirect_uri": "http://localhost:8080"})
print("REFRESH TOKEN:", r.json()["refresh_token"])
```

Run it, click Allow in the browser, copy the printed `REFRESH TOKEN` — this is permanent unless you revoke the app.

### Deploy the Reddit Lambda

```bash
cd ebay_notifications
export TF_VAR_reddit_client_id="YOUR_CLIENT_ID"
export TF_VAR_reddit_client_secret="YOUR_CLIENT_SECRET"
export TF_VAR_reddit_refresh_token="YOUR_REFRESH_TOKEN"
export TF_VAR_reddit_user_agent="harpua2001-crosspost/1.0 by harpua2001"
terraform apply
```

This adds:
- 4 Reddit env vars to the existing Lambda
- New API Gateway routes `POST /ebay/reddit-post` and `OPTIONS /ebay/reddit-post`

After apply, the **Post to Reddit** button on `reddit.html` works end-to-end. Until then, the Copy button (manual paste at `reddit.com/r/<sub>/submit`) is always available as a fallback.

### Subreddit rules to know

- **r/SportsCardSales** — requires `[WTS]` tag in title, must include username + date image (proof of ownership), strict shipping abbreviations (PWE/BMWT). The page generates the right title format but you should add a proof image manually before submitting on first use.
- **r/footballcards** — selling allowed in flair-tagged posts; less strict.
- **r/Pokemoncardsales** — strict, `[WTS]` required, prices in title.

The page pre-selects the most appropriate sub based on the listing's category (Pokemon → Pokemoncardsales, basketball → r/basketballcards, baseball → r/baseballcards, football and everything else → r/SportsCardSales).
