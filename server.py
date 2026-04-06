"""
impl/stateful-memory — Pattern 4: Stateful Context MCP Server

The server maintains an in-process session store keyed by session_id.
Tools can read and write session state, enabling multi-step reasoning chains
where each tool call can access results from all prior calls in the session.

TRADEOFF: Best for complex, multi-step agentic workflows. Adds server-side
           complexity (storage, expiry, isolation). Not suited for stateless APIs.
"""

import argparse
import json
import statistics
import time
import uuid
from typing import Any
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("hr-stateful-memory")

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

# ── Session store — keyed by session_id ───────────────────────────────────────
# Structure: { session_id: { "created_at": float, "memory": {key: value}, "cache": {tool_key: result} } }
SESSION_STORE: dict[str, dict[str, Any]] = {}
SESSION_TTL_SECONDS = 3600  # sessions expire after 1 hour


def _get_or_create_session(session_id: str) -> dict:
    """Return existing session or create a new one."""
    _evict_expired_sessions()
    if session_id not in SESSION_STORE:
        SESSION_STORE[session_id] = {
            "created_at": time.time(),
            "last_accessed": time.time(),
            "memory": {},   # user-facing named facts
            "cache": {},    # tool result cache keyed by (tool_name, args)
            "call_log": [], # ordered list of tool calls made this session
        }
    else:
        SESSION_STORE[session_id]["last_accessed"] = time.time()
    return SESSION_STORE[session_id]


def _evict_expired_sessions():
    now = time.time()
    expired = [sid for sid, s in SESSION_STORE.items()
               if now - s["last_accessed"] > SESSION_TTL_SECONDS]
    for sid in expired:
        del SESSION_STORE[sid]


# ── SESSION MANAGEMENT TOOLS ───────────────────────────────────────────────────

@mcp.tool()
def create_session() -> dict:
    """
    Create a new session. Returns a session_id to pass to all subsequent tool calls.
    Always call this first at the start of a multi-step task.
    """
    session_id = str(uuid.uuid4())[:8]
    _get_or_create_session(session_id)
    return {"session_id": session_id, "status": "created"}


@mcp.tool()
def remember_fact(session_id: str, key: str, value: str) -> dict:
    """
    Store a named fact in session memory. Use to persist user corrections,
    derived conclusions, or intermediate results for later steps.
    """
    session = _get_or_create_session(session_id)
    session["memory"][key] = value
    return {"session_id": session_id, "stored": {key: value}, "memory_size": len(session["memory"])}


@mcp.tool()
def recall_facts(session_id: str) -> dict:
    """
    Retrieve all facts stored in this session's memory.
    Call at the start of each reasoning step to recover prior context.
    """
    session = _get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "memory": session["memory"],
        "call_log": session["call_log"][-10:],  # last 10 calls
    }


@mcp.tool()
def get_session_summary(session_id: str) -> dict:
    """Get a full summary of what has been learned in this session so far."""
    session = _get_or_create_session(session_id)
    return {
        "session_id": session_id,
        "age_seconds": round(time.time() - session["created_at"]),
        "memory": session["memory"],
        "cached_tools": list(session["cache"].keys()),
        "total_tool_calls": len(session["call_log"]),
    }


# ── HR TOOLS with session-aware caching ───────────────────────────────────────

@mcp.tool()
def get_employee(employee_id: str, session_id: str = "") -> dict:
    """
    Get employee details. Results are cached in session for the duration of the task.
    Pass session_id to avoid redundant fetches in multi-step workflows.
    """
    cache_key = f"get_employee:{employee_id.upper()}"

    if session_id:
        session = _get_or_create_session(session_id)
        if cache_key in session["cache"]:
            result = session["cache"][cache_key]
            result["_cached"] = True
            return result
        session["call_log"].append({"tool": "get_employee", "args": {"employee_id": employee_id}})

    emp = EMPLOYEES.get(employee_id.upper())
    if not emp:
        return {"error": f"No employee found with id={employee_id}", "id": employee_id}

    result = {"id": employee_id.upper(), **emp, "_cached": False}

    if session_id:
        session["cache"][cache_key] = {k: v for k, v in result.items() if k != "_cached"}

    return result


