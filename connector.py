"""
eBay Seller Data — Fivetran Connector SDK
==========================================
Syncs 5 tables for seller Harpua2001:
  1. active_listings        — built from orders + ad listing IDs, enriched via eBay item lookup
  2. listing_performance    — analytics traffic report (30-day rolling window)
  3. orders                 — fulfillment orders (incremental)
  4. promoted_listings      — ad campaigns + ads
  5. seller_standards       — seller performance profile

Key findings from API exploration:
  - Listings were created via legacy Sell flow (not Inventory API) → total=0 from inventory_item
  - Active listing IDs are sourced from orders (legacyItemId) + promoted ads (listingId)
  - Browse API item lookup returns 403 with user token → use listing data embedded in orders/ads
  - Traffic report requires filter=marketplace_ids:{EBAY_US},date_range:[...]
  - Seller standards returns standardsProfiles list with metrics array
"""

import json
import time
import base64
import re
from datetime import datetime, timezone, timedelta

import requests
from fivetran_connector_sdk import Connector, Operations as op, Logging as log


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PROD_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
PROD_BASE      = "https://api.ebay.com"

OAUTH_SCOPES = " ".join([
    "https://api.ebay.com/oauth/api_scope/sell.inventory.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.fulfillment.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.analytics.readonly",
    "https://api.ebay.com/oauth/api_scope/sell.marketing.readonly",
    "https://api.ebay.com/oauth/api_scope/commerce.identity.readonly",
])

PAGE_SIZE        = 50
RATE_LIMIT_SLEEP = 0.2
MAX_RETRIES      = 3


# ---------------------------------------------------------------------------
# Token Management
# ---------------------------------------------------------------------------

def get_access_token(configuration: dict) -> str:
    client_id     = configuration["client_id"]
    client_secret = configuration["client_secret"]
    refresh_token = configuration["refresh_token"]

    encoded = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {encoded}",
        "Content-Type":  "application/x-www-form-urlencoded",
    }
    payload = {
        "grant_type":    "refresh_token",
        "refresh_token": refresh_token,
        "scope":         OAUTH_SCOPES,
    }

    resp = requests.post(PROD_TOKEN_URL, headers=headers, data=payload, timeout=30)

    if resp.status_code == 401:
        log.severe("Token refresh 401 — check client_id / client_secret / refresh_token.")
        raise RuntimeError("eBay OAuth 401")
    if resp.status_code == 403:
        log.severe("Token refresh 403 — verify OAuth scopes are approved.")
        raise RuntimeError("eBay OAuth 403")

    resp.raise_for_status()
    token = resp.json().get("access_token")
    if not token:
        raise RuntimeError(f"No access_token in response: {resp.json()}")

    log.info("Access token refreshed successfully.")
    return token


# ---------------------------------------------------------------------------
# HTTP Helper with Retry
# ---------------------------------------------------------------------------

def _request(method: str, url: str, headers: dict,
             params: dict = None, json_body: dict = None, timeout: int = 30) -> requests.Response:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.request(method, url, headers=headers,
                                    params=params, json=json_body, timeout=timeout)
        except requests.exceptions.RequestException as exc:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** attempt)
            continue

        if resp.status_code == 401:
            log.severe(f"401 on {url}")
            raise RuntimeError(f"eBay 401 on {url}")
        if resp.status_code == 403:
            log.severe(f"403 on {url} — scope missing or access denied")
            raise RuntimeError(f"eBay 403 on {url}")
        if resp.status_code == 429:
            wait = min(2 ** attempt, 60)
            log.warning(f"Rate limited (429), sleeping {wait}s")
            time.sleep(wait)
            continue
        if resp.status_code in (500, 503):
            if attempt == MAX_RETRIES:
                resp.raise_for_status()
            log.warning(f"Server error {resp.status_code}, retrying in 2s")
            time.sleep(2)
            continue

        resp.raise_for_status()
        return resp

    raise RuntimeError(f"Max retries exceeded for {url}")


# ---------------------------------------------------------------------------
# Pagination Helper
# ---------------------------------------------------------------------------

