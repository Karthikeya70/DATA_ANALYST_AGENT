"""Security tests for the SQL sandbox: every defense is verified by an
actual attack attempt. Run: python src/test_sandbox.py
A production claim you can't test is a production claim you don't have.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from sandbox import SQLSandbox

sb = SQLSandbox()
passed = failed = 0


def check(name, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}  {detail}")


print("== legitimate queries work ==")
r = sb.execute("SELECT COUNT(*) FROM orders")
check("simple SELECT", r["ok"] and r["rows"][0][0] == 99441, str(r))

r = sb.execute("WITH d AS (SELECT * FROM orders WHERE order_status='delivered') "
               "SELECT COUNT(*) FROM d")
check("WITH ... SELECT", r["ok"] and r["rows"][0][0] == 96478, str(r))

r = sb.execute("-- comment first\nSELECT 1")
check("leading comment stripped", r["ok"], str(r))

print("== write attempts are blocked ==")
for name, sql in [
    ("UPDATE", "UPDATE orders SET order_status='x'"),
    ("DELETE", "DELETE FROM orders"),
    ("INSERT", "INSERT INTO sellers VALUES ('a','1','b','c')"),
    ("DROP", "DROP TABLE orders"),
    ("CREATE", "CREATE TABLE evil (x)"),
    ("write hidden in WITH", "WITH x AS (SELECT 1) INSERT INTO sellers SELECT * FROM x"),
]:
    r = sb.execute(sql)
    check(f"blocks {name}", not r["ok"], str(r))

print("== escape attempts are blocked ==")
for name, sql in [
    ("ATTACH another db", "ATTACH DATABASE 'file:evil.db' AS evil"),
    ("PRAGMA", "PRAGMA writable_schema=ON"),
    ("multi-statement", "SELECT 1; DROP TABLE orders"),
    ("comment-hidden second stmt", "SELECT 1 /* */; DELETE FROM orders"),
]:
    r = sb.execute(sql)
    check(f"blocks {name}", not r["ok"], str(r))

print("== read-only introspection allowed, write pragmas still blocked ==")
r = sb.execute("SELECT name FROM pragma_table_info('orders')")
check("pragma_table_info (read-only) works", r["ok"] and r["row_count"] == 8, str(r)[:80])

r = sb.execute("SELECT * FROM pragma_function_list")
check("blocks pragma_function_list (not allowlisted)", not r["ok"], str(r)[:80])

print("== resource limits hold ==")
r = sb.execute("SELECT * FROM orders")
check("row cap", r["ok"] and r["row_count"] == 50 and r["truncated"], str(r)[:80])

r = sb.execute("SELECT COUNT(*) FROM geolocation a JOIN geolocation b "
               "ON a.geolocation_zip_code_prefix != b.geolocation_zip_code_prefix")
check("timeout kills a 1M x 1M cross join", not r["ok"] and "time limit" in r["error"], str(r)[:80])

print("== database is intact after all attacks ==")
r = sb.execute("SELECT COUNT(*) FROM orders")
check("orders table unharmed", r["ok"] and r["rows"][0][0] == 99441, str(r))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
