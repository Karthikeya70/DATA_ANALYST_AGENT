import sys, json
sys.stdout.reconfigure(encoding="utf-8")
r = json.load(open("data/eval/results.json", encoding="utf-8"))
for q in r:
    if q["sql_errors"] > 0:
        print(f"=== {q['id']} recovered from {q['sql_errors']} error(s) ===")
        for s in q["trajectory"]:
            if s["type"] == "run_sql" and not s["ok"]:
                print("  ERROR:", s["result_preview"][:120])
