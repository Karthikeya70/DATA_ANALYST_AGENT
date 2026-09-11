"""Grade the agent against the 12-question exam with known answers.

Usage:
  python src/evaluate.py                # full eval
  python src/evaluate.py --limit 3     # quick smoke run
  python src/evaluate.py --no-repair   # ABLATION: die on first SQL error
                                        # (measures what self-repair is worth)

Metrics reported:
  accuracy (overall + per difficulty), avg steps, SQL error count,
  repair success rate, avg/total latency and cost.

Every run saves per-question results INCLUDING full trajectories to
data/eval/results.json — failed questions can be replayed step by step
for error analysis instead of guessing what went wrong.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

import argparse
import json
import os
import re

from agent import run_agent


def parse_number(text):
    """'R$ 13,221,498.11' -> 13221498.11 ; returns None if not a number."""
    if text is None:
        return None
    cleaned = re.sub(r"[^\d.\-]", "", str(text).replace(",", ""))
    try:
        return float(cleaned)
    except ValueError:
        return None


def grade(q, value):
    """Compare the agent's bare answer to the ground truth."""
    if value is None:
        return False
    if q["answer_type"] in ("int", "float"):
        got = parse_number(value)
        if got is None:
            return False
        tol = q.get("tolerance") or 0.001
        return abs(got - float(q["ground_truth"])) <= tol
    # string: case/space-insensitive exact match
    return str(value).strip().lower() == str(q["ground_truth"]).strip().lower()


def is_grounded(q, value, trajectory):
    """Deterministic groundedness audit (the RAG project's faithfulness
    judge, without the LLM): a numeric final answer must literally appear
    in some executed query result. If it doesn't, the model computed or
    'rounded' the number in its head — the exact failure our architecture
    forbids. (We caught a real one: SQL returned 1.1417, model said 1.13.)
    """
    if q["answer_type"] not in ("int", "float"):
        return True  # strings (names, states) are copied, not computed
    got = parse_number(value)
    if got is None:
        return False
    for step in trajectory:
        if step.get("type") == "run_sql" and step.get("ok"):
            for num in re.findall(r"-?\d+\.?\d*(?:e-?\d+)?",
                                  step.get("result_preview", "")):
                try:
                    if abs(float(num) - got) <= 0.005 * max(1, abs(got)):
                        return True
                except ValueError:
                    pass
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-repair", action="store_true",
                    help="ablation: abort a question on its first SQL error")
    ap.add_argument("--model", type=str, default=None,
                    help="override the primary model (for model bake-offs), "
                         "e.g. --model openai/gpt-4o-mini")
    ap.add_argument("--questions", type=str, default="data/eval/questions.json",
                    help="path to the question set to grade against "
                         "(default: the 20-question baseline exam)")
    args = ap.parse_args()

    if args.model:
        import agent as agent_module
        agent_module.MODELS = [args.model]  # no fallback: measure THIS model
        print(f"[model override: {args.model}]")

    with open(args.questions, encoding="utf-8") as f:
        questions = json.load(f)
    if args.limit:
        questions = questions[:args.limit]

    results = []
    print(f"{'id':<5} {'diff':<7} {'ok':<4} {'steps':<6} {'err':<4} "
          f"{'cost':<9} {'sec':<6} agent answer vs truth")
    print("-" * 90)

    for q in questions:
        r = run_agent(q["question"], allow_repair=not args.no_repair)
        ok = grade(q, r["answer_value"])
        grounded = is_grounded(q, r["answer_value"], r["trajectory"])
        results.append({**q, "agent_value": r["answer_value"],
                        "correct": ok, "grounded": grounded,
                        "status": r["status"],
                        "steps": r["steps"], "sql_errors": r["sql_errors"],
                        "repairs": r["repairs"], "cost": r["cost"],
                        "latency": r["latency"], "model": r["model"],
                        "explanation": r["explanation"],
                        "trajectory": r["trajectory"]})
        print(f"{q['id']:<5} {q['difficulty']:<7} {'YES' if ok else 'NO':<4} "
              f"{r['steps']:<6} {r['sql_errors']:<4} ${r['cost']:<8.5f} "
              f"{r['latency']:<6} {str(r['answer_value'])[:24]} vs {q['ground_truth']}")

    # ---- summary ----
    n = len(results)
    correct = [r for r in results if r["correct"]]
    print("\n================ SUMMARY ================")
    print(f"Accuracy: {len(correct)}/{n}  ({100 * len(correct) // n}%)")
    for diff in ("easy", "medium", "hard"):
        sub = [r for r in results if r["difficulty"] == diff]
        if sub:
            good = sum(r["correct"] for r in sub)
            print(f"  {diff:<7} {good}/{len(sub)}")

    ungrounded = [r for r in results if not r["grounded"]]
    print(f"Groundedness: {n - len(ungrounded)}/{n} numeric answers traced "
          f"verbatim to an executed query result")
    for r in ungrounded:
        print(f"  UNGROUNDED: {r['id']} — value {r['agent_value']!r} not "
              f"found in any query result (mental math detected)")

    total_err = sum(r["sql_errors"] for r in results)
    err_qs = [r for r in results if r["sql_errors"] > 0]
    recovered = [r for r in err_qs if r["correct"]]
    print(f"Avg steps/question: {sum(r['steps'] for r in results) / n:.1f}")
    print(f"SQL errors: {total_err} across {len(err_qs)} questions; "
          f"recovered to a correct answer in {len(recovered)}/{len(err_qs) or 1} of them")
    print(f"Latency: avg {sum(r['latency'] for r in results) / n:.1f}s, "
          f"total {sum(r['latency'] for r in results):.0f}s")
    print(f"Cost: avg ${sum(r['cost'] for r in results) / n:.5f}, "
          f"total ${sum(r['cost'] for r in results):.4f}")

    wrong = [r for r in results if not r["correct"]]
    if wrong:
        print("\nFailed questions:")
        for r in wrong:
            print(f"  {r['id']} ({r['difficulty']}): got {r['agent_value']!r}, "
                  f"expected {r['ground_truth']!r}  [status={r['status']}]")

    # Per-model bake-off runs and alternate question sets get their own
    # file so they never clobber the main baseline results.
    qset = os.path.splitext(os.path.basename(args.questions))[0]
    suffix = "" if qset == "questions" else f"_{qset}"
    if args.model:
        slug = args.model.replace("/", "_").replace(":", "_")
        out = f"data/eval/results_{slug}{suffix}.json"
    elif args.no_repair:
        out = f"data/eval/results_no_repair{suffix}.json"
    else:
        out = f"data/eval/results{suffix}.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nFull results + trajectories saved to {out}")


if __name__ == "__main__":
    main()
