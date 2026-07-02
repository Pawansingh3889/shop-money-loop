# shop-money-loop: where a Shopify store's money is going

The factory money-loop pattern pointed at commerce: dlt loads a store's orders
and inventory from the Admin GraphQL API into DuckDB, dbt prices the leaks,
one tree says where the money went.

- refunds and discounts by month (P&L leaks)
- cancelled order value
- capital tied up in stock (quantity x unit cost, per product) -- this one is
  cash sitting on a shelf, not money lost; it is in the tree because it is the
  number merchants most often cannot see
- everything scaled against revenue

## Run it

Demo mode (synthetic data, no store needed):

    C:\Users\pawan\work\data-loop-demo\.venv\Scripts\python.exe run.py --demo

Real store: copy `.env.example` to `.env`, fill in the store domain and a
custom-app Admin API token (scopes: read_orders, read_products,
read_inventory), then run without --demo. Variants with no unit cost recorded
show as null capital rather than being silently priced at zero -- fixing cost
data at the source is usually the first finding.
