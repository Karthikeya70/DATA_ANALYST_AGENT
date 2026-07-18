"""Expert tier for the exam (e01-e08): questions engineered to be HARD
for a SQL-writing agent, because the first 12 saturated at 100%.

Each targets a specific difficulty class:
- SQLite missing features (no MEDIAN) -> forces improvisation, likely errors
- schema traps (customer_id is per-order; customer_unique_id is the person)
- multi-row-per-order traps (payments)
- window-function analytics (month-over-month growth)
- multi-condition aggregation (thresholds + joins)

Ground truths computed here with pandas, independently of any SQL the
agent might write. Appended to data/eval/questions.json.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import pandas as pd

RAW = "data/raw"
orders = pd.read_csv(f"{RAW}/olist_orders_dataset.csv")
items = pd.read_csv(f"{RAW}/olist_order_items_dataset.csv")
customers = pd.read_csv(f"{RAW}/olist_customers_dataset.csv")
products = pd.read_csv(f"{RAW}/olist_products_dataset.csv")
payments = pd.read_csv(f"{RAW}/olist_order_payments_dataset.csv")
reviews = pd.read_csv(f"{RAW}/olist_order_reviews_dataset.csv")
trans = pd.read_csv(f"{RAW}/product_category_name_translation.csv")

for col in ["order_purchase_timestamp", "order_delivered_customer_date"]:
    orders[col] = pd.to_datetime(orders[col])

qs = []

def add(qid, tables, question, answer, answer_type, gt_code, tolerance=None):
    qs.append({"id": qid, "difficulty": "expert", "tables": tables,
               "question": question, "ground_truth": answer,
               "answer_type": answer_type, "tolerance": tolerance,
               "gt_code": gt_code.strip()})

# e01 — SQLite has no MEDIAN(): the agent must improvise (ORDER BY/LIMIT
# or window functions). Prime candidate for first-attempt errors.
add("e01", ["order_items"],
    "What is the median item price across all rows of the order_items "
    "table? Round to 2 decimal places.",
    round(float(items.price.median()), 2), "float",
    "items.price.median()", tolerance=0.01)

# e02 — THE schema trap: customer_id changes per order; customer_unique_id
# identifies the person. Using the wrong one gives 0% repeat customers.
merged = orders.merge(customers[["customer_id", "customer_unique_id"]],
                      on="customer_id")
per_person = merged.groupby("customer_unique_id").order_id.nunique()
repeat_rate = round(100 * (per_person > 1).mean(), 2)
add("e02", ["orders", "customers"],
    "What percentage of customers (identified by customer_unique_id) "
    "placed more than one order? Round to 2 decimal places.",
    float(repeat_rate), "float",
    "orders+customers; orders per customer_unique_id; % with >1",
    tolerance=0.05)

# e03 — simple wording, division trap (which denominator?)
avg_items = round(len(items) / items.order_id.nunique(), 2)
add("e03", ["order_items"],
    "On average, how many item rows does an order have? Compute as: total "
    "rows in order_items divided by the number of distinct orders in "
    "order_items. Round to 2 decimal places.",
    float(avg_items), "float",
    "len(items) / items.order_id.nunique()", tolerance=0.01)

# e04 — month-over-month growth: needs LAG() or a self-join.
monthly = (orders[orders.order_status == "delivered"]
           .order_purchase_timestamp.dt.to_period("M")
           .value_counts().sort_index())
growth = monthly.diff().dropna()
add("e04", ["orders"],
    "Considering delivered orders grouped by purchase month (YYYY-MM), "
    "which month had the largest INCREASE in number of delivered orders "
    "compared to the previous calendar month? Answer in YYYY-MM format.",
    str(growth.idxmax()), "string",
    "monthly delivered counts; diff(); idxmax()")

# e05 — multi-join + threshold + aggregation ordering trap
rev_state = (reviews.merge(orders[orders.order_status == "delivered"]
                           [["order_id", "customer_id"]], on="order_id")
             .merge(customers[["customer_id", "customer_state"]], on="customer_id"))
counts = rev_state.groupby("customer_state").size()
eligible = counts[counts >= 1000].index
best_state = (rev_state[rev_state.customer_state.isin(eligible)]
              .groupby("customer_state").review_score.mean().idxmax())
add("e05", ["reviews", "orders", "customers"],
    "Among customer states having at least 1000 reviews on delivered "
    "orders, which state has the highest average review score? Treat "
    "each review row as one data point.",
    best_state, "string",
    "reviews->delivered orders->customers; states with >=1000 reviews; "
    "highest mean score")

# e06 — payments multi-row trap: orders paid with >1 DISTINCT payment type
multi = payments.groupby("order_id").payment_type.nunique()
pct_multi = round(100 * (multi > 1).mean(), 2)
add("e06", ["payments"],
    "What percentage of orders in the payments table used more than one "
    "DISTINCT payment type? Round to 2 decimal places.",
    float(pct_multi), "float",
    "payments.groupby(order_id).payment_type.nunique(); % >1",
    tolerance=0.05)

# e07 — 4-table join + per-category threshold + a different metric (freight)
fr = (items.merge(orders[orders.order_status == "delivered"][["order_id"]],
                  on="order_id")
      .merge(products[["product_id", "product_category_name"]], on="product_id")
      .merge(trans, on="product_category_name"))
cat_counts = fr.groupby("product_category_name_english").size()
big_cats = cat_counts[cat_counts >= 100].index
best_freight = (fr[fr.product_category_name_english.isin(big_cats)]
                .groupby("product_category_name_english")
                .freight_value.mean().idxmax())
add("e07", ["orders", "order_items", "products", "category_translation"],
    "Among product categories (English names) with at least 100 items "
    "sold in delivered orders, which category has the highest AVERAGE "
    "freight value per item?",
    best_freight, "string",
    "items->delivered->products->translation; cats >=100 items; "
    "highest mean freight_value")

# e08 — all-voucher orders: requires per-order ALL() logic (NOT EXISTS /
# MIN=MAX / GROUP BY HAVING), an awkward SQL shape
delivered_ids = set(orders[orders.order_status == "delivered"].order_id)
pay_d = payments[payments.order_id.isin(delivered_ids)]
all_voucher = pay_d.groupby("order_id").payment_type.agg(
    lambda s: (s == "voucher").all())
pct_voucher = round(100 * all_voucher.mean(), 2)
add("e08", ["orders", "payments"],
    "What percentage of delivered orders (that appear in the payments "
    "table) were paid ENTIRELY by voucher — i.e. every payment row of "
    "that order has payment_type = 'voucher'? Round to 2 decimal places.",
    float(pct_voucher), "float",
    "delivered orders in payments; groupby order: all rows voucher; %",
    tolerance=0.05)

# ---- append to the existing exam ----
with open("data/eval/questions.json", encoding="utf-8") as f:
    existing = json.load(f)
existing = [q for q in existing if not q["id"].startswith("e")]  # idempotent
existing.extend(qs)
with open("data/eval/questions.json", "w", encoding="utf-8") as f:
    json.dump(existing, f, indent=2, ensure_ascii=False)

print(f"{'id':<5} {'answer':<15} question")
print("-" * 80)
for q in qs:
    print(f"{q['id']:<5} {str(q['ground_truth']):<15} {q['question'][:60]}")
print(f"\nExam now has {len(existing)} questions")
