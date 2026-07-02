# shop-money-loop: where a Shopify store's money is going

One command answers the question Shopify's own reports don't: dlt loads your
store's orders and inventory from the Admin GraphQL API into a local DuckDB
warehouse, dbt prices the leaks, and one tree says where the money went.

```
== where the store's money is going ==
  capital in stock   £  53,800.26   (176.62% of revenue)
  discounts          £   1,737.19   (5.70% of revenue)
  refunds            £   1,593.64   (5.23% of revenue)
  cancelled orders   £     921.46   (3.03% of revenue)
  top capital in stock: Product N £9,042, Product J £8,021, Product A £7,369
```

Everything runs on your machine. Your store data never leaves it: no hosted
service, no third party, no app to install on the store beyond a read-only
custom-app token you create and control.

- refunds and discounts by month (P&L leaks)
- cancelled order value
- capital tied up in stock (quantity x unit cost, per product) -- this one is
  cash sitting on a shelf, not money lost; it is in the tree because it is the
  number merchants most often cannot see
- everything scaled against revenue

## Run it

Setup (own venv, fully self-contained):

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt

Demo mode (synthetic data, no store needed):

    .\.venv\Scripts\python.exe run.py --demo

Real store: copy `.env.example` to `.env`, fill in the store domain and a
custom-app Admin API token (scopes: read_orders, read_products,
read_inventory), then run without --demo. Variants with no unit cost recorded
show as null capital rather than being silently priced at zero -- fixing cost
data at the source is usually the first finding.
