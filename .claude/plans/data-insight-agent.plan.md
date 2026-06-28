# Plan: DataInsight — Milestone 1 — State Machine Skeleton + Data Track

**Source PRD**: [.claude/prds/data-insight-agent.prd.md](../.claude/prds/data-insight-agent.prd.md)
**Selected Milestone**: #1 — Four-stage state machine skeleton + Data Track node
**Complexity**: Medium

## Summary
Establish the project skeleton (pyproject.toml, src/ layout, LangGraph state machine with 4 placeholder nodes) and implement the **Data Track** node end-to-end: a deterministic sandbox script that extracts `df.info()`, `df.describe()`, `df.isnull().sum()`, and first 5 rows from a user-provided CSV/Excel file, then feeds that structured metadata to an LLM that produces a *Data Technical Audit Report* (《数据技术盘报告》). The other three nodes remain stubs wired into the graph so the full pipeline shape is visible and testable.

## Patterns to Mirror
Since this is a greenfield project with no existing code, the patterns below are derived from the project's ECC Python rules and CLAUDE.md.

| Category | Source | Pattern |
|---|---|---|
| Naming | ECC `python/coding-style.md` | Files: `snake_case.py`; Classes: `PascalCase`; Functions: `snake_case` with type annotations |
| Immutability | ECC `python/coding-style.md` | State objects as `frozen=True` dataclasses or `NamedTuple`; never mutate in place |
| Error handling | ECC `common/coding-style.md` | Explicit at every level; never silently swallow; fail fast with clear messages |
| Testing | ECC `python/testing.md` | `pytest` with `@pytest.mark.unit` / `@pytest.mark.integration` markers; AAA pattern |
| Package layout | CLAUDE.md `src/` convention | `src/agent/`, `src/sandbox/`, `src/analysis/`, `src/report/`; tests mirror `src/` |
| Config | CLAUDE.md tooling | `ruff check .`, `ruff format .`, `mypy src/`, `pytest -v` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `pyproject.toml` | CREATE | Project metadata, dependencies (langgraph, langchain, pandas, openpyxl, matplotlib, pytest), tool configs |
| `src/__init__.py` | CREATE | Package root |
| `src/agent/__init__.py` | CREATE | Agent package |
| `src/agent/state.py` | CREATE | LangGraph `AgentState` (TypedDict or Pydantic model) — the shared state object flowing through all 4 nodes |
| `src/agent/graph.py` | CREATE | LangGraph `StateGraph` definition with 4 nodes + conditional edges |
| `src/agent/nodes/__init__.py` | CREATE | Nodes subpackage |
| `src/agent/nodes/data_track.py` | CREATE | **Data Track node**: runs deterministic sandbox script, calls LLM, produces audit report |
| `src/agent/nodes/business_track.py` | CREATE | Stub for Business Track node (raises `NotImplementedError` with TODO) |
| `src/agent/nodes/decision_match.py` | CREATE | Stub for Decision Match node |
| `src/agent/nodes/execution.py` | CREATE | Stub for Execution node |
| `src/agent/nodes/report_gen.py` | CREATE | Stub for Report Generation node |
| `src/sandbox/__init__.py` | CREATE | Sandbox package |
| `src/sandbox/executor.py` | CREATE | Sandbox execution harness: subprocess-based Python runner with timeout, captures stdout/stderr |
| `src/sandbox/inspection_script.py` | CREATE | **Deterministic inspection script template**: `df.info()`, `df.describe()`, `df.isnull().sum()`, `df.head(5)` |
| `src/agent/llm.py` | CREATE | LLM client factory (LangChain chat model wrapper, provider-agnostic) |
| `tests/__init__.py` | CREATE | Test package |
| `tests/conftest.py` | CREATE | Shared fixtures: sample CSV fixture, mock LLM, sandbox config |
| `tests/test_data_track.py` | CREATE | Unit tests for Data Track node: inspection output parsing, LLM prompt structure, audit report format |
| `tests/test_graph.py` | CREATE | Unit tests for graph topology: correct node ordering, state passing between nodes |
| `tests/test_sandbox.py` | CREATE | Unit tests for sandbox executor: timeout behavior, stdout capture, error propagation |

## Tasks

### Task 1: Project scaffolding & dependency wiring
- **Action**: Create `pyproject.toml` with all dependencies and tool configs (ruff, mypy, pytest). Create `src/` and `tests/` directory trees with `__init__.py` files. Run `pip install -e ".[dev]"` to verify installability.
- **Mirror**: CLAUDE.md stack spec; ECC python/coding-style.md tooling (ruff, mypy, pytest)
- **Validate**: `python -c "import src"` succeeds; `ruff check .` passes on empty tree

