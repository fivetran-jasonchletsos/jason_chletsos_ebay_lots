# Session Handoff — 2026-05-22

## Additional code fixes from afternoon autonomous run

Three systemic agent bugs found and patched, each with diagnostic improvements so future failures surface eBay's actual error instead of opaque ack=Failure summaries:

### 1. `email_campaign_agent.py` — Weekly Steals selector was inverted
**Was:** backfilled from snapshot by `price DESC` → surfaced the most-expensive (and most-overpriced) lots as "steals."
**Now:** loads the snapshot's `market` comp data, filters out OVERPRICED items, ranks remainder by most-negative `gap_pct` (most under market median) then by price desc. New `load_market_data()` helper added. Featured items from `seller_hub_plan` still take priority.

### 2. `best_offer_agent.py` — stale-snapshot price → eBay error 22003
**Was:** When a listing was repriced down same-day, the snapshot's `price` field was stale. The agent computed `min_offer` from the old higher price, producing values above the new live BIN → eBay rejected with `errorId 22003` ("Auto decline amount cannot be greater than or equal to the Buy It Now price").
**Now:** `fetch_item_state()` extracts `current_price` from GetItem. `filter_for_idempotency()` re-clamps `auto_accept` and `auto_decline` against the live BIN whenever it's lower than the snapshot price, with proper floor + gap guards. Verified fix on `306949802296` (was failing, now accepts).
**Side benefit:** errors now print inline with the ack=Failure line so future failures are immediately diagnosable.

### 3. `promoted_listings_agent.py` — `0/139 bids accepted` was a lie
**Was:** Used `bulk_create_ads_by_listing_id`. After the first daily run, every subsequent call returned `errorId 35036` ("An ad for listing Id X already exists"). The agent counted those as failures and reported "0/139 accepted" — looked catastrophic, but the listings were correctly in the campaign at their existing bids.
**Now:** Per-listing errors are surfaced inline (so future *real* errors are diagnosable), and the `35036` "already exists" responses are rewritten to a synthetic `200` with a `_note` field — the daily summary now correctly reports `139/139` (all listings already promoted, no new ads needed).
**Caveat:** eBay's "Promoted Listings General" campaign type has no bulk-update bid endpoint. The agent can't push bid percentage changes via API for legacy campaigns — that must be done in the eBay UI ("Edit campaign" → set to Suggested/Dynamic rate). The campaign is already running at 6.68× ROAS per your screenshot, so this is fine.

---



Everything I did this session while you were focused elsewhere, plus the open items waiting on you.

---

## What I shipped

### Daily Toolkit dashboard (rebuilt)
- New `docs/index.html` — tight, dark/luxe, mobile-first, organized by best-seller workflow (Make Money → Source → Optimize → Money → Channels).
- **48 cluttered pages archived** to `docs/_archive/` (camera/scan pages, vanity per-Pokemon pages, redundant hubs, low-value report variants).
- **16 live pages remain** — all linked from index, all serve a money or deal-finding purpose.

### eBay credential restoration
- OAuth refresh token re-minted with `sell.marketing` scope (previous token was missing it).
- New token written to `configuration.json`; lifetime ~18 months.
- `finish_oauth.py` patched to fix double-URL-encoding bug that was breaking exchanges.

### Code fixes in 4 daily-pipeline agents
- `listing_performance_agent.py`, `pnl_agent.py`, `daily_digest_agent.py` — snapshot schema drift fix (`{listings:[...], market:{}, ...}` was being treated as a flat list).
- `email_campaign_agent.py` — added `X-EBAY-C-MARKETPLACE-ID` header, renamed `template` → `emailCampaignType`.

