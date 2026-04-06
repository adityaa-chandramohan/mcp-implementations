"""
impl/resource-context — Pattern 2: Resource Injection MCP Server

MCP Resources pre-load domain knowledge (schema, business rules, data dictionary)
so the model always has grounded context before calling any tool.
Tools return typed JSON instead of raw strings.

TRADEOFF: More upfront schema design, but hallucination drops sharply because
           the model reasons against an explicit schema rather than inferring structure.
"""

import argparse
import json
import math
import statistics
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hr-resource-context")

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

# ── RESOURCES — persistent, addressable domain knowledge ──────────────────────

@mcp.resource("hr://schema/employee")
def employee_schema() -> str:
    """Canonical schema for the Employee object. Always load this first."""
    schema = {
        "Employee": {
            "id":                    {"type": "string",  "format": "EMPXXX",  "description": "Unique employee ID"},
            "name":                  {"type": "string",  "description": "Full name"},
            "department":            {"type": "string",  "enum": ["Engineering", "Marketing", "HR", "Leadership"],
                                     "description": "Department name — use exactly as listed"},
            "salary":                {"type": "integer", "unit": "CAD_annual", "description": "Annual salary in CAD"},
            "hired":                 {"type": "string",  "format": "YYYY-MM-DD"},
            "manager":               {"type": "string|null", "description": "Manager full name, null for C-level"},
            "last_raise_months_ago": {"type": "integer", "description": "Months since last salary adjustment"},
            "review_score":          {"type": "float",   "range": "0.0-5.0",  "description": "Last performance review score"},
        }
    }
    return json.dumps(schema, indent=2)


@mcp.resource("hr://rules/salary-anomaly")
def salary_anomaly_rules() -> str:
    """Business rules for flagging salary anomalies. Use when analyzing compensation."""
    rules = {
        "anomaly_definition": "A salary is flagged as anomalous if it is more than 2 standard deviations from the department mean.",
        "raise_overdue_threshold_months": 18,
        "raise_overdue_definition": "last_raise_months_ago > 18 AND review_score >= 3.5",
        "high_performer_threshold": 4.5,
        "currency": "CAD",
        "note": "Salary data is annual gross. Do not infer monthly or hourly rates without explicit conversion."
    }
    return json.dumps(rules, indent=2)


@mcp.resource("hr://meta/departments")
def department_metadata() -> str:
    """Known departments and their cost centres. Use to validate department names in queries."""
    meta = {
        "departments": [
            {"name": "Engineering",  "cost_centre": "CC-ENG-001", "headcount_target": 5},
            {"name": "Marketing",    "cost_centre": "CC-MKT-002", "headcount_target": 3},
            {"name": "HR",           "cost_centre": "CC-HR-003",  "headcount_target": 2},
            {"name": "Leadership",   "cost_centre": "CC-LEAD-004","headcount_target": 2},
        ]
    }
    return json.dumps(meta, indent=2)


# ── TOOLS — typed JSON returns ─────────────────────────────────────────────────

@mcp.tool()
def get_employee(employee_id: str) -> dict:
    """
    Get full details for a single employee.
    Returns a dict matching the hr://schema/employee resource.
    """
    emp = EMPLOYEES.get(employee_id.upper())
    if not emp:
        return {"error": f"No employee found with id={employee_id}", "id": employee_id}
    return {"id": employee_id.upper(), **emp}


@mcp.tool()
def list_employees(department: str = "") -> list[dict]:
    """
    List employees, optionally filtered by department.
    Each record matches the hr://schema/employee resource.
    """
    result = []
    for eid, emp in EMPLOYEES.items():
        if department and emp["department"].lower() != department.lower():
            continue
        result.append({"id": eid, **emp})
    return result


@mcp.tool()
def get_headcount(department: str = "") -> dict:
    """Get headcount summary. Optionally filter to one department."""
    all_emps = list_employees(department)
    by_dept: dict[str, int] = {}
    for e in all_emps:
        by_dept[e["department"]] = by_dept.get(e["department"], 0) + 1
    return {"total": len(all_emps), "by_department": by_dept}


@mcp.tool()
def get_avg_salary(department: str = "") -> dict:
    """Get average salary. Returns mean, std_dev, min, max per department."""
    emps = list_employees(department)
    if not emps:
        return {"error": f"No employees found for department={department!r}"}

    by_dept: dict[str, list[int]] = {}
    for e in emps:
        by_dept.setdefault(e["department"], []).append(e["salary"])

    result = {}
    for dept, salaries in by_dept.items():
        std = statistics.stdev(salaries) if len(salaries) > 1 else 0
        result[dept] = {
            "mean": round(statistics.mean(salaries)),
            "std_dev": round(std),
            "min": min(salaries),
            "max": max(salaries),
            "count": len(salaries),
        }
    return result


@mcp.tool()
def flag_salary_anomalies() -> list[dict]:
    """
    Apply the hr://rules/salary-anomaly resource rules.
    Returns employees whose salary exceeds 2 std dev from their department mean.
    """
    by_dept: dict[str, list] = {}
    for eid, emp in EMPLOYEES.items():
        by_dept.setdefault(emp["department"], []).append((eid, emp))

    anomalies = []
    for dept, members in by_dept.items():
        salaries = [e["salary"] for _, e in members]
        if len(salaries) < 2:
            continue
        mean = statistics.mean(salaries)
        std = statistics.stdev(salaries)
        for eid, emp in members:
            z = abs(emp["salary"] - mean) / std if std else 0
            if z > 2:
                anomalies.append({
                    "id": eid,
                    "name": emp["name"],
                    "department": dept,
                    "salary": emp["salary"],
                    "dept_mean": round(mean),
                    "z_score": round(z, 2),
                    "flag": "salary_anomaly",
                })
    return anomalies


# ── Demo mode ─────────────────────────────────────────────────────────────────

def _demo(query: str):
    query_lower = query.lower()
    if "emp001" in query_lower:
        print(json.dumps(get_employee("EMP001"), indent=2))
    elif "headcount" in query_lower or "salary anomal" in query_lower:
        headcount = get_headcount()
        avg = get_avg_salary()
        anomalies = flag_salary_anomalies()
        print(json.dumps({"headcount": headcount, "avg_salary": avg, "anomalies": anomalies}, indent=2))
    elif "engineer" in query_lower and "review" in query_lower:
        engineers = list_employees("Engineering")
        overdue = [
            {"id": e["id"], "name": e["name"], "department": e["department"],
             "review_score": e["review_score"],
             "raise_overdue": e["last_raise_months_ago"] > 18 and e["review_score"] >= 3.5}
            for e in engineers if e["hired"] < "2022-01-01"
        ]
        print(json.dumps(overdue, indent=2))
    else:
        print(json.dumps(list_employees(), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-query", type=str, default=None)
    args = parser.parse_args()

    if args.demo_query:
        _demo(args.demo_query)
    else:
        mcp.run()
