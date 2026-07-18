"""First look at the Olist data: schemas, sizes, and the traps.

We run this ONCE, by hand, before building anything — because the eval
questions need ground-truth answers we compute ourselves, and to compute
them correctly we must know where this dataset lies to us.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd

RAW = "data/raw"

tables = {
    "orders": "olist_orders_dataset.csv",
    "items": "olist_order_items_dataset.csv",
    "customers": "olist_customers_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "products": "olist_products_dataset.csv",
    "payments": "olist_order_payments_dataset.csv",
    "reviews": "olist_order_reviews_dataset.csv",
    "translation": "product_category_name_translation.csv",
}

dfs = {name: pd.read_csv(f"{RAW}/{f}") for name, f in tables.items()}

print("========== 1. COLUMNS OF EVERY TABLE ==========")
for name, df in dfs.items():
    print(f"\n{name} ({len(df)} rows):")
    for col in df.columns:
        nulls = df[col].isna().sum()
        note = f"  <-- {nulls} NULLS" if nulls else ""
        print(f"   {col} ({df[col].dtype}){note}")

print("\n========== 2. ORDER STATUS VALUES ==========")
print(dfs["orders"]["order_status"].value_counts().to_string())

print("\n========== 3. DATE RANGE ==========")
ts = pd.to_datetime(dfs["orders"]["order_purchase_timestamp"])
print(f"orders span: {ts.min()}  ->  {ts.max()}")

print("\n========== 4. THE PORTUGUESE TRAP ==========")
print("sample product categories:",
      dfs["products"]["product_category_name"].dropna().unique()[:5].tolist())
print("translation table sample:")
print(dfs["translation"].head(3).to_string(index=False))
untranslated = set(dfs["products"]["product_category_name"].dropna().unique()) \
             - set(dfs["translation"]["product_category_name"])
print(f"categories that have NO English translation: {untranslated}")

print("\n========== 5. MONEY: price vs payment ==========")
order_id = dfs["items"]["order_id"].iloc[0]
print(f"one order ({order_id[:8]}...):")
print("  items:", dfs["items"][dfs["items"].order_id == order_id][["price", "freight_value"]].to_dict("records"))
print("  payments:", dfs["payments"][dfs["payments"].order_id == order_id][["payment_type", "payment_value"]].to_dict("records"))

print("\n========== 6. ONE ORDER, MANY PAYMENT ROWS? ==========")
pay_counts = dfs["payments"].groupby("order_id").size()
print(f"orders with more than one payment row: {(pay_counts > 1).sum()}")

print("\n========== 7. REVIEWS: ONE PER ORDER? ==========")
rev_counts = dfs["reviews"].groupby("order_id").size()
print(f"orders with more than one review: {(rev_counts > 1).sum()}")

print("\n========== 8. DELIVERY DATES MISSING ==========")
o = dfs["orders"]
delivered = o[o.order_status == "delivered"]
print(f"delivered orders: {len(delivered)}")
print(f"...of which missing the actual delivery timestamp: {delivered.order_delivered_customer_date.isna().sum()}")
