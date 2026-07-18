"""Load the 9 Olist CSVs into a single SQLite file (data/olist.db).

Why SQLite: it ships inside Python (zero install), it's a single file,
and — critically for this project — it supports a READ-ONLY connection
mode plus an authorizer hook, which is what makes executing
LLM-generated SQL safe (see sandbox.py).

Indexes are added on every join key: the agent's queries join these
tables constantly, and without indexes some multi-joins take seconds.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import os
import sqlite3
import pandas as pd

RAW = "data/raw"
DB = "data/olist.db"

# CSV file -> table name (short names = fewer tokens for the agent)
TABLES = {
    "olist_orders_dataset.csv": "orders",
    "olist_order_items_dataset.csv": "order_items",
    "olist_customers_dataset.csv": "customers",
    "olist_sellers_dataset.csv": "sellers",
    "olist_products_dataset.csv": "products",
    "olist_order_payments_dataset.csv": "payments",
    "olist_order_reviews_dataset.csv": "reviews",
    "olist_geolocation_dataset.csv": "geolocation",
    "product_category_name_translation.csv": "category_translation",
}

INDEXES = [
    ("orders", "order_id"), ("orders", "customer_id"), ("orders", "order_status"),
    ("order_items", "order_id"), ("order_items", "product_id"), ("order_items", "seller_id"),
    ("customers", "customer_id"),
    ("sellers", "seller_id"),
    ("products", "product_id"),
    ("payments", "order_id"),
    ("reviews", "order_id"),
]

if os.path.exists(DB):
    os.remove(DB)

conn = sqlite3.connect(DB)
for csv, table in TABLES.items():
    df = pd.read_csv(f"{RAW}/{csv}")
    df.to_sql(table, conn, index=False, if_exists="replace")
    print(f"{table:<22} {len(df):>9} rows")

for table, col in INDEXES:
    conn.execute(f"CREATE INDEX idx_{table}_{col} ON {table}({col})")
conn.commit()

size_mb = os.path.getsize(DB) / 1e6
print(f"\nBuilt {DB} ({size_mb:.0f} MB) with {len(INDEXES)} indexes")
conn.close()