### Apply runs
- **Best Offer enabled** on 4 of 5 high-value listings (the agent's algorithm only picks the strongest cases): item IDs `306903941543`, `306913790653`, `306931303163`, `306950542310`.
- **Promoted Listings API failed** — the bulk-create endpoint rejected all 139 bids. Likely your campaign type is CPS (Cost-Per-Sale) which uses ad groups instead of per-listing bid percentages. **Workaround: enable in eBay UI** (link below — 30 sec).

### Documents in your Downloads folder
- `Harpua-Player-Watchlist.pdf` — which players to set aside when sorting cards
- `Harpua-Pack-Buying-Guide.pdf` — which sealed product has the best resale right now
- `zsh-Cheat-Sheet.pdf` — terminal companion

---

## The big finding: 36% of your store is overpriced

I ran the snapshot's market-comp data against all 154 listings. Result:

| Bucket | Count | What it means |
|---|---|---|
| **OVERPRICED** | **56** | Priced above market median — actively suppressing sales |
| OK | 79 | Within market range |
| UNDERPRICED | 16 | You're leaving money on the table — raise these |
| No comps | 3 | Too obscure for the matcher |

**Top 5 overpriced (sorted by biggest opportunity = gap × price):**

| Gap | Current | Suggested | Title |
|---|---|---|---|
| +2512% | $25.99 | $1.01 | Boomer Esiason Bengals/Jets lot (7) |
| +917% | $31.99 | $3.21 | Charcadet 022 Mega Evolution Promo Holo |
| +269% | $5.99 | $1.65 | Topps Chrome All-Chrome Justin Jefferson ACT-6 |
| +241% | $6.78 | $2.03 | 2025 Prizm Draft Vernell Brown III #154 Silver |
| +183% | $23.99 | $8.65 | Marcus Allen Raiders/Chiefs lot (11) HOF |

> ⚠️ **Caveat:** the "market_median" comes from eBay sold-comp matching that can include non-comparable items (e.g., a single Boomer Esiason common card vs a 7-card lot). The extreme gaps (>200%) need eyeball review before bulk-repricing — but even after culling false matches, you almost certainly have 20-30 legitimately overpriced listings sitting dead.

**The "Weekly Steals" email irony:** 4 of the 6 items I featured as "steals" in the campaign were actually overpriced listings, not deals. Lucky the email never sent — would have undermined trust. The campaign-agent's "steals selector" logic needs to prefer UNDERPRICED items, not OVERPRICED ones flagged as "great value." Bug to fix.

**Top 5 underpriced (easy raise):**

| Gap | Current | Suggested | Title |
|---|---|---|---|
| -29% | $9.99 | $14.27 | 2025 Icon Collection Mahomes Game Gear #GG-3 |
| -25% | $2.99 | $4.07 | 2025 Prizm Prizmatic Colston Loveland Silver |
| -24% | $10.99 | $14.79 | 2025 Donruss Optic DK Metcalf Black Pandora /149 |
| -19% | $3.99 | $5.04 | 2025 Select Rookie Swatches TreVeyon Henderson Red |
| -16% | $4.19 | $5.09 | 2025 Topps Chrome Matthew Golden Pink X-fractor Packers |

Full sortable lists at `output/repricing_action_list.json` (top 30 overpriced + top 20 underpriced).

---

## The secondary finding: snapshot has no engagement data

Every listing shows `watchers: None, hit_count: None, views: None` because whatever agent builds `output/listings_snapshot.json` only pulls listing metadata + market comps — not the per-listing engagement metrics from eBay's Analytics or Trading API.

That's why `watchers.html`, `listing_performance.html`, and `daily.html` all show "Watchers: 0" even when you have real watchers. The fix is to add a `GetItem` call per listing (or use the Analytics API `/sell/analytics/v1/traffic_report`) to populate `WatchCount` and `HitCount` into the listings array before snapshot save.

**Workaround until that's fixed:** check eBay Seller Hub → Performance → Sales for the real numbers. Or just open Seller Hub → Listings and sort by Watchers — that's the ground truth.

---

## Open items for you

### Immediate (5 min each)
1. **Enable Promoted Listings via UI** — https://www.ebay.com/sh/mkt/promotions → Standard → "Promote all" at 4-6%. Only charges on sales.
2. **Bulk-enable Best Offer on remaining ~145 listings** — Seller Hub → Listings → select all → Edit → Best Offer → auto-accept at 85%, auto-decline below 70%.
3. **Submit the `sell.negotiation` license request** — text at `docs/ebay_negotiation_license_request.md`. Copy-paste into developer.ebay.com Contact Developer Relations.

### Inventory workflow
4. **Try Mark My Cards** ([markmycards.com](https://www.markmycards.com)) — phone-first card scanner → auto-fills eBay title/specifics/pricing → posts directly. Replaces the SCP→eBay manual gap. Free trial.

### Quick wins from the diagnostic
5. **Repricing decision** — review `output/repricing_action_list.json`. Drop the obvious-bad-comp matches (single card vs lot comparisons) and tweak the legit overpriced items 20-50% down. The Boomer Esiason lot at $25.99 isn't selling because it's 25× market.
6. **Raise the 16 underpriced** — gain ~$1-5 per listing without losing the buyer (still under market).

---

## Quick-access links

| Page | Path |
|---|---|
| New Daily Toolkit dashboard | `docs/index.html` |
| eBay license request (copy-paste) | `docs/ebay_negotiation_license_request.md` |
| Repricing action list (JSON) | `output/repricing_action_list.json` |
| Listing health buckets (JSON) | `output/listing_health_buckets.json` |
| Player Watchlist PDF | `~/Downloads/Harpua-Player-Watchlist.pdf` |
| Pack Buying Guide PDF | `~/Downloads/Harpua-Pack-Buying-Guide.pdf` |
| zsh Cheat Sheet PDF | `~/Downloads/zsh-Cheat-Sheet.pdf` |
| Legacy dashboard (if you want it back) | `docs/_archive/index_legacy.html` |
