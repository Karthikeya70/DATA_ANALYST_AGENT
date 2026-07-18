"""Web UI for the data analyst agent.

GET  /          the page, with live benchmark stats from results.json
POST /api/ask   {question} -> full agent result including the trajectory
                (every SQL attempt, errors, repairs) so the UI can show
                the agent's actual reasoning process, not just the answer.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import json
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from flask import Flask, render_template, request, jsonify
from agent import run_agent

app = Flask(__name__)


def load_stats():
    stats = {"accuracy": "—", "grounded": "—", "repairs": "—",
             "avg_latency": "—", "avg_cost": "—"}
    try:
        with open("data/eval/results.json", encoding="utf-8") as f:
            rs = json.load(f)
        n = len(rs)
        stats["accuracy"] = f"{100 * sum(r['correct'] for r in rs) // n}%"
        stats["grounded"] = f"{100 * sum(r.get('grounded', True) for r in rs) // n}%"
        err = [r for r in rs if r["sql_errors"] > 0]
        rec = [r for r in err if r["correct"]]
        stats["repairs"] = f"{len(rec)}/{len(err)}" if err else "0/0"
        stats["avg_latency"] = f"{sum(r['latency'] for r in rs) / n:.1f}s"
        stats["avg_cost"] = f"${sum(r['cost'] for r in rs) / n:.4f}"
    except FileNotFoundError:
        pass
    return stats


@app.route("/")
def home():
    return render_template("index.html", **load_stats())


@app.route("/api/ask", methods=["POST"])
def api_ask():
    data = request.get_json(force=True)
    question = (data.get("question") or "").strip()
    if not question:
        return jsonify({"error": "Please type a question."}), 400
    if len(question) > 500:
        return jsonify({"error": "Question too long (500 chars max)."}), 400
    try:
        r = run_agent(question)
        return jsonify(r)
    except Exception as e:
        return jsonify({"error": str(e)}), 502


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