def paginate(url: str, headers: dict, params: dict = None):
    """
    Yields one page of JSON response at a time.
    Handles eBay's offset/total pagination pattern.
    """
    params = dict(params or {})
    params.setdefault("limit", PAGE_SIZE)
    offset = 0

    while True:
        params["offset"] = offset
        log.info(f"GET {url} offset={offset}")
        resp = _request("GET", url, headers=headers, params=params)
        data = resp.json()
        yield data

        total = data.get("total", 0)
        offset += PAGE_SIZE
        if offset >= total:
            break

        time.sleep(RATE_LIMIT_SLEEP)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def schema(configuration: dict):
    return [
        {
            "table": "active_listings",
            "primary_key": ["listing_id"],
            "columns": {
                "listing_id":            "STRING",
                "title":                 "STRING",
                "category_id":           "STRING",
                "condition":             "STRING",
                "price":                 "FLOAT",
                "currency":              "STRING",
                "quantity_available":    "INT",
                "listing_status":        "STRING",
                "listing_format":        "STRING",
                "listing_url":           "STRING",
                "image_urls":            "STRING",
                "item_specifics":        "STRING",
                "last_seen_in_orders":   "UTC_DATETIME",
                "last_seen_in_ads":      "BOOLEAN",
            },
        },
        {
            "table": "listing_performance",
            "primary_key": ["listing_id", "date"],
            "columns": {
                "listing_id":                     "STRING",
                "date":                           "STRING",
                "impressions":                    "INT",
                "clicks":                         "INT",
                "click_through_rate":             "FLOAT",
                "page_views":                     "INT",
                "conversion_rate":                "FLOAT",
                "top_20_search_slot_impressions": "INT",
            },
        },
        {
            "table": "orders",
            "primary_key": ["order_id"],
            "columns": {
                "order_id":           "STRING",
                "legacy_order_id":    "STRING",
                "listing_id":         "STRING",
                "buyer_username":     "STRING",
                "sale_price":         "FLOAT",
                "shipping_cost":      "FLOAT",
                "total_amount":       "FLOAT",
                "currency":           "STRING",
                "order_status":       "STRING",
                "payment_status":     "STRING",
                "created_date":       "UTC_DATETIME",
                "last_modified_date": "UTC_DATETIME",
                "shipping_carrier":   "STRING",
                "tracking_number":    "STRING",
                "item_title":         "STRING",
                "sku":                "STRING",
                "quantity":           "INT",
                "sales_record_ref":   "STRING",
            },
        },
        {
            "table": "promoted_listings",
            "primary_key": ["campaign_id", "ad_id"],
            "columns": {
                "campaign_id":     "STRING",
                "campaign_name":   "STRING",
                "campaign_status": "STRING",
                "ad_id":           "STRING",
                "listing_id":      "STRING",
                "bid_percentage":  "FLOAT",
                "funding_model":   "STRING",
                "start_date":      "STRING",
                "end_date":        "STRING",
            },
        },
        {
            "table": "seller_standards",
            "primary_key": ["snapshot_date", "program"],
            "columns": {
                "snapshot_date":                   "STRING",
                "program":                         "STRING",
                "overall_status":                  "STRING",
                "evaluation_reason":               "STRING",
                "defect_rate":                     "FLOAT",
                "defect_count":                    "INT",
                "defect_denominator":              "INT",
                "late_shipment_rate":              "FLOAT",
                "cases_closed_without_resolution": "FLOAT",
                "transaction_count":               "INT",
                "gmv":                             "FLOAT",
                "eligible_for_top_rated_plus":     "BOOLEAN",
            },
        },
    ]


# ---------------------------------------------------------------------------
# Sync: Active Listings
# Sourced from order line items + promoted ad listing IDs
# since legacy listings don't appear in the Inventory API
# ---------------------------------------------------------------------------

