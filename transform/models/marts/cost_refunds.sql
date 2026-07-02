-- Money handed back: refunds by month.
select date_trunc('month', cast(created_at as timestamp)) as month,
       count(*) filter (where total_refunded > 0) as refunded_orders,
       round(sum(total_refunded), 2) as amount_gbp
from {{ ref('stg_orders') }}
where not cancelled
group by 1
