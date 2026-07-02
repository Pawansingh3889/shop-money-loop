"""Load a Shopify store's money signals into a DuckDB warehouse.

Two sources, same tables either way:
  - live: the Admin GraphQL API — orders (with per-line items, discounts,
    refunds) and products (variant price, unit cost, inventory);
  - demo: synthetic but realistically shaped data, so the marts work before
    the store has traded a penny.

Auth, in .env at the repo root:
  SHOPIFY_STORE=your-store.myshopify.com
  SHOPIFY_TOKEN=shpat_...                       # a direct Admin token, or:
  SHOPIFY_CLIENT_ID=... / SHOPIFY_CLIENT_SECRET=...   # Dev Dashboard app
                                                      # (client credentials grant)
Scopes: read_orders, read_products, read_inventory.

Run:  python ingest/pipeline.py [--demo]
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import dlt

HERE = Path(__file__).resolve().parent.parent
WAREHOUSE = str(HERE / "warehouse.duckdb")
API_VERSION = "2026-04"


def load_env() -> None:
    env = HERE / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def _gql(store: str, token: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        f"https://{store}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token},
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        out = json.loads(resp.read())
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]


def get_token(store: str) -> str:
    """A direct Admin token if configured, else the client credentials grant."""
    token = os.environ.get("SHOPIFY_TOKEN", "")
    if token:
        return token
    cid = os.environ.get("SHOPIFY_CLIENT_ID", "")
    secret = os.environ.get("SHOPIFY_CLIENT_SECRET", "")
    if not (cid and secret):
        return ""
    req = urllib.request.Request(
        f"https://{store}/admin/oauth/access_token",
        data=json.dumps({"grant_type": "client_credentials",
                         "client_id": cid, "client_secret": secret}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())["access_token"]


ORDERS_Q = """
query($cursor: String) {
  orders(first: 50, after: $cursor, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id name createdAt cancelledAt displayFinancialStatus
      totalPriceSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      totalShippingPriceSet { shopMoney { amount } }
      lineItems(first: 50) {
        nodes {
          title quantity
          product { title }
          originalTotalSet { shopMoney { amount } }
          discountedTotalSet { shopMoney { amount } }
          discountAllocations { allocatedAmountSet { shopMoney { amount } } }
        }
      }
    }
  }
}
"""

PRODUCTS_Q = """
query($cursor: String) {
  products(first: 100, after: $cursor) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title status
      variants(first: 50) {
        nodes {
          id title price inventoryQuantity
          inventoryItem { unitCost { amount } }
        }
      }
    }
  }
}
"""


def _money(node: dict, key: str) -> float:
    return float(((node.get(key) or {}).get("shopMoney") or {}).get("amount") or 0)


def fetch_live(store: str, token: str) -> tuple[list, list, list]:
    orders, items = [], []
    cursor = None
    while True:
        data = _gql(store, token, ORDERS_Q, {"cursor": cursor})
        page = data["orders"]
        for o in page["nodes"]:
            orders.append({
                "order_id": o["id"], "name": o["name"], "created_at": o["createdAt"],
                "cancelled": o["cancelledAt"] is not None,
                "financial_status": o["displayFinancialStatus"],
                "total_price": _money(o, "totalPriceSet"),
                "total_discounts": _money(o, "totalDiscountsSet"),
                "total_refunded": _money(o, "totalRefundedSet"),
                "shipping_charged": _money(o, "totalShippingPriceSet"),
            })
            for li in o["lineItems"]["nodes"]:
                original = _money(li, "originalTotalSet")
                # line-level discounts show in discountedTotalSet; order-level
                # discounts only appear as per-line allocations -- count both
                allocated = sum(
                    float(a["allocatedAmountSet"]["shopMoney"]["amount"])
                    for a in li.get("discountAllocations") or []
                )
                discounted = _money(li, "discountedTotalSet")
                discount = round(max(original - discounted, allocated), 2)
                items.append({
                    "order_id": o["id"],
                    "cancelled": o["cancelledAt"] is not None,
                    "product": (li.get("product") or {}).get("title") or li["title"],
                    "quantity": li["quantity"],
                    "original_total": original,
                    "discounted_total": round(original - discount, 2),
                    "discount": discount,
                })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    variants = []
    cursor = None
    while True:
        data = _gql(store, token, PRODUCTS_Q, {"cursor": cursor})
        page = data["products"]
        for p in page["nodes"]:
            for v in p["variants"]["nodes"]:
                unit_cost = ((v.get("inventoryItem") or {}).get("unitCost") or {}).get("amount")
                variants.append({
                    "product_id": p["id"], "product": p["title"], "status": p["status"],
                    "variant_id": v["id"], "variant": v["title"],
                    "price": float(v["price"] or 0),
                    "unit_cost": float(unit_cost) if unit_cost else None,
                    "inventory_quantity": v["inventoryQuantity"] or 0,
                })
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]
    return orders, items, variants


def build_demo(seed: int = 7) -> tuple[list, list, list]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    names = [f"Product {chr(65 + i)}" for i in range(15)]

    variants = []
    for i, name in enumerate(names):
        cost = round(rng.uniform(4, 60), 2)
        variants.append({
            "product_id": f"demo/p{i}", "product": name, "status": "ACTIVE",
            "variant_id": f"demo/v{i}", "variant": "Default",
            "price": round(cost * rng.uniform(1.6, 3.2), 2),
            "unit_cost": cost,
            "inventory_quantity": rng.randint(0, 400),
        })

    orders, items = [], []
    for i in range(240):
        picks = rng.sample(variants, rng.randint(1, 3))
        discounted_order = rng.random() < 0.35
        lines, gross, disc_total = [], 0.0, 0.0
        for v in picks:
            qty = rng.randint(1, 3)
            original = round(v["price"] * qty, 2)
            disc = round(original * rng.uniform(0.05, 0.3), 2) if discounted_order else 0.0
            gross += original
            disc_total += disc
            lines.append((v["product"], qty, original, disc))
        total = round(gross - disc_total, 2)
        refunded = rng.random() < 0.08
        cancelled = rng.random() < 0.04
        oid = f"demo/{i}"
        orders.append({
            "order_id": oid, "name": f"#10{i:03}",
            "created_at": (now - timedelta(days=rng.uniform(0, 90))).isoformat(),
            "cancelled": cancelled,
            "financial_status": "REFUNDED" if refunded else "PAID",
            "total_price": total,
            "total_discounts": round(disc_total, 2),
            "total_refunded": round(total * rng.uniform(0.4, 1.0), 2) if refunded else 0.0,
            "shipping_charged": round(rng.choice([0, 0, 3.95, 5.95]), 2),
        })
        for product, qty, original, disc in lines:
            items.append({
                "order_id": oid, "cancelled": cancelled, "product": product,
                "quantity": qty, "original_total": original,
                "discounted_total": round(original - disc, 2), "discount": disc,
            })
    return orders, items, variants


def run(demo: bool) -> None:
    load_env()
    store = os.environ.get("SHOPIFY_STORE", "")
    token = "" if demo else get_token(store)
    if not demo and not (store and token):
        print("No usable credentials in .env — running demo mode instead.")
        demo = True

    if demo:
        orders, items, variants = build_demo()
    else:
        print(f"fetching live data from {store} ...")
        orders, items, variants = fetch_live(store, token)
    print(f"{len(orders)} orders, {len(items)} line items, {len(variants)} variants")

    pipeline = dlt.pipeline(
        pipeline_name="shop_money_loop",
        destination=dlt.destinations.duckdb(WAREHOUSE),
        dataset_name="raw",
    )
    info = pipeline.run([
        dlt.resource(orders, name="orders", write_disposition="replace"),
        dlt.resource(items, name="order_items", write_disposition="replace"),
        dlt.resource(variants, name="variants", write_disposition="replace"),
    ])
    print(info)


if __name__ == "__main__":
    run(demo="--demo" in sys.argv)