def sync_active_listings(base_url: str, headers: dict, state: dict,
                          order_listings: dict, ad_listing_ids: set):
    """
    Builds active_listings from two sources:
      1. order_listings: {listing_id -> {title, price, currency, condition, ...}} from order line items
      2. ad_listing_ids: set of listing IDs from promoted ads

    Merges both sets and emits one record per unique listing_id.
    """
    # Merge ad listing IDs into the order_listings dict (may not have full detail)
    all_listing_ids = set(order_listings.keys()) | ad_listing_ids

    for listing_id in all_listing_ids:
        detail = order_listings.get(listing_id, {})

        # Build listing URL
        listing_url = f"https://www.ebay.com/itm/{listing_id}" if listing_id else ""

        record = {
            "listing_id":          listing_id,
            "title":               detail.get("title", ""),
            "category_id":         detail.get("category_id", ""),
            "condition":           detail.get("condition", ""),
            "price":               detail.get("price", 0.0),
            "currency":            detail.get("currency", "USD"),
            "quantity_available":  detail.get("quantity_available", 0),
            "listing_status":      detail.get("listing_status", "ACTIVE"),
            "listing_format":      detail.get("listing_format", "FIXED_PRICE"),
            "listing_url":         listing_url,
            "image_urls":          detail.get("image_urls", "[]"),
            "item_specifics":      detail.get("item_specifics", "{}"),
            "last_seen_in_orders": detail.get("last_seen_in_orders"),
            "last_seen_in_ads":    listing_id in ad_listing_ids,
        }
        yield record


# ---------------------------------------------------------------------------
# Sync: Listing Performance (Traffic Report)
# ---------------------------------------------------------------------------

def sync_listing_performance(base_url: str, headers: dict, state: dict):
    """
    Pulls 30-day rolling traffic report.
    eBay returns dimension/metric values positionally by index — not by key name.
    Use the header to build index maps.
    dimension=LISTING gives one row per listing (115 listings found in testing).
    """
    end_dt   = datetime.now(timezone.utc)
    start_dt = end_dt - timedelta(days=30)
    start_s  = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    end_s    = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    url = f"{base_url}/sell/analytics/v1/traffic_report"
    params = {
        "dimension": "LISTING",
        "metric":    ",".join([
            "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE",
            "LISTING_VIEWS_TOTAL",
            "TRANSACTION",
            "CLICK_THROUGH_RATE",
        ]),
        "filter": f"marketplace_ids:{{EBAY_US}},date_range:[{start_s}..{end_s}]",
    }

    try:
        resp = _request("GET", url, headers=headers, params=params)
        data = resp.json()
    except Exception as exc:
        log.warning(f"Traffic report failed: {exc}")
        return

    # Build index maps from header
    header      = data.get("header", {})
    dim_keys    = [d.get("key", "") for d in header.get("dimensionKeys", [])]
    metric_keys = [m.get("key", "") for m in header.get("metrics", [])]

    log.info(f"Traffic report dimensions: {dim_keys}")
    log.info(f"Traffic report metrics:    {metric_keys}")

    records = data.get("records", [])
    log.info(f"Traffic report: {len(records)} listing records returned")

    # Metric index lookups
    def _idx(keys, name):
        return keys.index(name) if name in keys else -1

    imp_idx  = _idx(metric_keys, "LISTING_IMPRESSION_SEARCH_RESULTS_PAGE")
    view_idx = _idx(metric_keys, "LISTING_VIEWS_TOTAL")
    txn_idx  = _idx(metric_keys, "TRANSACTION")
    ctr_idx  = _idx(metric_keys, "CLICK_THROUGH_RATE")

    # Use today as the date since dimension=LISTING aggregates across the date range
    date_str = end_dt.strftime("%Y-%m-%d")

    for record in records:
        dim_vals    = record.get("dimensionValues", [])
        metric_vals = record.get("metricValues", [])

        # First dimension value is the listing ID
        listing_id = dim_vals[0].get("value", "") if dim_vals else ""
        if not listing_id:
            continue

        def _mval(idx, default=0):
            if idx < 0 or idx >= len(metric_vals):
                return default
            v = metric_vals[idx].get("value", default)
            return v if v is not None else default

        impressions = int(_mval(imp_idx, 0))
        page_views  = int(_mval(view_idx, 0))
        clicks      = int(_mval(txn_idx, 0))
        ctr         = float(_mval(ctr_idx, 0.0))
        conv        = round(clicks / impressions, 4) if impressions > 0 else 0.0

        yield {
            "listing_id":                     listing_id,
            "date":                           date_str,
            "impressions":                    impressions,
            "clicks":                         clicks,
            "click_through_rate":             ctr,
            "page_views":                     page_views,
            "conversion_rate":                conv,
            "top_20_search_slot_impressions": impressions,  # search results page impressions = top slot proxy
        }


# ---------------------------------------------------------------------------
# Sync: Orders
# ---------------------------------------------------------------------------