### Task 2: Define AgentState & LangGraph skeleton
- **Action**: Define `AgentState` as a frozen/Pydantic model in `src/agent/state.py` with fields: `file_path`, `user_requirement`, `data_report`, `business_plan`, `execution_plan`, `execution_result`, `final_report`, `error`. Build the 4-node `StateGraph` in `src/agent/graph.py` with all nodes as stubs, wire sequential edges (Data → Business → Decision → Execution → Report), and verify the graph compiles.
- **Mirror**: `dataclass(frozen=True)` from ECC python/patterns.md; LangGraph `StateGraph` pattern
- **Validate**: `python -c "from src.agent.graph import build_graph; g = build_graph(); print(g.get_graph().draw_ascii())"` shows 5 nodes with correct edges

### Task 3: Implement sandbox inspection script
- **Action**: Write `src/sandbox/inspection_script.py` — a deterministic Python script template that takes a file path argument, loads it with pandas, and prints structured JSON containing: column names, dtypes, null counts, descriptive statistics, first 5 rows. This script is NEVER generated by the LLM — it is a fixed, trusted asset.
- **Mirror**: PRD requirement that Data Track uses a fixed script (not LLM-generated code) to prevent hallucination
- **Validate**: Run against a sample CSV fixture, verify JSON output schema is correct

### Task 4: Implement sandbox executor
- **Action**: Write `src/sandbox/executor.py` — a `run_script(script_path, args, timeout_seconds)` function that spawns a subprocess, captures stdout/stderr, enforces timeout, and returns a structured result (`SandboxResult` with `stdout`, `stderr`, `exit_code`, `timed_out`). No network access allowed; file system access limited to the input file.
- **Mirror**: PRD risk mitigation: "Sandbox execution capped with timeout (120s); sandbox security boundary"
- **Validate**: `pytest tests/test_sandbox.py -v` — tests cover normal execution, timeout, script error, and stdout capture

### Task 5: Implement LLM client factory
- **Action**: Write `src/agent/llm.py` — a factory that returns a LangChain `BaseChatModel` configured from environment variables (`DATAINSIGHT_LLM_PROVIDER`, `DATAINSIGHT_LLM_MODEL`, `DATAINSIGHT_LLM_API_KEY`). Default to OpenAI-compatible chat model. Include a `get_llm()` function used by all nodes.
- **Mirror**: CLAUDE.md "LangChain / LangGraph (agent orchestration)"; common/security.md "secrets from env vars, never hardcoded"
- **Validate**: `python -c "from src.agent.llm import get_llm; llm = get_llm(); print(type(llm))"` (mock key OK — just verify no import errors)

### Task 6: Implement Data Track node
- **Action**: Write `src/agent/nodes/data_track.py` with a `data_track_node(state: AgentState) -> AgentState` function that:
  1. Calls sandbox executor with the inspection script + user's file path
  2. Parses the JSON output (column metadata, null counts, stats, head sample)
  3. Constructs a prompt instructing the LLM to role-play a strict data auditor
  4. Calls LLM to produce a *Data Technical Audit Report* (fields, missingness, anomaly risks, columns needing aggressive cleaning)
  5. Writes the report into `state.data_report` and returns the updated state
- **Mirror**: PRD Phase 1 Data Track specification; common/coding-style.md "Explicit error handling at every level"
- **Validate**: `pytest tests/test_data_track.py -v` — mock LLM, verify prompt contains inspection data, verify returned state has `data_report` populated

### Task 7: Wire Data Track into graph & end-to-end smoke test
- **Action**: Replace the Data Track stub in `src/agent/graph.py` with the real implementation. Write an integration test in `tests/test_graph.py` that:
  1. Creates a temp CSV with known content
  2. Builds the graph with 1 real node + 3 stubs
  3. Invokes the graph with a mock LLM
  4. Asserts `state.data_report` is populated and the other nodes were visited
- **Mirror**: PRD four-stage philosophy; AAA test pattern
- **Validate**: `pytest tests/test_graph.py -v` — integration test passes

## Validation

```bash
# Install
pip install -e ".[dev]"

# Lint & type check
ruff check . && ruff format --check . && mypy src/

# Unit tests
pytest -v -m unit

# Integration test (graph smoke test)
pytest -v -m integration

# All tests with coverage
pytest -v --cov=src --cov-report=term-missing
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| LangGraph API changes between versions | Medium | Pin exact version in pyproject.toml; use the stable `StateGraph` API |
| LLM SDK compatibility (LangChain deprecations) | Medium | Use the `langchain-core` chat model abstraction, not provider-specific imports |
| Sandbox subprocess isolation on Windows | Low | Use `subprocess.run()` which is cross-platform; test on Windows first (our target platform) |
| Inspection script fails on non-UTF-8 encoded CSVs | Low | Pandas `read_csv` with `encoding` detection fallback; wrap in try/except with clear error message |

## Acceptance

- [ ] All tasks complete
- [ ] Validation passes (ruff, mypy, pytest green)
- [ ] Graph compiles and shows 4 nodes in correct order
- [ ] Data Track produces a structured audit report from a real CSV
- [ ] Stub nodes raise clear `NotImplementedError` (not silent pass)
- [ ] Patterns mirrored, not reinvented

---
*Plan for Milestone 1 of 4. Subsequent milestones will be planned after M1 is complete.*
