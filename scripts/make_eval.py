"""Build the exam BEFORE the student exists.

Each eval question gets its ground-truth answer computed HERE, by
hand-written pandas code, and saved to data/eval/questions.json.
The agent will never see this file or this code — it only gets the
question text. Grading later = compare the agent's answer to these.

Design rules learned from the RAG project:
- question wording must be PRECISE (define what "revenue" means, which
  orders count) so there is exactly one correct answer;
- floats carry a tolerance; strings are compared case-insensitively;
- we store the ground-truth code alongside the answer, so anyone can
  audit how the "correct" answer was computed.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import pandas as pd

RAW = "data/raw"
orders = pd.read_csv(f"{RAW}/olist_orders_dataset.csv")
items = pd.read_csv(f"{RAW}/olist_order_items_dataset.csv")
customers = pd.read_csv(f"{RAW}/olist_customers_dataset.csv")
sellers = pd.read_csv(f"{RAW}/olist_sellers_dataset.csv")
products = pd.read_csv(f"{RAW}/olist_products_dataset.csv")
payments = pd.read_csv(f"{RAW}/olist_order_payments_dataset.csv")
reviews = pd.read_csv(f"{RAW}/olist_order_reviews_dataset.csv")
trans = pd.read_csv(f"{RAW}/product_category_name_translation.csv")

for col in ["order_purchase_timestamp", "order_delivered_customer_date",
            "order_estimated_delivery_date"]:
    orders[col] = pd.to_datetime(orders[col])

questions = []

def add(qid, difficulty, tables, question, answer, answer_type, gt_code, tolerance=None):
    questions.append({
        "id": qid, "difficulty": difficulty, "tables": tables,
        "question": question, "ground_truth": answer,
        "answer_type": answer_type, "tolerance": tolerance,
        "gt_code": gt_code.strip(),
    })

# ---------- EASY: one table, one operation ----------

add("q01", "easy", ["orders"],
    "How many orders are there in total in the orders table?",
    int(len(orders)), "int",
    "len(orders)")

add("q02", "easy", ["orders"],
    "How many orders have the status 'canceled'?",
    int((orders.order_status == "canceled").sum()), "int",
    "(orders.order_status == 'canceled').sum()")

add("q03", "easy", ["payments"],
    "What is the most common payment type?",
    payments.payment_type.value_counts().idxmax(), "string",
    "payments.payment_type.value_counts().idxmax()")

add("q04", "easy", ["reviews"],
    "What is the average review score across all rows of the reviews "
    "table, rounded to 2 decimal places?",
    round(float(reviews.review_score.mean()), 2), "float",
    "round(reviews.review_score.mean(), 2)", tolerance=0.01)

# ---------- MEDIUM: filtering, grouping, dates, one join ----------

add("q05", "medium", ["orders"],
    "In which calendar month were the most orders placed? Answer in "
    "YYYY-MM format, based on order_purchase_timestamp.",
    str(orders.order_purchase_timestamp.dt.to_period("M").value_counts().idxmax()),
    "string",
    "orders.order_purchase_timestamp.dt.to_period('M').value_counts().idxmax()")

add("q06", "medium", ["customers"],
    "Which customer state (2-letter code) has the most customers, "
    "counting rows of the customers table?",
    customers.customer_state.value_counts().idxmax(), "string",
    "customers.customer_state.value_counts().idxmax()")

rev = items.merge(orders[orders.order_status == "delivered"][["order_id"]],
                  on="order_id")
add("q07", "medium", ["orders", "items"],
    "What is the total revenue from delivered orders, where revenue is "
    "defined as the sum of item prices (the price column, excluding "
    "freight) over all items belonging to orders with status "
    "'delivered'? Round to 2 decimal places.",
    round(float(rev.price.sum()), 2), "float",
    "items.merge(orders[orders.order_status=='delivered'][['order_id']], "
    "on='order_id').price.sum()", tolerance=1.0)

add("q08", "medium", ["orders"],
    "How many orders with status 'delivered' are missing the actual "
    "delivery timestamp (order_delivered_customer_date is null)?",
    int(orders[(orders.order_status == "delivered")
               & orders.order_delivered_customer_date.isna()].shape[0]),
    "int",
    "orders[(orders.order_status=='delivered') & "
    "orders.order_delivered_customer_date.isna()].shape[0]")

# ---------- HARD: multi-join, computed conditions, traps ----------

cat_rev = (items
           .merge(orders[orders.order_status == "delivered"][["order_id"]], on="order_id")
           .merge(products[["product_id", "product_category_name"]], on="product_id")
           .merge(trans, on="product_category_name"))
top_cat = cat_rev.groupby("product_category_name_english").price.sum().idxmax()
add("q09", "hard", ["orders", "items", "products", "translation"],
    "Which product category, using its ENGLISH name from the category "
    "translation table, has the highest total revenue (sum of item "
    "prices) among delivered orders?",
    top_cat, "string",
    "items -> join delivered orders -> join products -> join translation "
    "-> groupby(english).price.sum().idxmax()")

d = orders[(orders.order_status == "delivered")
           & orders.order_delivered_customer_date.notna()]
late_pct = round(100 * (d.order_delivered_customer_date
                        > d.order_estimated_delivery_date).mean(), 2)
add("q10", "hard", ["orders"],
    "What percentage of delivered orders arrived LATE, i.e. the actual "
    "delivery date is after the estimated delivery date? Consider only "
    "delivered orders that have a non-null delivery date. Round to 2 "
    "decimal places.",
    float(late_pct), "float",
    "d = delivered & delivery date notna; "
    "100 * (d.delivered_date > d.estimated_date).mean()", tolerance=0.05)

seller_rev = (items
              .merge(orders[orders.order_status == "delivered"][["order_id"]], on="order_id")
              .merge(sellers[["seller_id", "seller_state"]], on="seller_id"))
add("q11", "hard", ["orders", "items", "sellers"],
    "Which seller state (2-letter code) generated the highest total "
    "revenue (sum of item prices) from delivered orders?",
    seller_rev.groupby("seller_state").price.sum().idxmax(), "string",
    "items -> join delivered orders -> join sellers -> "
    "groupby(seller_state).price.sum().idxmax()")

late_orders = d[d.order_delivered_customer_date > d.order_estimated_delivery_date]
late_reviews = reviews.merge(late_orders[["order_id"]], on="order_id")
add("q12", "hard", ["orders", "reviews"],
    "What is the average review score of delivered orders that arrived "
    "later than their estimated delivery date? Treat every row of the "
    "reviews table joined to such orders as one data point. Round to 2 "
    "decimal places.",
    round(float(late_reviews.review_score.mean()), 2), "float",
    "reviews joined to late delivered orders; mean(review_score)",
    tolerance=0.01)

# ---------- save ----------
import os
os.makedirs("data/eval", exist_ok=True)
with open("data/eval/questions.json", "w", encoding="utf-8") as f:
    json.dump(questions, f, indent=2, ensure_ascii=False)

print(f"{'id':<5} {'diff':<7} {'answer':<22} question")
print("-" * 95)
for q in questions:
    print(f"{q['id']:<5} {q['difficulty']:<7} {str(q['ground_truth']):<22} {q['question'][:55]}")
print(f"\nSaved {len(questions)} questions to data/eval/questions.json")
