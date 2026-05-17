# Manual Steps Checklist — Harpua2001 eBay Site

Generated 2026-05-17 after a long ship-everything session. Every item here is
something **CC can't do for JC** — either it needs your eBay/Google/AWS login,
a real-world action (camera), or a one-time consent click.

Order is roughly by ROI per minute spent.

---

## 🔥 Tier 1 — Do today (highest revenue impact)

### 1. Upload the eBay storefront banner (3 min)

The banner is already in the repo at `docs/ebay_billboard.jpg` (1200×270, ready).

1. Open https://www.ebay.com/sh/store-design (eBay Seller Hub → Store → Design)
2. Click **Billboard / Header image** → Upload → select `docs/ebay_billboard.jpg`
3. Save

While you're there, **also** set the **Description** field at
https://www.ebay.com/sh/store-info — paste this:

> Sports and Pokemon cards from a 27-year eBay member. Football, Basketball, Baseball, Pokemon TCG — singles, lots, and graded. Combined shipping ($0.50 each additional, $5 cap). Fast US ship. 100% positive feedback.

(Trading API SetStore is deprecated, both fields are UI-only now.)

### 2. Reshoot top 5 listings (15-20 min on your phone)

Single biggest Cassini search-rank lever left. Every listing has 1 photo at
500px — eBay's algo de-ranks for <8 photos at <1600px.

Open https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/photo_upload.html on
your phone. Drag in 8+ photos at 1600×1600+ for these (sorted by margin
priority):

| Priority | Item ID | Title | Price |
|---|---|---|---|
| 1 | `306939333836` | Cam Ward Pink X-Fractor Mega Exclusive | $31.23 |
| 2 | `306937677187` | (see photo_upload.html for current title) | $16.99 |
| 3 | `306931446668` | | $13.99 |
| 4 | `306937452121` | Joe Burrow & Justin Jefferson 1/1 King | $13.13 |
| 5 | `306913934898` | | $10.00 |

