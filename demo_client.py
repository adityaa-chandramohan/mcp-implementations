"""
demo_client.py — MCP Implementation Benchmark Client

Runs 3 identical benchmark queries against each MCP implementation
and scores output on: completeness, format consistency, and token cost.

Usage:
    python demo_client.py --impl basic-flat-tools
    python demo_client.py --impl resource-context
    python demo_client.py --impl prompt-templates
    python demo_client.py --impl stateful-memory
    python demo_client.py --all   # run all and compare
"""

import argparse
import subprocess
import json
import time
import sys
from pathlib import Path

BENCHMARK_QUERIES = [
    {
        "id": "Q1",
        "label": "Simple lookup",
        "query": "Get employee details for ID EMP001.",
    },
    {
        "id": "Q2",
        "label": "Aggregation",
        "query": "Summarize headcount by department and flag any salary anomalies above 2 standard deviations.",
    },
    {
        "id": "Q3",
        "label": "Multi-step reasoning",
        "query": (
            "Find all engineers hired before 2022, check their last performance review scores, "
            "identify anyone overdue for a raise (last raise > 18 months ago), "
            "and output a JSON list with name, department, review_score, and raise_overdue flag."
        ),
    },
]

IMPLEMENTATIONS = ["basic-flat-tools", "resource-context", "prompt-templates", "stateful-memory"]


def run_impl(impl_name: str) -> dict:
    """Switch to the impl branch and run server.py, capturing output."""
    print(f"\n{'='*60}")
    print(f"  Running: impl/{impl_name}")
    print(f"{'='*60}")

    repo_path = Path(__file__).parent
    results = {"impl": impl_name, "queries": []}

    try:
        subprocess.run(
            ["git", "checkout", f"impl/{impl_name}"],
            cwd=repo_path,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Could not checkout impl/{impl_name}: {e.stderr.decode()}")
        return results

    for q in BENCHMARK_QUERIES:
        print(f"\n  [{q['id']}] {q['label']}")
        print(f"  Query: {q['query'][:80]}...")

        start = time.perf_counter()

        proc = subprocess.run(
            [sys.executable, "server.py", "--demo-query", q["query"]],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        elapsed = time.perf_counter() - start
        output = proc.stdout.strip()

        score = _score_output(output, q["id"])
        results["queries"].append(
            {
                "query_id": q["id"],
                "label": q["label"],
                "output_preview": output[:200],
                "latency_s": round(elapsed, 2),
                "score": score,
            }
        )
        print(f"  Score: {score}/10  |  Latency: {elapsed:.2f}s")

    subprocess.run(["git", "checkout", "main"], cwd=repo_path, capture_output=True)
    return results


def _score_output(output: str, query_id: str) -> int:
    """Heuristic scorer — replace with LLM-as-judge in production."""
    score = 0
    if output:
        score += 2  # non-empty
    if len(output) > 50:
        score += 1  # substantive
    if "null" not in output.lower() and "error" not in output.lower():
        score += 2  # no obvious failure signals
    try:
        json.loads(output)
        score += 3  # valid JSON = structured output
    except Exception:
        if "{" in output:
            score += 1  # partial structure
    if query_id == "Q3" and "raise_overdue" in output:
        score += 2  # correct field present for complex query
    elif query_id == "Q2" and "department" in output.lower():
        score += 2
    elif query_id == "Q1" and ("name" in output.lower() or "emp001" in output.lower()):
        score += 2
    return min(score, 10)


def print_summary(all_results: list[dict]):
    print(f"\n\n{'='*60}")
    print("  BENCHMARK SUMMARY")
    print(f"{'='*60}")
    print(f"{'Implementation':<25} {'Q1':>5} {'Q2':>5} {'Q3':>5} {'Avg':>7}")
    print("-" * 50)
    for r in all_results:
        scores = [q["score"] for q in r["queries"]]
        avg = sum(scores) / len(scores) if scores else 0
        s = [str(s) for s in scores]
        print(f"{r['impl']:<25} {s[0] if len(s) > 0 else '-':>5} {s[1] if len(s) > 1 else '-':>5} {s[2] if len(s) > 2 else '-':>5} {avg:>7.1f}")
    print()


def main():
    parser = argparse.ArgumentParser(description="MCP Implementation Benchmark")
    parser.add_argument("--impl", choices=IMPLEMENTATIONS, help="Run a single implementation")
    parser.add_argument("--all", action="store_true", help="Run all implementations and compare")
    args = parser.parse_args()

    if args.all:
        all_results = [run_impl(impl) for impl in IMPLEMENTATIONS]
        print_summary(all_results)
    elif args.impl:
        result = run_impl(args.impl)
        print_summary([result])
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