def sync_orders(base_url: str, headers: dict, state: dict):
    """
    Incremental sync using creationdate filter.
    Also builds order_listings dict and ad_listing_ids set for active_listings table.
    Yields (record, new_cursor, order_listings_dict) tuples.
    """
    cursor = state.get("orders_cursor", "")
    if not cursor:
        start_dt = datetime.now(timezone.utc) - timedelta(days=365)
        cursor   = start_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    end_dt  = datetime.now(timezone.utc)
    end_str = end_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    url    = f"{base_url}/sell/fulfillment/v1/order"
    params = {
        "filter":           f"creationdate:[{cursor}..{end_str}]",
        "orderingSortOrder": "ASC",
    }

    latest_cursor  = cursor
    order_listings = {}  # listing_id -> enriched detail dict

    for page in paginate(url, headers, params):
        orders = page.get("orders", [])
        for order in orders:
            order_id      = order.get("orderId", "")
            legacy_id     = order.get("legacyOrderId", "")
            created_date  = order.get("creationDate", "")
            modified_date = order.get("lastModifiedDate", created_date)

            if modified_date and modified_date > latest_cursor:
                latest_cursor = modified_date

            buyer         = order.get("buyer", {})
            buyer_username = buyer.get("username", "")

            pricing       = order.get("pricingSummary", {})
            subtotal      = pricing.get("priceSubtotal", {})
            delivery      = pricing.get("deliveryCost", {})
            total         = pricing.get("total", {})

            sale_price    = float(subtotal.get("value", 0.0) or 0.0)
            shipping_cost = float(delivery.get("shippingCost", {}).get("value", 0.0) or 0.0)
            total_amount  = float(total.get("value", 0.0) or 0.0)
            currency      = total.get("currency", "USD") or "USD"

            order_status  = order.get("orderFulfillmentStatus", "")
            payment_status = order.get("orderPaymentStatus", "")
            sales_record  = order.get("salesRecordReference", "")

            # Shipping / tracking from fulfillment instructions
            shipping_carrier = ""
            tracking_number  = ""
            for instr in order.get("fulfillmentStartInstructions", []):
                step = instr.get("shippingStep", {})
                shipping_carrier = step.get("shippingCarrierCode", "")
                if shipping_carrier:
                    break

            # Line items
            line_items  = order.get("lineItems", [])
            listing_id  = ""
            item_title  = ""
            sku         = ""
            quantity    = 0
            unit_price  = 0.0
            condition   = ""
            category_id = ""

            if line_items:
                first       = line_items[0]
                listing_id  = first.get("legacyItemId", "")
                item_title  = first.get("title", "")
                sku         = first.get("sku", "")
                quantity    = int(first.get("quantity", 1))
                lp          = first.get("lineItemCost", {})
                unit_price  = float(lp.get("value", 0.0) or 0.0)
                condition   = first.get("legacyVariationId", "")  # best proxy available
                category_id = first.get("categoryId", "")

                # Accumulate listing detail for active_listings table
                if listing_id:
                    if listing_id not in order_listings or created_date > order_listings[listing_id].get("last_seen_in_orders", ""):
                        order_listings[listing_id] = {
                            "title":               item_title,
                            "price":               unit_price,
                            "currency":            currency,
                            "condition":           condition,
                            "category_id":         category_id,
                            "quantity_available":  0,
                            "listing_status":      "ACTIVE",
                            "listing_format":      "FIXED_PRICE",
                            "image_urls":          "[]",
                            "item_specifics":      "{}",
                            "last_seen_in_orders": created_date,
                        }

            record = {
                "order_id":           order_id,
                "legacy_order_id":    legacy_id,
                "listing_id":         listing_id,
                "buyer_username":     buyer_username,
                "sale_price":         sale_price,
                "shipping_cost":      shipping_cost,
                "total_amount":       total_amount,
                "currency":           currency,
                "order_status":       order_status,
                "payment_status":     payment_status,
                "created_date":       created_date or None,
                "last_modified_date": modified_date or None,
                "shipping_carrier":   shipping_carrier,
                "tracking_number":    tracking_number,
                "item_title":         item_title,
                "sku":                sku,
                "quantity":           quantity,
                "sales_record_ref":   sales_record,
            }

            yield record, latest_cursor, order_listings


# ---------------------------------------------------------------------------
# Sync: Promoted Listings
# ---------------------------------------------------------------------------

