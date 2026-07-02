select order_id, name, created_at, cancelled, financial_status,
       total_price, total_discounts, total_refunded, shipping_charged
from {{ source('raw', 'orders') }}
