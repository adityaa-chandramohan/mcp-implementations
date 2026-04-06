# MCP Implementation Patterns — Comparative Study

> **Model Context Protocol (MCP)** is Anthropic's open standard for connecting AI models to external tools, data sources, and context. This repo demonstrates that **the same model produces dramatically different result quality** depending purely on *how* the MCP server is architected — not which model you use.

---

## Why This Matters

Most discussions about LLM output quality focus on model selection or prompt wording. This repo proves a third lever: **MCP server design**. The same Claude model, given identical user queries, will produce inconsistent, hallucinated, or shallow responses with a naive MCP implementation — and grounded, structured, reproducible responses with a well-designed one.

---

## The Four Implementation Patterns

Each pattern is a separate branch. They all expose the same domain (a fictional HR system) and use the same model. Only the MCP architecture differs.

| Branch | Pattern | Core Mechanic | Best For |
|--------|---------|---------------|----------|
| `impl/basic-flat-tools` | **Flat Tools** | Tools return raw unstructured strings | Baseline / prototyping |
| `impl/resource-context` | **Resource Injection** | MCP Resources pre-load domain knowledge | Knowledge-heavy domains |
| `impl/prompt-templates` | **Prompt Templates** | Server-side prompt templates enforce structure | Repeatable, auditable workflows |
| `impl/stateful-memory` | **Stateful Context** | Session state persists across tool calls | Multi-step reasoning chains |

---

## Pattern 1 — Flat Tools (`impl/basic-flat-tools`)

### What it does
Tools are defined with minimal schema. They return raw string blobs. The model must interpret structure from untyped text.

```python
@mcp.tool()
def get_employee(employee_id: str) -> str:
    return f"John Doe, Senior Engineer, Dept: Engineering, Salary: 95000, Manager: Jane Smith"
```

### Pros
- Fastest to build
- Zero boilerplate — great for quick proofs of concept
- Works fine for single, simple lookups

### Cons
- Model must infer schema from prose — hallucination-prone on edge cases
- No reusable context; every call starts cold
- Output format varies between runs (non-deterministic structure)
- Tool errors are strings — model cannot distinguish error from data
- Scales poorly: adding tools creates context fragmentation

### Result Quality
Queries like "Summarize headcount by department and flag any salary anomalies" produce **inconsistent summaries** — the model invents categories not in the data, mis-attributes managers, and formats output differently each run.

---

## Pattern 2 — Resource Injection (`impl/resource-context`)

### What it does
MCP Resources (persistent, addressable content) load domain knowledge before tool calls. Tools return typed JSON. The model always has a grounded schema to reason against.

```python
@mcp.resource("hr://schema/employee")
def employee_schema() -> str:
    """Returns the canonical employee data schema."""
    return json.dumps(EMPLOYEE_SCHEMA)

@mcp.tool()
def get_employee(employee_id: str) -> dict:
    return {"id": employee_id, "name": "John Doe", "department": "Engineering", ...}
```

### Pros
- Resources act as a persistent knowledge base — model knows field meanings before calling tools
- Typed returns eliminate structural hallucination
- Resources are cacheable; reduces redundant context tokens
- Schema + tool separation follows MCP's design intent
- Strong fit for document-heavy domains (legal, compliance, finance)

### Cons
- More upfront design work (schema definition)
- Resources add to context window budget — must be managed for large domains
- Resource content must be kept in sync with tool return shapes
- Not suited for deeply dynamic data where schema changes frequently

### Result Quality
Same headcount/salary query produces **structured, schema-consistent output** every run. Department names match exactly, salary figures are never fabricated, and the model's reasoning cites the loaded schema resource.

---

## Pattern 3 — Prompt Templates (`impl/prompt-templates`)

### What it does
The MCP server exposes Prompts — reusable, parameterized prompt templates — alongside tools. The client selects a template; the server returns a fully-formed message sequence that enforces chain-of-thought and output format before the model ever speaks.

```python
@mcp.prompt()
def analyze_department(department: str) -> list[PromptMessage]:
    return [
        PromptMessage(role="user", content=f"""
        You are an HR analytics assistant. For department '{department}':
        1. Call get_headcount('{department}')
        2. Call get_avg_salary('{department}')
        3. Output JSON: {{"department": ..., "headcount": ..., "avg_salary": ..., "flag": ...}}
        Never add fields not in the schema. If a tool errors, set the field to null.
        """)
    ]
```

### Pros
- Output format is **guaranteed** — templates encode the expected structure
- Chain-of-thought reasoning is explicit and auditable
- Reusable across teams/clients — one source of truth for complex queries
- Versioning templates = versioning your AI workflows (treat like code)
- Best pattern for compliance/audit trails where reproducibility is required