def sync_promoted_listings(base_url: str, headers: dict, state: dict):
    """
    Fetches all campaigns and their ads.
    Returns (records_generator, ad_listing_ids_set).
    """
    url            = f"{base_url}/sell/marketing/v1/ad_campaign"
    ad_listing_ids = set()

    for page in paginate(url, headers, {"limit": PAGE_SIZE}):
        campaigns = page.get("campaigns", [])
        for campaign in campaigns:
            campaign_id     = campaign.get("campaignId", "")
            campaign_name   = campaign.get("campaignName", "")
            campaign_status = campaign.get("campaignStatus", "")
            start_date      = campaign.get("startDate", "")
            end_date        = campaign.get("endDate", "")
            funding         = campaign.get("fundingStrategy", {})
            funding_model   = funding.get("fundingModel", "")

            # Fetch ads for this campaign
            ads_url = f"{base_url}/sell/marketing/v1/ad_campaign/{campaign_id}/ad"
            try:
                for ads_page in paginate(ads_url, headers, {"limit": PAGE_SIZE}):
                    for ad in ads_page.get("ads", []):
                        ad_id      = ad.get("adId", "")
                        listing_id = ad.get("listingId", "")
                        bid_pct    = float(ad.get("bidPercentage", 0.0) or 0.0)

                        if listing_id:
                            ad_listing_ids.add(listing_id)

                        yield {
                            "campaign_id":     campaign_id,
                            "campaign_name":   campaign_name,
                            "campaign_status": campaign_status,
                            "ad_id":           ad_id,
                            "listing_id":      listing_id,
                            "bid_percentage":  bid_pct,
                            "funding_model":   funding_model,
                            "start_date":      start_date,
                            "end_date":        end_date,
                        }, ad_listing_ids

            except Exception as exc:
                log.warning(f"Failed to fetch ads for campaign {campaign_id}: {exc}")


# ---------------------------------------------------------------------------
# Sync: Seller Standards
# ---------------------------------------------------------------------------

def sync_seller_standards(base_url: str, headers: dict, state: dict):
    url = f"{base_url}/sell/analytics/v1/seller_standards_profile"
    try:
        resp = _request("GET", url, headers=headers)
        data = resp.json()
    except Exception as exc:
        log.warning(f"Seller standards failed: {exc}")
        return

    profiles      = data.get("standardsProfiles", [data])
    snapshot_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for profile in profiles:
        overall_status   = profile.get("standardsLevel", "UNKNOWN")
        program          = profile.get("program", "PROGRAM_US")
        eval_reason      = profile.get("evaluationReason", "")
        default_program  = profile.get("defaultProgram", False)

        # Use cycle date if available
        cycle = profile.get("cycle", {})
        if cycle.get("evaluationDate"):
            snapshot_date = cycle["evaluationDate"][:10]

        # Parse metrics list
        metrics_list = profile.get("metrics", [])
        metrics      = {}
        for m in metrics_list:
            key = m.get("metricKey", "")
            val = m.get("value", {})
            metrics[key] = val

        def _rate(key):
            v = metrics.get(key, {})
            if isinstance(v, dict):
                return float(v.get("value", 0.0) or 0.0)
            return float(v or 0.0)

        def _int_val(key, sub="value"):
            v = metrics.get(key, {})
            if isinstance(v, dict):
                return int(v.get(sub, 0) or 0)
            return int(v or 0)

        defect_rate  = _rate("DEFECTIVE_TRANSACTION_RATE")
        defect_count = _int_val("DEFECTIVE_TRANSACTION_RATE", "numerator")
        defect_denom = _int_val("DEFECTIVE_TRANSACTION_RATE", "denominator")
        late_rate    = _rate("LATE_SHIPMENT_RATE")
        cases_rate   = _rate("CASES_CLOSED_WITHOUT_SELLER_RESOLUTION")
        txn_count    = _int_val("MIN_TXN_COUNT")
        gmv_raw      = metrics.get("MIN_GMV", {})
        gmv          = float(gmv_raw.get("value", 0.0) if isinstance(gmv_raw, dict) else 0.0)

        yield {
            "snapshot_date":                   snapshot_date,
            "program":                         program,
            "overall_status":                  overall_status,
            "evaluation_reason":               eval_reason,
            "defect_rate":                     defect_rate,
            "defect_count":                    defect_count,
            "defect_denominator":              defect_denom,
            "late_shipment_rate":              late_rate,
            "cases_closed_without_resolution": cases_rate,
            "transaction_count":               txn_count,
            "gmv":                             gmv,
            "eligible_for_top_rated_plus":     default_program,
        }


