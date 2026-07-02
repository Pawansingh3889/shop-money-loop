-- Cash sitting on the shelf: on-hand quantity x unit cost, per product.
-- Variants without a unit cost are listed with null so the gap is visible,
-- not silently priced at zero.
select product, variant,
       inventory_quantity,
       unit_cost,
       round(inventory_quantity * unit_cost, 2) as capital_gbp
from {{ ref('stg_variants') }}
where inventory_quantity > 0
order by capital_gbp desc nulls last
