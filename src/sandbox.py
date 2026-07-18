"""Safe executor for LLM-generated SQL.

Threat model: the SQL string comes from a language model, which can be
manipulated by anyone who controls the question OR the data (prompt
injection through data cells). We therefore assume the SQL is hostile
and defend in FOUR independent layers — if any one layer has a hole,
the next one still holds:

  1. READ-ONLY connection (mode=ro in the SQLite URI): the OS-level
     file handle cannot write. Writes are physically impossible.
  2. AUTHORIZER: SQLite asks permission for every internal operation a
     statement performs. We allow reading and SELECT machinery, and
     deny everything else (INSERT, UPDATE, DROP, ATTACH, PRAGMA, ...).
     This catches tricks that string inspection cannot, e.g. writes
     hidden inside a WITH clause.
  3. STATEMENT SHAPE CHECK: after stripping comments, the statement
     must start with SELECT or WITH. sqlite3's execute() additionally
     refuses multi-statement strings ("SELECT 1; DROP ...") natively.
  4. RESOURCE LIMITS: a wall-clock timeout via the progress handler
     (protects against accidental cross joins over the 1M-row
     geolocation table) and a row cap on results (protects the LLM's
     context window from a million-row SELECT *).

Nothing here trusts the model. That is the point.
"""
import re
import sqlite3
import time

DB_PATH = "data/olist.db"
MAX_ROWS = 50          # rows returned to the model (context protection)
TIMEOUT_SECONDS = 15   # wall-clock budget per query

_ALLOWED_ACTIONS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
}


def _authorizer(action, arg1, arg2, db_name, trigger):
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _strip_comments(sql: str) -> str:
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql.strip()


class SQLSandbox:
    def __init__(self, db_path: str = DB_PATH):
        # mode=ro -> the connection itself is read-only (layer 1)
        self.conn = sqlite3.connect(
            f"file:{db_path}?mode=ro", uri=True, check_same_thread=False
        )
        self.conn.set_authorizer(_authorizer)  # layer 2

    def execute(self, sql: str) -> dict:
        """Run one SELECT. Returns
        {ok, columns, rows, row_count, truncated} or {ok: False, error}."""
        cleaned = _strip_comments(sql)
        if not re.match(r"^(SELECT|WITH)\b", cleaned, re.IGNORECASE):  # layer 3
            return {"ok": False,
                    "error": "Rejected: only SELECT (or WITH...SELECT) "
                             "statements are allowed."}

        deadline = time.time() + TIMEOUT_SECONDS
        self.conn.set_progress_handler(                      # layer 4 (time)
            lambda: 1 if time.time() > deadline else 0, 100_000
        )
        try:
            cur = self.conn.execute(cleaned)
            columns = [d[0] for d in cur.description] if cur.description else []
            rows = cur.fetchmany(MAX_ROWS + 1)               # layer 4 (rows)
            truncated = len(rows) > MAX_ROWS
            rows = rows[:MAX_ROWS]
            return {
                "ok": True,
                "columns": columns,
                "rows": [list(r) for r in rows],
                "row_count": len(rows),
                "truncated": truncated,
            }
        except sqlite3.OperationalError as e:
            msg = str(e)
            if "interrupted" in msg.lower():
                msg = (f"Query exceeded the {TIMEOUT_SECONDS}s time limit. "
                       "Add filters or avoid huge joins (geolocation has 1M rows).")
            return {"ok": False, "error": f"SQL error: {msg}"}
        except sqlite3.DatabaseError as e:
            return {"ok": False, "error": f"SQL error: {e}"}
        finally:
            self.conn.set_progress_handler(None, 0)

    def close(self):
        self.conn.close()