# ---------------------------------------------------------------------------
# Update (main sync entry point)
# ---------------------------------------------------------------------------

def update(configuration: dict, state: dict):
    log.info("Starting eBay seller sync for Harpua2001...")

    access_token = get_access_token(configuration)
    base_url     = PROD_BASE
    headers      = {
        "Authorization":          f"Bearer {access_token}",
        "Content-Type":           "application/json",
        "Accept":                 "application/json",
        "X-EBAY-C-MARKETPLACE-ID": "EBAY_US",
    }

    # ------------------------------------------------------------------
    # 1. Orders — sync first to build listing metadata map
    # ------------------------------------------------------------------
    log.info("Syncing orders...")
    latest_orders_cursor = state.get("orders_cursor", "")
    orders_count         = 0
    order_listings       = {}  # listing_id -> detail, built during order sync

    try:
        for record, new_cursor, ol_map in sync_orders(base_url, headers, state):
            yield op.upsert("orders", record)
            orders_count += 1
            order_listings.update(ol_map)

            if new_cursor > latest_orders_cursor:
                latest_orders_cursor = new_cursor

            if orders_count % 50 == 0:
                state = {**state, "orders_cursor": latest_orders_cursor}
                yield op.checkpoint(state)

        state = {**state, "orders_cursor": latest_orders_cursor}
        yield op.checkpoint(state)
        log.info(f"orders: {orders_count} records synced. {len(order_listings)} unique listings found.")
    except Exception as exc:
        log.severe(f"orders sync failed: {exc}")
        raise

    # ------------------------------------------------------------------
    # 2. Promoted Listings — also collects ad_listing_ids
    # ------------------------------------------------------------------
    log.info("Syncing promoted_listings...")
    promo_count    = 0
    ad_listing_ids = set()

    try:
        for record, current_ad_ids in sync_promoted_listings(base_url, headers, state):
            yield op.upsert("promoted_listings", record)
            promo_count += 1
            ad_listing_ids = current_ad_ids

            if promo_count % 50 == 0:
                yield op.checkpoint(state)

        yield op.checkpoint(state)
        log.info(f"promoted_listings: {promo_count} records synced. {len(ad_listing_ids)} unique ad listing IDs.")
    except Exception as exc:
        log.severe(f"promoted_listings sync failed: {exc}")
        raise

    # ------------------------------------------------------------------
    # 3. Active Listings — built from orders + ads data
    # ------------------------------------------------------------------
    log.info("Syncing active_listings...")
    listings_count = 0

    try:
        for record in sync_active_listings(base_url, headers, state, order_listings, ad_listing_ids):
            yield op.upsert("active_listings", record)
            listings_count += 1

        yield op.checkpoint(state)
        log.info(f"active_listings: {listings_count} records synced.")
    except Exception as exc:
        log.severe(f"active_listings sync failed: {exc}")
        raise

    # ------------------------------------------------------------------
    # 4. Listing Performance (Traffic Report)
    # ------------------------------------------------------------------
    log.info("Syncing listing_performance...")
    perf_count = 0

    try:
        for record in sync_listing_performance(base_url, headers, state):
            yield op.upsert("listing_performance", record)
            perf_count += 1

        yield op.checkpoint(state)
        log.info(f"listing_performance: {perf_count} records synced.")
    except Exception as exc:
        log.severe(f"listing_performance sync failed: {exc}")
        raise

    # ------------------------------------------------------------------
    # 5. Seller Standards
    # ------------------------------------------------------------------
    log.info("Syncing seller_standards...")
    standards_count = 0

    try:
        for record in sync_seller_standards(base_url, headers, state):
            yield op.upsert("seller_standards", record)
            standards_count += 1

        yield op.checkpoint(state)
        log.info(f"seller_standards: {standards_count} records synced.")
    except Exception as exc:
        log.severe(f"seller_standards sync failed: {exc}")
        raise

    log.info(f"Sync complete — orders={orders_count}, listings={listings_count}, "
             f"performance={perf_count}, promoted={promo_count}, standards={standards_count}")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
connector = Connector(update=update, schema=schema)

if __name__ == "__main__":
    connector.debug()
