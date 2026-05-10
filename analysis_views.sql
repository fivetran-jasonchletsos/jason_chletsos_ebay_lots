-- =============================================================================
-- LISTING HEALTH DASHBOARD
-- =============================================================================
-- Which listings have high impressions but low CTR?  → title/image problem
-- Which have high CTR but low conversion?            → price/description problem
-- Which have watchers but no sales?                  → fence-sitters

CREATE OR REPLACE VIEW listing_health_dashboard AS
WITH perf_30d AS (
    SELECT
        listing_id,
        SUM(impressions)                                        AS total_impressions,
        SUM(clicks)                                             AS total_clicks,
        SUM(quantity_sold)                                      AS total_units_sold,
        SUM(total_revenue)                                      AS total_revenue,
        SUM(watchers)                                           AS total_watchers,
        SUM(page_views)                                         AS total_page_views,
        -- Aggregate CTR and conversion as weighted averages
        CASE WHEN SUM(impressions) > 0
             THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions), 4)
             ELSE 0 END                                         AS agg_ctr,
        CASE WHEN SUM(clicks) > 0
             THEN ROUND(SUM(quantity_sold)::NUMERIC / SUM(clicks), 4)
             ELSE 0 END                                         AS agg_conversion_rate
    FROM listing_performance
    GROUP BY listing_id
),
listings AS (
    SELECT
        listing_id,
        title,
        price,
        currency,
        listing_status,
        listing_format,
        listing_url,
        image_urls,
        item_specifics,
        quantity_available,
        -- Count images from JSON array
        CASE
            WHEN image_urls IS NOT NULL AND image_urls != '[]'
            THEN JSON_ARRAY_LENGTH(image_urls::JSON)
            ELSE 0
        END                                                     AS image_count,
        -- Title length for quality flag
        LENGTH(title)                                           AS title_length
    FROM active_listings
    WHERE listing_status = 'ACTIVE'
)
SELECT
    l.listing_id,
    l.title,
    l.price,
    l.currency,
    l.listing_url,
    l.image_count,
    l.title_length,
    p.total_impressions,
    p.total_clicks,
    p.total_units_sold,
    p.total_revenue,
    p.total_watchers,
    p.total_page_views,
    p.agg_ctr,
    p.agg_conversion_rate,
    -- Health flags
    CASE WHEN p.total_impressions > 500 AND p.agg_ctr < 0.01
         THEN 'HIGH_IMPRESSIONS_LOW_CTR'       -- title/image problem
         WHEN p.agg_ctr > 0.03 AND p.agg_conversion_rate < 0.01
         THEN 'HIGH_CTR_LOW_CONVERSION'        -- price/description problem
         WHEN p.total_watchers > 3 AND p.total_units_sold = 0
         THEN 'WATCHERS_NO_SALES'              -- fence-sitters
         WHEN p.total_impressions < 50
         THEN 'LOW_VISIBILITY'                 -- buried in search
         ELSE 'HEALTHY'
    END                                                         AS health_flag,
    -- Quality flags
    CASE WHEN l.image_count < 2 THEN TRUE ELSE FALSE END        AS flag_few_images,
    CASE WHEN l.title_length < 60 THEN TRUE ELSE FALSE END      AS flag_short_title,
    CASE WHEN l.item_specifics IS NULL OR l.item_specifics = '{}'
         THEN TRUE ELSE FALSE END                               AS flag_missing_specifics
FROM listings l
LEFT JOIN perf_30d p ON l.listing_id = p.listing_id
ORDER BY p.total_impressions DESC NULLS LAST;


-- =============================================================================
-- CATEGORY & PRICING ANALYSIS
-- =============================================================================
-- What categories drive the most revenue?
-- Am I pricing competitively vs. my own sold history?

