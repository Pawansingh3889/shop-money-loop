-- Money given away at checkout: discounts by month.
select date_trunc('month', cast(created_at as timestamp)) as month,
       count(*) filter (where total_discounts > 0) as discounted_orders,
       round(sum(total_discounts), 2) as amount_gbp
from {{ ref('stg_orders') }}
where not cancelled
group by 1