### Cons
- Adds a template management layer — templates must be maintained as domain evolves
- Less flexible for ad-hoc exploration (template must pre-exist)
- Complex templates can be hard to debug if tool outputs change
- Requires clients to know which template to invoke (discovery overhead)

### Result Quality
The headcount/salary query **always returns identical JSON structure**. Output can be piped directly into downstream systems. Compliance teams can verify the exact reasoning chain from the template version alone.

---

## Pattern 4 — Stateful Memory (`impl/stateful-memory`)

### What it does
The server maintains a session store keyed by `session_id`. Each tool call can read and write to the session. Prior tool results, user corrections, and derived facts persist across the entire conversation. The model never re-fetches what it already knows.

```python
@mcp.tool()
def get_employee(employee_id: str, session_id: str) -> dict:
    if session_id in SESSION_STORE and employee_id in SESSION_STORE[session_id]:
        return SESSION_STORE[session_id][employee_id]  # cache hit
    data = fetch_employee(employee_id)
    SESSION_STORE.setdefault(session_id, {})[employee_id] = data
    return data

@mcp.tool()
def remember_fact(session_id: str, key: str, value: str) -> str:
    SESSION_STORE.setdefault(session_id, {})["facts"] = {key: value}
    return f"Remembered: {key} = {value}"
```

### Pros
- Enables **multi-step reasoning** without re-fetching data
- Model can build up a working set across a long task
- User corrections ("no, John's role changed") persist for the session
- Dramatically reduces tool call count for complex analytical tasks
- Best pattern for agentic, autonomous workflows

### Cons
- Session state adds server-side complexity (storage, expiry, concurrency)
- Memory can contain stale or contradictory facts — requires invalidation logic
- Harder to debug: output depends on full session history, not just current call
- Not appropriate for stateless, isolated requests (e.g., single-turn APIs)
- Security surface is larger — session data must be isolated per user

### Result Quality
Complex multi-step queries ("Find all engineers, check their last review scores, flag anyone overdue, then draft emails") succeed **end-to-end without context loss**. Without state, the same task requires the model to re-fetch data and frequently loses intermediate results across tool calls.

---

## Side-by-Side Comparison

| Dimension | Flat Tools | Resource Injection | Prompt Templates | Stateful Memory |
|-----------|-----------|-------------------|-----------------|-----------------|
| Setup complexity | Low | Medium | Medium-High | High |
| Output consistency | Poor | Good | Excellent | Good |
| Hallucination risk | High | Low | Very Low | Low |
| Multi-step tasks | Poor | Moderate | Moderate | Excellent |
| Auditability | Low | Medium | High | Medium |
| Token efficiency | High | Medium | Medium | High |
| Schema enforcement | None | Implicit | Explicit | Implicit |
| Scalability | Poor | Good | Good | Excellent |
| Best use case | Prototyping | Knowledge bases | Compliance/audits | Agentic pipelines |

---

## Running the Demo

### Prerequisites
```bash
python -m venv .venv && source .venv/bin/activate
pip install mcp fastmcp anthropic
```

### Run any implementation
```bash
git checkout impl/basic-flat-tools    # or any other branch
python server.py                       # starts the MCP server on stdio
```

### Run the test client (from main branch)
```bash
python demo_client.py --impl basic-flat-tools   # compares output quality
python demo_client.py --impl resource-context
python demo_client.py --impl prompt-templates
python demo_client.py --impl stateful-memory
```

### Expected output
The client runs the same 3 benchmark queries against each implementation and scores output on: completeness, format consistency, hallucination rate, and token cost.

---

## Choosing the Right Pattern

```
Is this a prototype or demo?
  └─ YES → impl/basic-flat-tools

Does the domain have rich background knowledge (docs, schemas, policies)?
  └─ YES → impl/resource-context

Is reproducible, auditable output required (compliance, finance, legal)?
  └─ YES → impl/prompt-templates

Are you building an agentic pipeline with multi-step reasoning?
  └─ YES → impl/stateful-memory

Can you mix patterns?
  └─ YES — production systems typically combine Resource Injection (for grounding)
            with Prompt Templates (for workflows) and Stateful Memory (for agents)
```

---

## Author

**Aditya S. Chandramohan** — Senior QA Manager · Test Architect · GenAI Solutions Architect  
[Portfolio](https://adityaa-chandramohan.github.io/website) · [GitHub](https://github.com/adityaa-chandramohan)

---

> *This repo is part of a series demonstrating AI architecture patterns for quality-critical enterprise systems.*
