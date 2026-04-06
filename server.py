"""
impl/basic-flat-tools — Pattern 1: Flat Tools MCP Server

Tools return raw unstructured strings. No schema, no resources, no templates.
The model must infer meaning and structure from plain text responses.

TRADEOFF: Fast to build, but output quality is non-deterministic — the model
           hallucination rate is high on aggregation and multi-step queries.
"""

import argparse
import json
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hr-basic")

# ── Fake HR data store ─────────────────────────────────────────────────────────
EMPLOYEES = {
    "EMP001": {"name": "Alice Chen",    "department": "Engineering", "salary": 98000, "hired": "2021-03-15", "manager": "Bob Kim",   "last_raise_months_ago": 8,  "review_score": 4.2},
    "EMP002": {"name": "Bob Kim",       "department": "Engineering", "salary": 145000,"hired": "2019-07-01", "manager": "Carol Day", "last_raise_months_ago": 22, "review_score": 4.7},
    "EMP003": {"name": "Carol Day",     "department": "Leadership",  "salary": 210000,"hired": "2018-01-10", "manager": None,        "last_raise_months_ago": 12, "review_score": 4.9},
    "EMP004": {"name": "David Park",    "department": "Engineering", "salary": 87000, "hired": "2022-09-01", "manager": "Bob Kim",   "last_raise_months_ago": 5,  "review_score": 3.8},
    "EMP005": {"name": "Eve Russo",     "department": "Marketing",   "salary": 75000, "hired": "2023-01-15", "manager": "Frank Yip", "last_raise_months_ago": 3,  "review_score": 4.0},
    "EMP006": {"name": "Frank Yip",     "department": "Marketing",   "salary": 120000,"hired": "2020-04-20", "manager": "Carol Day", "last_raise_months_ago": 20, "review_score": 4.3},
    "EMP007": {"name": "Grace Lam",     "department": "Engineering", "salary": 250000,"hired": "2021-11-30", "manager": "Bob Kim",   "last_raise_months_ago": 9,  "review_score": 4.8},
    "EMP008": {"name": "Henry Moss",    "department": "HR",          "salary": 68000, "hired": "2022-06-01", "manager": "Carol Day", "last_raise_months_ago": 6,  "review_score": 3.5},
}


# ── TOOLS — unstructured string returns ───────────────────────────────────────

@mcp.tool()
def get_employee(employee_id: str) -> str:
    """Get details for an employee by ID."""
    emp = EMPLOYEES.get(employee_id.upper())
    if not emp:
        return f"No employee found with ID {employee_id}"
    return (
        f"{emp['name']}, {emp['department']}, Salary: {emp['salary']}, "
        f"Hired: {emp['hired']}, Manager: {emp['manager']}, "
        f"Last raise: {emp['last_raise_months_ago']} months ago, "
        f"Review score: {emp['review_score']}"
    )


@mcp.tool()
def list_employees() -> str:
    """List all employees."""
    lines = []
    for eid, emp in EMPLOYEES.items():
        lines.append(f"{eid}: {emp['name']} ({emp['department']}) - ${emp['salary']}")
    return "\n".join(lines)


@mcp.tool()
def get_department_employees(department: str) -> str:
    """Get all employees in a department."""
    found = [(eid, e) for eid, e in EMPLOYEES.items()
             if e["department"].lower() == department.lower()]
    if not found:
        return f"No employees in department {department}"
    lines = [f"{eid}: {e['name']}, ${e['salary']}, hired {e['hired']}" for eid, e in found]
    return f"Department {department} ({len(found)} employees):\n" + "\n".join(lines)


@mcp.tool()
def get_salaries() -> str:
    """Get all salaries."""
    lines = [f"{e['name']}: ${e['salary']}" for e in EMPLOYEES.values()]
    return "\n".join(lines)


@mcp.tool()
def get_performance_reviews() -> str:
    """Get all performance review scores."""
    lines = [f"{e['name']} ({e['department']}): {e['review_score']}/5.0"
             for e in EMPLOYEES.values()]
    return "\n".join(lines)


# ── Demo mode: accepts a query arg and prints tool call result ─────────────────

def _demo(query: str):
    """Simulate a tool call based on query keyword — for benchmark only."""
    query_lower = query.lower()
    if "emp001" in query_lower:
        print(get_employee("EMP001"))
    elif "headcount" in query_lower or "department" in query_lower or "salary anomal" in query_lower:
        # Model would need to call list_employees + parse manually — simulate naive single call
        result = list_employees()
        print(result)
    elif "engineer" in query_lower and "review" in query_lower:
        result = get_performance_reviews()
        print(result)
    else:
        print(list_employees())


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-query", type=str, default=None)
    args = parser.parse_args()

    if args.demo_query:
        _demo(args.demo_query)
    else:
        mcp.run()
