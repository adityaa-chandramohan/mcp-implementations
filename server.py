"""
impl/prompt-templates — Pattern 3: Prompt Templates MCP Server

The server exposes MCP Prompts — reusable, parameterized prompt templates that
enforce chain-of-thought reasoning and strict output format before the model
processes any data. Tools return typed JSON; templates direct how results are
composed and validated.

TRADEOFF: Highest output consistency and auditability. Requires template
           maintenance as domain evolves. Best for compliance/repeatable workflows.
"""

import argparse
import json
import statistics
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.prompts import base

mcp = FastMCP("hr-prompt-templates")

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

# ── TOOLS — typed JSON returns ─────────────────────────────────────────────────

@mcp.tool()
def get_employee(employee_id: str) -> dict:
    """Get full typed details for one employee."""
    emp = EMPLOYEES.get(employee_id.upper())
    if not emp:
        return {"error": f"No employee found with id={employee_id}"}
    return {"id": employee_id.upper(), **emp}


@mcp.tool()
def list_employees(department: str = "") -> list[dict]:
    """List employees, optionally filtered to a department."""
    result = []
    for eid, emp in EMPLOYEES.items():
        if department and emp["department"].lower() != department.lower():
            continue
        result.append({"id": eid, **emp})
    return result


@mcp.tool()
def get_headcount(department: str = "") -> dict:
    """Return headcount summary by department."""
    emps = list_employees(department)
    by_dept: dict[str, int] = {}
    for e in emps:
        by_dept[e["department"]] = by_dept.get(e["department"], 0) + 1
    return {"total": len(emps), "by_department": by_dept}


@mcp.tool()
def get_avg_salary(department: str = "") -> dict:
    """Return salary statistics per department."""
    emps = list_employees(department)
    if not emps:
        return {"error": "No employees found"}
    by_dept: dict[str, list[int]] = {}
    for e in emps:
        by_dept.setdefault(e["department"], []).append(e["salary"])
    result = {}
    for dept, salaries in by_dept.items():
        std = statistics.stdev(salaries) if len(salaries) > 1 else 0
        result[dept] = {
            "mean": round(statistics.mean(salaries)),
            "std_dev": round(std),
            "count": len(salaries),
        }
    return result


# ── PROMPTS — reusable, parameterized templates ────────────────────────────────

@mcp.prompt()
def analyze_employee(employee_id: str) -> str:
    """
    Template: Full employee profile analysis.
    Enforces structured output — use for HR audits.
    """
    return f"""You are an HR analytics assistant. Analyze employee {employee_id}.

Step 1: Call get_employee("{employee_id}") to retrieve the employee record.

Step 2: Output ONLY this JSON structure — do not add or remove any fields:
{{
  "id": "<employee_id>",
  "name": "<full name>",
  "department": "<department>",
  "salary": <integer>,
  "review_score": <float>,
  "raise_overdue": <true if last_raise_months_ago > 18 AND review_score >= 3.5, else false>,
  "salary_band": "<low | mid | high based on: low < 80000, mid 80000-150000, high > 150000>"
}}

If get_employee returns an error field, output: {{"error": "<message>", "id": "{employee_id}"}}
Never fabricate fields. Never include markdown outside the JSON block."""


@mcp.prompt()
def department_headcount_report(department: str = "") -> str:
    """
    Template: Department headcount and salary summary report.
    Enforces consistent report structure — use for monthly headcount audits.
    """
    dept_clause = f'for department "{department}"' if department else "for all departments"
    return f"""You are an HR analytics assistant generating a headcount report {dept_clause}.

Step 1: Call get_headcount("{department}") to get headcount numbers.
Step 2: Call get_avg_salary("{department}") to get salary statistics.

Step 3: Output ONLY this JSON — one entry per department found in the data:
[
  {{
    "department": "<name>",
    "headcount": <integer>,
    "avg_salary": <integer, rounded to nearest 1000>,
    "salary_std_dev": <integer>,
    "anomaly_flag": <true if std_dev > 40000, else false>
  }}
]

Rules:
- Use department names EXACTLY as returned by the tools.
- If a department has only 1 employee, set salary_std_dev to 0 and anomaly_flag to false.
- Do not include departments not present in the tool responses.
- Output valid JSON only. No prose, no markdown fences."""


@mcp.prompt()
def raise_eligibility_report(hired_before: str = "2022-01-01") -> str:
    """
    Template: Raise eligibility analysis for employees hired before a date.
    Enforces the raise_overdue business rule — use for compensation cycle planning.
    """
    return f"""You are an HR compensation analyst. Identify raise-eligible employees hired before {hired_before}.

Step 1: Call list_employees() to get all employee records.

Step 2: Filter to employees where:
  - hired < "{hired_before}"
  - last_raise_months_ago > 18
  - review_score >= 3.5

Step 3: Output ONLY this JSON array:
[
  {{
    "id": "<employee_id>",
    "name": "<full name>",
    "department": "<department>",
    "review_score": <float>,
    "last_raise_months_ago": <integer>,
    "raise_overdue": true
  }}
]

If no employees match the filter, output: []
Do not include employees who do not meet ALL three criteria.
Do not add fields not listed above.
Output valid JSON only."""


# ── Demo mode ──────────────────────────────────────────────────────────────────

def _demo(query: str):
    """Simulate the prompt-template guided output for benchmark."""
    query_lower = query.lower()

    if "emp001" in query_lower:
        # Simulate model following analyze_employee template
        emp = EMPLOYEES["EMP001"]
        result = {
            "id": "EMP001",
            "name": emp["name"],
            "department": emp["department"],
            "salary": emp["salary"],
            "review_score": emp["review_score"],
            "raise_overdue": emp["last_raise_months_ago"] > 18 and emp["review_score"] >= 3.5,
            "salary_band": "mid" if 80000 <= emp["salary"] <= 150000 else ("low" if emp["salary"] < 80000 else "high"),
        }
        print(json.dumps(result, indent=2))

    elif "headcount" in query_lower or "salary anomal" in query_lower:
        # Simulate model following department_headcount_report template
        report = []
        by_dept: dict[str, list] = {}
        for eid, emp in EMPLOYEES.items():
            by_dept.setdefault(emp["department"], []).append(emp)
        for dept, members in by_dept.items():
            salaries = [e["salary"] for e in members]
            std = round(statistics.stdev(salaries)) if len(salaries) > 1 else 0
            report.append({
                "department": dept,
                "headcount": len(members),
                "avg_salary": round(statistics.mean(salaries) / 1000) * 1000,
                "salary_std_dev": std,
                "anomaly_flag": std > 40000,
            })
        print(json.dumps(report, indent=2))

    elif "engineer" in query_lower and "review" in query_lower:
        # Simulate model following raise_eligibility_report template
        eligible = []
        for eid, emp in EMPLOYEES.items():
            if (emp["hired"] < "2022-01-01"
                    and emp["last_raise_months_ago"] > 18
                    and emp["review_score"] >= 3.5):
                eligible.append({
                    "id": eid,
                    "name": emp["name"],
                    "department": emp["department"],
                    "review_score": emp["review_score"],
                    "last_raise_months_ago": emp["last_raise_months_ago"],
                    "raise_overdue": True,
                })
        print(json.dumps(eligible, indent=2))

    else:
        emps = list_employees()
        print(json.dumps(emps, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-query", type=str, default=None)
    args = parser.parse_args()

    if args.demo_query:
        _demo(args.demo_query)
    else:
        mcp.run()