(Note: photo_upload.html's "Push" button needs the Lambda route deployed —
see Tier 2 below. Until then it stages photos in the browser; you can also
upload them directly via eBay's listing-edit page on your phone.)

### 3. Export your SportsCardsPro collection (2 min)

This connects your real inventory to the eBay drafting flow.

1. Log into https://www.sportscardspro.com
2. Go to **My Collection** → **Export to CSV**
3. Drop the file in the repo root at `~/Documents/GitHub/jason_chletsos_ebay_lots/`
4. Run: `python3 scp_sync_agent.py --import-scp YOUR_FILENAME.csv`

That populates `inventory.csv` with your real cards and the "My Inventory"
page at https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/inventory.html
fills with proper data instead of the 3 sample rows.

---

## 🛠 Tier 2 — Lambda deploys (one-time, ~10 min total)

These light up several agents that currently 404 because their Lambda
routes aren't deployed yet.

### 4. Refresh AWS SSO + deploy Lambda

```bash
aws sso login --profile pokemon-app          # browser opens
cd ~/Documents/GitHub/jason_chletsos_ebay_lots/ebay_notifications
./deploy.sh
```

That ships these new routes:
- `/ebay/sync-store-categories` (Phase 2 store sync)
- `/ebay/sync-promoted` (Promoted Listings bid push)
- `/ebay/best-offer-bulk` (Best Offer bulk apply)
- `/ebay/create-listing` (inventory page draft button)
- `/ebay/ai-chat` (AI assistant chat backend)
- `/ebay/upload-photos` (photo reshoot helper push button)
- `/ebay/preview-store-categories` (read-only categories preview)
- `/ebay/promotion-rollup` (promotions echo + summary)

### 5. Add ANTHROPIC_API_KEY to Lambda env vars

Without this, the AI Assistant page (`/assistant.html`) 503s. Once added,
the chat actually responds.

1. AWS Console → Lambda → your function → Configuration → Environment variables
2. Add key `ANTHROPIC_API_KEY` with value from https://console.anthropic.com/settings/keys
3. Re-run `./deploy.sh` (or just save in console)

---

## 💰 Tier 3 — Affiliate revenue (sign-up needed, free)

### 6. Sign up for eBay Partner Network

Every outbound eBay link on the site is already wrapped with EPN tracking
params — but they're inert until you add your campaign ID.

1. Sign up: https://partnernetwork.ebay.com (free)
2. Once approved (usually same day), get your **Campaign ID**
3. Edit `configuration.json` in the repo root, add:
   ```json
   "epn_campid": "YOUR_CAMPAIGN_ID"
   ```
4. Next site rebuild: every outbound eBay click earns you 1-6% affiliate commission.

(Site already excludes own-store URLs from the wrap — eBay's self-affiliate
ban can't trigger.)

### 7. Submit Google feed (free Google Shopping)

Your product feed at https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/google_feed.xml
is already valid + auto-refreshes on every build.

1. Sign up: https://merchants.google.com (free)
2. Add your business
3. Products → Feeds → Add feed → **Scheduled fetch** → paste the URL
4. Fetch frequency: Daily
5. Run a fetch immediately — Google approves products usually within 1-2 days

That adds your listings to Google Shopping (free placement) AND to Google
search results when buyers search for specific cards.

---

## 🔑 Tier 4 — Token re-mint (one-time, 2 min)

### 8. Re-mint OAuth refresh token with sell.negotiation scope

`watchers_offer_agent.py --apply` currently fails with HTTP 403 because the
existing refresh token wasn't minted with `sell.negotiation` scope. 15 of
your watchers are sitting unanswered — these are the highest-intent buyers
in your pipeline.

1. Add your **RuName** to `configuration.json`:
   ```json
   "ru_name": "Jason_Chletsos-JasonChl-..."
   ```
   (Find it in eBay Developer Portal → Application Keysets → User Tokens → RuName)
2. Run: `python3 oauth_remint_helper.py`
3. Copy the printed consent URL → open in browser → approve all scopes
4. eBay redirects to your Lambda's `/ebay/oauth/callback` which auto-stores
   the new token
5. Run: `python3 watchers_offer_agent.py --apply` — sends offers to all 15
   watchers

---

## 📝 Tier 5 — Optional / when bored

### 9. Cross-post to Reddit + Craigslist

Both pages are ready with curated, ready-to-paste copy:
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/reddit.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/craigslist.html

Reddit has 7 curated subs (r/SportsCardSales is the big one) with formatted
[WTS] posts. Craigslist needs your city set in the dropdown to generate the
right URLs.

### 10. Daily routine (after all the above lights up)

```bash
cd ~/Documents/GitHub/jason_chletsos_ebay_lots
python3 promote.py                              # full rebuild + push to GitHub Pages
python3 promote.py --reprice-apply              # apply any new price changes
python3 specifics_agent.py --apply --no-fetch   # fill any new specifics gaps
python3 best_offer_autorespond_agent.py --apply # respond to pending offers
python3 message_responder_agent.py --apply      # respond to buyer messages
```

That keeps the store optimized daily. ~5 minutes total over coffee.

---

## What's already live (no action needed)

- ✅ Repricing: 50 listings adjusted to market value today
- ✅ Specifics: 98 listings updated with Cassini-critical Item Specifics
- ✅ Title fixes: 6 listings cleaned (4 still locked from rate limits — will clear in 24h)
- ✅ Store custom categories: 7 created + 125/128 listings assigned
- ✅ Promoted Listings: 92/128 listings (72% of catalog) ad-eligible across SMART + new Priority campaign
- ✅ Best Offer enabled on 6 listings with auto-accept/decline thresholds
- ✅ Site banner: rendered on homepage at index.html
- ✅ Social media meta: every page has OG + Twitter cards
- ✅ JSON-LD product schema on every item page (Google Shopping rich results)
- ✅ Combined shipping rule: derived but needs Seller Hub UI setup (API endpoint flaky)

## Pages JC's son can visit (no login)

- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/pokemon.html (landing for all 5 characters)
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/pikachu.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/charizard.html (top grail: $18,000 Base Set Shadowless 1st Ed)
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/mew.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/mewtwo.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/eevee.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/pokemon_news.html (Monochrome BWR + 7 upcoming sets)
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/under_10.html
- https://fivetran-jasonchletsos.github.io/jason_chletsos_ebay_lots/price_drops.html

---

CC out. Enjoy dinner JC.
