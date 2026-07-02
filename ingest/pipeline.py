"""Load a Shopify store's money signals into a DuckDB warehouse.

Two sources, same tables either way:
  - live: the Admin GraphQL API (orders with discounts/refunds, products with
    variant price, unit cost, and inventory) read with a custom-app token from
    .env (SHOPIFY_STORE, SHOPIFY_TOKEN; scopes read_orders, read_products,
    read_inventory);
  - demo: synthetic but realistically shaped orders and products, so the marts
    and the money tree work before the store has traded a penny.

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


# --- live source: Admin GraphQL ------------------------------------------- #
def _gql(store: str, token: str, query: str, variables: dict) -> dict:
    req = urllib.request.Request(
        f"https://{store}/admin/api/{API_VERSION}/graphql.json",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={"Content-Type": "application/json", "X-Shopify-Access-Token": token},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    if out.get("errors"):
        raise RuntimeError(out["errors"])
    return out["data"]

ORDERS_Q = """
query($cursor: String) {
  orders(first: 100, after: $cursor, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id name createdAt cancelledAt displayFinancialStatus
      totalPriceSet { shopMoney { amount } }
      totalDiscountsSet { shopMoney { amount } }
      totalRefundedSet { shopMoney { amount } }
      totalShippingPriceSet { shopMoney { amount } }
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


def live_orders(store: str, token: str):
    cursor = None
    while True:
        data = _gql(store, token, ORDERS_Q, {"cursor": cursor})
        page = data["orders"]
        for o in page["nodes"]:
            yield {
                "order_id": o["id"], "name": o["name"], "created_at": o["createdAt"],
                "cancelled": o["cancelledAt"] is not None,
                "financial_status": o["displayFinancialStatus"],
                "total_price": _money(o, "totalPriceSet"),
                "total_discounts": _money(o, "totalDiscountsSet"),
                "total_refunded": _money(o, "totalRefundedSet"),
                "shipping_charged": _money(o, "totalShippingPriceSet"),
            }
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]


def live_variants(store: str, token: str):
    cursor = None
    while True:
        data = _gql(store, token, PRODUCTS_Q, {"cursor": cursor})
        page = data["products"]
        for p in page["nodes"]:
            for v in p["variants"]["nodes"]:
                unit_cost = ((v.get("inventoryItem") or {}).get("unitCost") or {}).get("amount")
                yield {
                    "product_id": p["id"], "product": p["title"], "status": p["status"],
                    "variant_id": v["id"], "variant": v["title"],
                    "price": float(v["price"] or 0),
                    "unit_cost": float(unit_cost) if unit_cost else None,
                    "inventory_quantity": v["inventoryQuantity"] or 0,
                }
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]


# --- demo source: synthetic but realistically shaped ----------------------- #
def demo_orders(n: int = 240, seed: int = 7):
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    for i in range(n):
        price = round(rng.uniform(18, 240), 2)
        discounted = rng.random() < 0.35
        refunded = rng.random() < 0.08
        cancelled = rng.random() < 0.04
        yield {
            "order_id": f"demo/{i}", "name": f"#10{i:03}",
            "created_at": (now - timedelta(days=rng.uniform(0, 90))).isoformat(),
            "cancelled": cancelled,
            "financial_status": "REFUNDED" if refunded else "PAID",
            "total_price": price,
            "total_discounts": round(price * rng.uniform(0.05, 0.3), 2) if discounted else 0.0,
            "total_refunded": round(price * rng.uniform(0.4, 1.0), 2) if refunded else 0.0,
            "shipping_charged": round(rng.choice([0, 0, 3.95, 5.95]), 2),
        }


def demo_variants(seed: int = 7):
    rng = random.Random(seed)
    for i in range(15):
        cost = round(rng.uniform(4, 60), 2)
        yield {
            "product_id": f"demo/p{i}", "product": f"Product {chr(65 + i)}",
            "status": "ACTIVE", "variant_id": f"demo/v{i}", "variant": "Default",
            "price": round(cost * rng.uniform(1.6, 3.2), 2),
            "unit_cost": cost,
            "inventory_quantity": rng.randint(0, 400),
        }


def run(demo: bool) -> None:
    load_env()
    store, token = os.environ.get("SHOPIFY_STORE", ""), os.environ.get("SHOPIFY_TOKEN", "")
    if not demo and not (store and token):
        print("No SHOPIFY_STORE/SHOPIFY_TOKEN in .env — running demo mode instead.")
        demo = True

    orders = demo_orders() if demo else live_orders(store, token)
    variants = demo_variants() if demo else live_variants(store, token)

    pipeline = dlt.pipeline(
        pipeline_name="shop_money_loop",
        destination=dlt.destinations.duckdb(WAREHOUSE),
        dataset_name="raw",
    )
    info = pipeline.run([
        dlt.resource(orders, name="orders", write_disposition="replace"),
        dlt.resource(variants, name="variants", write_disposition="replace"),
    ])
    print(info)


if __name__ == "__main__":
    run(demo="--demo" in sys.argv)