CREATE OR REPLACE VIEW category_pricing_analysis AS
WITH category_revenue AS (
    SELECT
        al.category_id,
        al.category_name,
        COUNT(DISTINCT al.listing_id)                           AS active_listing_count,
        SUM(o.total_amount)                                     AS total_revenue,
        SUM(o.quantity)                                         AS total_units_sold,
        AVG(o.sale_price)                                       AS avg_sale_price,
        AVG(al.price)                                           AS avg_current_price,
        MIN(o.sale_price)                                       AS min_sold_price,
        MAX(o.sale_price)                                       AS max_sold_price
    FROM active_listings al
    LEFT JOIN orders o ON al.listing_id = o.listing_id
    WHERE o.order_status NOT IN ('CANCELLED') OR o.order_status IS NULL
    GROUP BY al.category_id, al.category_name
)
SELECT
    category_id,
    category_name,
    active_listing_count,
    COALESCE(total_revenue, 0)                                  AS total_revenue,
    COALESCE(total_units_sold, 0)                               AS total_units_sold,
    ROUND(COALESCE(avg_sale_price, 0)::NUMERIC, 2)              AS avg_sale_price,
    ROUND(avg_current_price::NUMERIC, 2)                        AS avg_current_price,
    ROUND(COALESCE(min_sold_price, 0)::NUMERIC, 2)              AS min_sold_price,
    ROUND(COALESCE(max_sold_price, 0)::NUMERIC, 2)              AS max_sold_price,
    -- Price positioning: is current price above or below avg sold price?
    CASE
        WHEN avg_current_price > COALESCE(avg_sale_price, avg_current_price) * 1.1
        THEN 'PRICED_HIGH'
        WHEN avg_current_price < COALESCE(avg_sale_price, avg_current_price) * 0.9
        THEN 'PRICED_LOW'
        ELSE 'COMPETITIVELY_PRICED'
    END                                                         AS price_positioning
FROM category_revenue
ORDER BY total_revenue DESC NULLS LAST;


-- =============================================================================
-- PROMOTION ROI
-- =============================================================================
-- Cost per sale, ROAS, and which non-promoted listings would benefit from promotion

CREATE OR REPLACE VIEW promotion_roi AS
WITH promo_metrics AS (
    SELECT
        pl.campaign_id,
        pl.campaign_name,
        pl.campaign_status,
        pl.listing_id,
        al.title,
        al.price,
        pl.bid_percentage,
        pl.daily_budget,
        SUM(pl.total_spend)                                     AS total_spend,
        SUM(pl.impressions)                                     AS total_impressions,
        SUM(pl.clicks)                                          AS total_clicks,
        SUM(pl.sales_attributed)                                AS total_sales_attributed,
        -- Revenue attributed: sales * price (proxy, actual revenue from orders)
        SUM(pl.sales_attributed) * al.price                    AS attributed_revenue
    FROM promoted_listings pl
    LEFT JOIN active_listings al ON pl.listing_id = al.listing_id
    GROUP BY
        pl.campaign_id, pl.campaign_name, pl.campaign_status,
        pl.listing_id, al.title, al.price, pl.bid_percentage, pl.daily_budget
),
non_promoted AS (
    -- Listings that are active but have no promoted listing record
    SELECT
        al.listing_id,
        al.title,
        al.price,
        p.total_impressions,
        p.total_clicks,
        p.agg_ctr,
        p.agg_conversion_rate,
        p.total_units_sold,
        p.total_revenue
    FROM active_listings al
    LEFT JOIN promoted_listings pl ON al.listing_id = pl.listing_id
    LEFT JOIN (
        SELECT
            listing_id,
            SUM(impressions)    AS total_impressions,
            SUM(clicks)         AS total_clicks,
            SUM(quantity_sold)  AS total_units_sold,
            SUM(total_revenue)  AS total_revenue,
            CASE WHEN SUM(impressions) > 0
                 THEN ROUND(SUM(clicks)::NUMERIC / SUM(impressions), 4)
                 ELSE 0 END     AS agg_ctr,
            CASE WHEN SUM(clicks) > 0
                 THEN ROUND(SUM(quantity_sold)::NUMERIC / SUM(clicks), 4)
                 ELSE 0 END     AS agg_conversion_rate
        FROM listing_performance
        GROUP BY listing_id
    ) p ON al.listing_id = p.listing_id
    WHERE pl.listing_id IS NULL
      AND al.listing_status = 'ACTIVE'
)
-- Promoted listing ROI
SELECT
    'PROMOTED'                                                  AS promotion_type,
    campaign_id,
    campaign_name,
    campaign_status,
    listing_id,
    title,
    price,
    bid_percentage,
    daily_budget,
    ROUND(total_spend::NUMERIC, 2)                              AS total_spend,
    total_impressions,
    total_clicks,
    total_sales_attributed                                      AS sales_count,
    ROUND(attributed_revenue::NUMERIC, 2)                       AS attributed_revenue,
    -- ROAS = revenue / spend
    CASE WHEN total_spend > 0
         THEN ROUND((attributed_revenue / total_spend)::NUMERIC, 2)
         ELSE NULL END                                          AS roas,
    -- Cost per sale
    CASE WHEN total_sales_attributed > 0
         THEN ROUND((total_spend / total_sales_attributed)::NUMERIC, 2)
         ELSE NULL END                                          AS cost_per_sale,
    NULL::BOOLEAN                                               AS promotion_recommended
