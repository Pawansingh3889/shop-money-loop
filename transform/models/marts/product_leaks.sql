-- Per-product attribution: which products carry the discounts, and what each
-- one actually brings in. Line-level discounts only (order-level discounts
-- allocate to lines in Shopify's API, so both kinds land here).
select
    product,
    count(distinct order_id) as orders,
    sum(quantity) as units,
    round(sum(discounted_total), 2) as revenue_gbp,
    round(sum(discount), 2) as discount_gbp,
    round(100.0 * sum(discount) / nullif(sum(original_total), 0), 1) as discount_pct
from {{ ref('stg_order_items') }}
where not cancelled
group by product
order by discount_gbp desc
