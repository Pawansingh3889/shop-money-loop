-- Margin per product: revenue kept after discounts, minus cost of goods.
-- COGS joins on product title (single-variant catalogs; a variant-level join
-- needs variant ids carried through line items -- documented assumption).
with items as (
    select product,
           sum(quantity) as units,
           sum(discounted_total) as revenue_gbp,
           sum(discount) as discount_gbp
    from {{ ref('stg_order_items') }}
    where not cancelled
    group by product
),
costs as (
    select product, avg(unit_cost) as unit_cost
    from {{ ref('stg_variants') }}
    where unit_cost is not null
    group by product
)
select
    i.product,
    i.units,
    round(i.revenue_gbp, 2) as revenue_gbp,
    round(i.units * c.unit_cost, 2) as cogs_gbp,
    round(i.revenue_gbp - i.units * c.unit_cost, 2) as margin_gbp,
    round(100.0 * (i.revenue_gbp - i.units * c.unit_cost) / nullif(i.revenue_gbp, 0), 1) as margin_pct,
    round(i.discount_gbp, 2) as discount_gbp,
    round(100.0 * i.discount_gbp / nullif(i.revenue_gbp - i.units * c.unit_cost + i.discount_gbp, 0), 1)
        as discount_share_of_potential_margin_pct
from items i
join costs c on i.product = c.product
order by margin_gbp desc