FROM promo_metrics

UNION ALL

-- Non-promoted listings with promotion recommendation
SELECT
    'NOT_PROMOTED'                                              AS promotion_type,
    NULL                                                        AS campaign_id,
    NULL                                                        AS campaign_name,
    NULL                                                        AS campaign_status,
    listing_id,
    title,
    price,
    NULL                                                        AS bid_percentage,
    NULL                                                        AS daily_budget,
    0                                                           AS total_spend,
    total_impressions,
    total_clicks,
    total_units_sold                                            AS sales_count,
    total_revenue                                               AS attributed_revenue,
    NULL                                                        AS roas,
    NULL                                                        AS cost_per_sale,
    -- Recommend promotion if: decent CTR but low impressions, or high watchers
    CASE WHEN agg_ctr > 0.02 AND total_impressions < 200
         THEN TRUE ELSE FALSE END                               AS promotion_recommended
FROM non_promoted
ORDER BY promotion_type, roas DESC NULLS LAST;


-- =============================================================================
-- LISTING QUALITY FLAGS
-- =============================================================================
-- Surfaces listings with SEO/quality issues that hurt eBay Cassini ranking

CREATE OR REPLACE VIEW listing_quality_flags AS
SELECT
    al.listing_id,
    al.title,
    al.price,
    al.listing_url,
    al.listing_status,
    -- Image count (parsed from JSON array string)
    CASE
        WHEN al.image_urls IS NOT NULL AND al.image_urls NOT IN ('[]', '', 'null')
        THEN JSON_ARRAY_LENGTH(al.image_urls::JSON)
        ELSE 0
    END                                                         AS image_count,
    LENGTH(al.title)                                            AS title_length,
    -- Item specifics completeness
    CASE
        WHEN al.item_specifics IS NULL OR al.item_specifics IN ('{}', '', 'null')
        THEN 0
        ELSE JSON_OBJECT_KEYS(al.item_specifics::JSON)::TEXT[]  -- count keys downstream
    END                                                         AS item_specifics_raw,
    -- Quality flags
    CASE WHEN al.image_urls IS NULL
              OR al.image_urls IN ('[]', '', 'null')
              OR JSON_ARRAY_LENGTH(al.image_urls::JSON) < 2
         THEN TRUE ELSE FALSE END                               AS flag_few_images,
    CASE WHEN LENGTH(al.title) < 60
         THEN TRUE ELSE FALSE END                               AS flag_short_title,
    CASE WHEN al.item_specifics IS NULL
              OR al.item_specifics IN ('{}', '', 'null')
         THEN TRUE ELSE FALSE END                               AS flag_no_item_specifics,
    CASE WHEN al.condition IS NULL OR al.condition = ''
         THEN TRUE ELSE FALSE END                               AS flag_missing_condition,
    -- Overall quality score (0-4, higher = better)
    (
        CASE WHEN JSON_ARRAY_LENGTH(COALESCE(NULLIF(al.image_urls,'[]'), '[]')::JSON) >= 4
             THEN 1 ELSE 0 END
      + CASE WHEN LENGTH(al.title) >= 60 THEN 1 ELSE 0 END
      + CASE WHEN al.item_specifics IS NOT NULL
                  AND al.item_specifics NOT IN ('{}', '', 'null')
             THEN 1 ELSE 0 END
      + CASE WHEN al.condition IS NOT NULL AND al.condition != ''
             THEN 1 ELSE 0 END
    )                                                           AS quality_score