@mcp.tool()
def list_employees(department: str = "", session_id: str = "") -> list[dict]:
    """
    List employees, optionally filtered by department.
    Results are cached per department within the session.
    """
    cache_key = f"list_employees:{department.lower()}"

    if session_id:
        session = _get_or_create_session(session_id)
        if cache_key in session["cache"]:
            return session["cache"][cache_key]
        session["call_log"].append({"tool": "list_employees", "args": {"department": department}})

    result = []
    for eid, emp in EMPLOYEES.items():
        if department and emp["department"].lower() != department.lower():
            continue
        result.append({"id": eid, **emp})

    if session_id:
        session["cache"][cache_key] = result

    return result


@mcp.tool()
def flag_raise_eligible(session_id: str = "", hired_before: str = "2022-01-01") -> list[dict]:
    """
    Find employees overdue for a raise (last_raise_months_ago > 18 AND review_score >= 3.5).
    Stores result in session memory under key 'raise_eligible_employees'.
    """
    emps = list_employees(session_id=session_id)
    eligible = []
    for emp in emps:
        if (emp["hired"] < hired_before
                and emp["last_raise_months_ago"] > 18
                and emp["review_score"] >= 3.5):
            eligible.append({
                "id": emp["id"],
                "name": emp["name"],
                "department": emp["department"],
                "review_score": emp["review_score"],
                "last_raise_months_ago": emp["last_raise_months_ago"],
                "raise_overdue": True,
            })

    if session_id:
        remember_fact(session_id, "raise_eligible_employees", json.dumps(eligible))
        remember_fact(session_id, "raise_eligible_count", str(len(eligible)))

    return eligible


@mcp.tool()
def draft_raise_emails(session_id: str) -> list[dict]:
    """
    Draft raise notification emails for all employees flagged as raise-eligible in this session.
    Requires flag_raise_eligible to have been called first in this session.
    """
    session = _get_or_create_session(session_id)
    eligible_json = session["memory"].get("raise_eligible_employees")

    if not eligible_json:
        return [{"error": "No raise-eligible employees found in session memory. Call flag_raise_eligible first."}]

    eligible = json.loads(eligible_json)
    emails = []
    for emp in eligible:
        emails.append({
            "to": f"{emp['name'].lower().replace(' ', '.')}@company.com",
            "subject": f"Compensation Review — {emp['name']}",
            "body": (
                f"Hi {emp['name'].split()[0]},\n\n"
                f"Your last salary adjustment was {emp['last_raise_months_ago']} months ago. "
                f"Given your performance score of {emp['review_score']}/5.0, "
                f"you have been flagged for the upcoming compensation review cycle.\n\n"
                f"Your manager will reach out to discuss next steps.\n\nHR Team"
            ),
        })

    remember_fact(session_id, "emails_drafted", str(len(emails)))
    return emails


# ── Demo mode ──────────────────────────────────────────────────────────────────

def _demo(query: str):
    """Simulate a full stateful multi-step session for benchmark."""
    query_lower = query.lower()

    session = create_session()
    sid = session["session_id"]

    if "emp001" in query_lower:
        result = get_employee("EMP001", session_id=sid)
        print(json.dumps(result, indent=2))

    elif "headcount" in query_lower or "salary anomal" in query_lower:
        emps = list_employees(session_id=sid)
        by_dept: dict[str, list] = {}
        for e in emps:
            by_dept.setdefault(e["department"], []).append(e)
        report = []
        for dept, members in by_dept.items():
            salaries = [m["salary"] for m in members]
            std = round(statistics.stdev(salaries)) if len(salaries) > 1 else 0
            report.append({
                "department": dept,
                "headcount": len(members),
                "avg_salary": round(statistics.mean(salaries)),
                "salary_std_dev": std,
                "anomaly_flag": std > 40000,
            })
        remember_fact(sid, "headcount_report", json.dumps(report))
        summary = get_session_summary(sid)
        print(json.dumps({"report": report, "session_summary": summary}, indent=2))

    elif "engineer" in query_lower and "review" in query_lower:
        # Multi-step: list → flag → draft emails, all within one session
        eligible = flag_raise_eligible(session_id=sid)
        emails = draft_raise_emails(session_id=sid)
        session_summary = get_session_summary(sid)
        result = {
            "raise_eligible": eligible,
            "emails_drafted": emails,
            "session": {
                "id": sid,
                "total_tool_calls": session_summary["total_tool_calls"],
                "memory_keys": list(session_summary["memory"].keys()),
            },
        }
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps(list_employees(session_id=sid), indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo-query", type=str, default=None)
    args = parser.parse_args()

    if args.demo_query:
        _demo(args.demo_query)
    else:
        mcp.run()
