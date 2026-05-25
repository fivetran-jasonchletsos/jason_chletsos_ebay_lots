# eBay `sell.negotiation` OAuth Scope — Application Request

Submit at developer.ebay.com → My Account → Application Keysets → your Production app → **Contact Developer Relations** (or open a support ticket via the eBay Developer Portal help link).

---

## Application Details

**Application name:** jason_chletsos_fivetran (Production)
**App ID (Client ID):** `JasonChl-jasonchl-PRD-d8f6186d5-ea3d812b`
**Seller account:** harpua2001 (jchletsos@gmail.com)
**Requested scope:** `https://api.ebay.com/oauth/api_scope/sell.negotiation`

---

## Business Justification (paste into the request form)

> I run a small eBay sports & Pokemon card store (harpua2001) with 154 active listings. I've built an internal automation pipeline that helps me operate the store more efficiently, and I'd like to enable the Send Offer to Watchers feature programmatically via the Negotiation API.
>
> Specifically, my use case is:
>
> 1. **Watchers identification** — my pipeline already identifies listings with active watchers via the Trading API (`GetItem` + `WatchCount`). On a typical day I have 5–20 watchers across the store.
>
> 2. **Offer eligibility scoring** — for each listing with watchers, my agent computes a recommended offer amount (typically 8–15% below current list price, floored at the listing's cost basis from my Sportscards Pro inventory data).
>
> 3. **Automated offer dispatch** — I'd like to call `POST /sell/negotiation/v1/find_eligible_items` followed by `POST /sell/negotiation/v1/send_offer_to_interested_buyers` to push these offers without manually clicking through each listing in Seller Hub.
>
> 4. **Tracking** — offer outcomes (accepted, declined, expired) feed back into my P&L tracker so I can iterate on the offer-rate threshold.
>
> Without this scope, I currently have to send each Send-Offer manually through the Seller Hub UI, which is the bottleneck on roughly $3–8 per day of expected revenue uplift from watcher conversions. The agent is fully audited (dry-run mode by default, explicit `--apply` flag required to push) and offers are bounded by configured minimums to prevent runaway discounting.
>
> The corresponding agent file in my codebase: `watchers_offer_agent.py`.
>
> I'd appreciate the scope being added to my Production app keyset so I can re-mint a refresh token that includes it.

---

## What to expect after submission

- **Response time:** typically 1–3 business days for eBay Developer Relations to review.
- **If approved:** eBay updates your app's OAuth Scopes whitelist. You re-run `oauth_remint_helper.py` (with `sell.negotiation` uncommented at line 52) to mint a new refresh token. The Watchers Offer agent then works on the next daily run.
- **If they ask for more detail:** the most common follow-up is asking for a privacy policy URL covering buyer data. Your existing eBay-registered privacy URL `https://jw0hur2091.execute-api.us-east-1.amazonaws.com/health` should suffice — if not, point them at any seller-side privacy statement on your site or eBay store description.

---

## Re-enable after approval

Edit `oauth_remint_helper.py` line 52 — uncomment:

```python
"https://api.ebay.com/oauth/api_scope/sell.negotiation",
```

Then run `python3 finish_oauth.py` to re-mint and update `configuration.json`.
