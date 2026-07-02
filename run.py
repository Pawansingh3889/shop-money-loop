"""Run the shop money loop: load -> model -> report.

With SHOPIFY_STORE/SHOPIFY_TOKEN in .env it reads the real store; without,
it runs on synthetic demo data so the marts and the tree always work.

  python run.py [--demo]
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import duckdb

HERE = Path(__file__).resolve().parent
WAREHOUSE = str(HERE / "warehouse.duckdb")


def main() -> int:
    demo = ["--demo"] if "--demo" in sys.argv else []
    print("== 1/3 load (dlt) ==")
    r = subprocess.run([sys.executable, str(HERE / "ingest" / "pipeline.py"), *demo])
    if r.returncode:
        return r.returncode

    print("== 2/3 model (dbt) ==")
    env = {**os.environ, "DBT_PROFILES_DIR": str(HERE / "transform"), "MONEY_WAREHOUSE": WAREHOUSE}
    r = subprocess.run(
        [sys.executable, "-m", "dbt.cli.main", "run", "--project-dir", str(HERE / "transform")],
        env=env,
    )
    if r.returncode:
        return r.returncode

    print("== 3/3 where the store's money is going ==")
    con = duckdb.connect(WAREHOUSE, read_only=True)
    try:
        for cat, amount, pct in con.execute(
            "SELECT category, amount_gbp, pct_of_revenue FROM main.money_summary"
        ).fetchall():
            print(f"  {cat:18} £{amount:>11,.2f}   ({pct:.2f}% of revenue)")
        top = con.execute(
            "SELECT product, capital_gbp FROM main.stock_capital "
            "WHERE capital_gbp IS NOT NULL LIMIT 3"
        ).fetchall()
        if top:
            print("  top capital in stock:", ", ".join(f"{p} £{c:,.0f}" for p, c in top))
        leaks = con.execute(
            "SELECT product, revenue_gbp, discount_gbp, discount_pct "
            "FROM main.product_leaks WHERE discount_gbp > 0 LIMIT 5"
        ).fetchall()
        if leaks:
            print("  most-discounted products:")
            for prod, rev, disc, pct in leaks:
                print(f"    {prod[:44]:44} £{disc:>8,.2f} off £{rev:>9,.2f} ({pct}%)")
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
