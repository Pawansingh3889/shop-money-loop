select product_id, product, status, variant_id, variant,
       price, unit_cost, inventory_quantity
from {{ source('raw', 'variants') }}
