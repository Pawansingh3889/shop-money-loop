select order_id, cancelled, product, quantity,
       original_total, discounted_total, discount
from {{ source('raw', 'order_items') }}