FROM active_listings al
WHERE al.listing_status = 'ACTIVE'
ORDER BY quality_score ASC, al.price DESC;


-- =============================================================================
-- SALES VELOCITY
-- =============================================================================
-- Fast movers → restock candidates
-- Zero-sales in 30+ days → price drop or relist candidates

CREATE OR REPLACE VIEW sales_velocity AS
WITH recent_sales AS (
    SELECT
        listing_id,
        SUM(quantity_sold)                                      AS units_sold_30d,
        SUM(total_revenue)                                      AS revenue_30d,
        MAX(date)                                               AS last_sale_date,
        COUNT(DISTINCT date)                                    AS days_with_sales
    FROM listing_performance
    WHERE date >= (CURRENT_DATE - INTERVAL '30 days')::TEXT
    GROUP BY listing_id
),
order_recency AS (
    SELECT
        listing_id,
        MAX(created_date)                                       AS last_order_date,
        SUM(quantity)                                           AS total_units_ordered
    FROM orders
    WHERE order_status NOT IN ('CANCELLED')
    GROUP BY listing_id
)
SELECT
    al.listing_id,
    al.title,
    al.price,
    al.currency,
    al.quantity_available,
    al.listing_url,
    COALESCE(rs.units_sold_30d, 0)                              AS units_sold_30d,
    COALESCE(rs.revenue_30d, 0)                                 AS revenue_30d,
    rs.last_sale_date,
    rs.days_with_sales,
    or2.last_order_date,
    COALESCE(or2.total_units_ordered, 0)                        AS total_units_ordered,
    -- Daily velocity
    CASE WHEN rs.days_with_sales > 0
         THEN ROUND((rs.units_sold_30d::NUMERIC / 30), 2)
         ELSE 0 END                                             AS daily_velocity,
    -- Days until stockout at current velocity
    CASE
        WHEN rs.units_sold_30d > 0 AND al.quantity_available > 0
        THEN ROUND((al.quantity_available::NUMERIC / (rs.units_sold_30d::NUMERIC / 30)), 0)
        ELSE NULL
    END                                                         AS days_until_stockout,
    -- Action recommendation
    CASE
        WHEN COALESCE(rs.units_sold_30d, 0) = 0
             AND (or2.last_order_date IS NULL
                  OR or2.last_order_date < (NOW() - INTERVAL '30 days'))
        THEN 'RELIST_OR_PRICE_DROP'
        WHEN rs.units_sold_30d > 5
             AND al.quantity_available <= 2
        THEN 'RESTOCK_URGENTLY'
        WHEN rs.units_sold_30d > 2
             AND al.quantity_available <= 5
        THEN 'RESTOCK_SOON'
        WHEN COALESCE(rs.units_sold_30d, 0) = 0
             AND al.quantity_available > 0
        THEN 'REVIEW_PRICING'
        ELSE 'MONITOR'
    END                                                         AS action_recommendation
FROM active_listings al
LEFT JOIN recent_sales rs ON al.listing_id = rs.listing_id
LEFT JOIN order_recency or2 ON al.listing_id = or2.listing_id
WHERE al.listing_status = 'ACTIVE'
ORDER BY units_sold_30d DESC, al.price DESC;
