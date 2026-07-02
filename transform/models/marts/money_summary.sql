-- Where the store's money is going, with revenue for scale.
with o as (select * from {{ ref('stg_orders') }}),
rev as (select sum(total_price) as revenue from o where not cancelled),
leaks as (
    select 'refunds' as category, sum(total_refunded) as amount_gbp from o where not cancelled
    union all
    select 'discounts', sum(total_discounts) from o where not cancelled
    union all
    select 'cancelled orders', sum(total_price) from o where cancelled
    union all
    select 'capital in stock', sum(inventory_quantity * unit_cost) from {{ ref('stg_variants') }}
)
select l.category,
       round(coalesce(l.amount_gbp, 0), 2) as amount_gbp,
       round(100.0 * coalesce(l.amount_gbp, 0) / r.revenue, 2) as pct_of_revenue
from leaks l cross join rev r
order by amount_gbp desc
