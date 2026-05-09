-- Analysis views for Fivetran managed eBay connector
-- Destination: jason_chletsos_databricks / jason_chletsos_ebay
-- Run these after the first sync completes

-- 1. Order revenue summary
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_order_summary AS
SELECT
    o.order_id,
    o.creation_date,
    o.order_fulfillment_status,
    o.order_payment_status,
    o.buyer_username,
    COUNT(DISTINCT li.line_item_id)                              AS line_item_count,
    SUM(li.quantity)                                             AS total_units,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(li.delivery_cost_value)                                  AS shipping_charged,
    SUM(li.line_item_cost_value) + SUM(li.delivery_cost_value)   AS total_order_value,
    SUM(COALESCE(r.amount_value, 0))                             AS total_refunded,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY o.order_id, o.creation_date, o.order_fulfillment_status,
         o.order_payment_status, o.buyer_username;

-- 2. Sales by item
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_sales_by_item AS
SELECT
    li.legacy_item_id                                            AS listing_id,
    li.title,
    COUNT(DISTINCT li.order_id)                                  AS orders_count,
    SUM(li.quantity)                                             AS units_sold,
    AVG(li.line_item_cost_value)                                 AS avg_sale_price,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(COALESCE(r.amount_value, 0))                             AS total_refunded,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue,
    MIN(o.creation_date)                                         AS first_sale_date,
    MAX(o.creation_date)                                         AS last_sale_date
FROM jason_chletsos_ebay.orders_line_item li
JOIN jason_chletsos_ebay.order_history o ON li.order_id = o.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY li.legacy_item_id, li.title
ORDER BY gross_revenue DESC;

-- 3. Monthly revenue trend
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_monthly_revenue AS
SELECT
    DATE_TRUNC('month', o.creation_date)                         AS month,
    COUNT(DISTINCT o.order_id)                                   AS orders,
    SUM(li.quantity)                                             AS units_sold,
    SUM(li.line_item_cost_value)                                 AS gross_revenue,
    SUM(COALESCE(r.amount_value, 0))                             AS refunds,
    SUM(li.line_item_cost_value) - SUM(COALESCE(r.amount_value, 0)) AS net_revenue,
    COUNT(DISTINCT o.buyer_username)                             AS unique_buyers
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
LEFT JOIN jason_chletsos_ebay.orders_line_item_refund r ON li.line_item_id = r.line_item_id
GROUP BY DATE_TRUNC('month', o.creation_date)
ORDER BY month DESC;

-- 4. Fulfillment performance
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_fulfillment_performance AS
SELECT
    o.order_id,
    o.creation_date                                              AS order_date,
    o.order_fulfillment_status,
    sf.shipping_carrier_code,
    sf.shipped_date,
    DATEDIFF('day', o.creation_date, sf.shipped_date)            AS days_to_ship,
    CASE
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 1 THEN 'Same or next day'
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 3 THEN 'Fast 2 to 3 days'
        WHEN DATEDIFF('day', o.creation_date, sf.shipped_date) <= 7 THEN 'Standard 4 to 7 days'
        ELSE 'Slow 7 plus days'
    END                                                          AS shipping_speed_tier
FROM jason_chletsos_ebay.order_history o
LEFT JOIN jason_chletsos_ebay.shipping_fulfillment sf ON o.order_id = sf.order_id;

-- 5. Buyer analysis
CREATE OR REPLACE VIEW jason_chletsos_ebay.v_buyer_analysis AS
SELECT
    o.buyer_username,
    COUNT(DISTINCT o.order_id)                                   AS total_orders,
    SUM(li.line_item_cost_value)                                 AS lifetime_value,
    AVG(li.line_item_cost_value)                                 AS avg_order_value,
    MIN(o.creation_date)                                         AS first_order_date,
    MAX(o.creation_date)                                         AS last_order_date,
    CASE
        WHEN COUNT(DISTINCT o.order_id) = 1  THEN 'One-time'
        WHEN COUNT(DISTINCT o.order_id) <= 3 THEN 'Repeat'
        ELSE 'Loyal'
    END                                                          AS buyer_segment
FROM jason_chletsos_ebay.order_history o
JOIN jason_chletsos_ebay.orders_line_item li ON o.order_id = li.order_id
GROUP BY o.buyer_username
ORDER BY lifetime_value DESC;
