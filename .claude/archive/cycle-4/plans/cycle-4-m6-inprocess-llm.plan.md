# Plan: Cycle 4 M6 — In-Process LLM + Session Persistence

**Source PRD**: (none — architectural refinement from Cycle 4 retro)
**Selected Milestone**: 5.1 — In-process LLM for Transform/Filter, session persistence
**Complexity**: Large

## Summary

Two interconnected changes: (1) Move Transform/Filter LLM execution from subprocess sandbox to in-process `exec()` with restricted namespace, unifying them onto the same template dispatch path; (2) Persist full session state to disk so a completed analysis becomes a permanent dashboard — re-opening a session shows results without re-execution. Terminal units keep their subprocess sandbox.

## Driving Principles

- **"Run once, view forever"** — complete session state (plan, unit source code, charts, insights, report) survives restarts
- **Haiku for Transform/Filter, Sonnet for Terminal** — simple column contracts don't need a big model; save latency and cost
- **Stored source code is for persistence, not rerun** — rerun always re-invokes the LLM (bug fix or changed requirements = old code is stale); stored code powers the "view forever" guarantee
- **Template dispatch is the single execution path** — LLM generates a function body, `exec()` compiles it into a callable, then `dispatch()` handles everything downstream (build result, contract validation, checkpoint)

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Template dispatch | `src/agent/templates.py:214-262` | `dispatch(unit, df, output_dir)` returns result dict or None |
| Template result building | `src/agent/templates.py:265-318` | `_build_template_result(unit, output, output_dir, df)` attaches `_result_df` |
| Contract validation | `src/agent/dag.py:480-492` | `_save_unit_checkpoint` checks row count + output_columns |
| LLM invocation | `src/agent/nodes/analysis.py:257-260` | `get_llm(temperature=0, node="analysis").invoke(prompt)` |
| Static guard | `src/sandbox/static_guard.py` | `check_static(code) -> (safe, reason)` — keep for LLM-generated code |
| Session store | `src/api/session.py` | In-memory `SessionStore`, `store.update(session_id, patch)` |
| Test fixtures | `tests/conftest.py:48-75` | `sample_csv_100_rows`, `tmp_path`, `sample_plan` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/nodes/analysis.py` | UPDATE (heavy) | Replace subprocess path for Transform/Filter with in-process `exec()`; remove ~150 lines of subprocess/CSV/JSON parsing; keep Terminal subprocess path |
| `src/agent/templates.py` | UPDATE | Add `exec_llm_function(body, safe_ns) -> TemplateFunc` helper |
| `src/agent/state.py` | UPDATE | Add `persisted_at: str | None` to AgentState; execution metadata remains in unit results, not PlanUnit |
| `src/api/session.py` | UPDATE | Add `save(session_id) -> path` and `load(session_id) -> AgentState` for disk persistence |
| `src/sandbox/executor.py` | UPDATE (trim) | Keep only Terminal path; deprecate generic `run_script` if no longer used by analysis |
| `tests/test_analysis.py` | UPDATE | Add in-process LLM tests; remove subprocess-mock tests for Transform/Filter path |
| `tests/test_templates.py` | UPDATE | Add `exec_llm_function` tests |

## Tasks

### Task 1: Add `exec_llm_function` to templates.py
- **Action**: New helper `exec_llm_function(code: str) -> TemplateFunc`:
  - Runs `check_static(code)` first — reject if unsafe
  - Constructs restricted namespace: `{"pd": pd, "np": np, "__builtins__": {"len": len, "range": range, ...}}` — no `os`, `sys`, `subprocess`, `open`, `eval`, `exec`, `__import__`
  - `exec(code, safe_ns)` to compile
  - Returns the compiled callable matching `TemplateFunc` signature `(df, input_columns, params) -> dict`
  - Raises on static guard failure or syntax error
- **Mirror**: `src/sandbox/static_guard.py` (check_static), `src/agent/templates.py:29` (TemplateFunc type)
- **Validate**: `pytest -v -m unit tests/test_templates.py::test_exec_llm_function_*`

### Task 2: Rewrite LLM path in `_execute_unit` for Transform/Filter
- **Action**: In `_execute_unit` (analysis.py), split by unit_type:
  - **Transform / Filter**: LLM generates function body via Haiku (new prompt: "Write a Python function body..."), `exec_llm_function(body)` compiles it, call it with `(df, input_columns, params)`, pass result to `_template_dispatch` → `_build_template_result`. If function raises, ReAct re-prompts Haiku with the error. **No subprocess, no CSV round-trip.**
  - **Terminal**: Keep existing subprocess path (Sonnet, sandbox, output.csv, JSON stdout).
  - Store `source_code` and `model_used` in the result dict.
- **Mirror**: `src/agent/nodes/analysis.py:257-361` (existing LLM + ReAct loop)
- **Validate**: `pytest -v -m unit tests/test_analysis.py`

### Task 3: Add session persistence to SessionStore
- **Action**: Add `save(session_id)` and `load(session_id)` class methods to SessionStore:
  - Persist to `data/sessions/{session_id}/state.json` with atomic replacement
  - Strip executor-only keys beginning with `_` before JSON serialization
  - Load reconstructs AgentState via `AgentState(**json.loads(...))`
  - API calls `save()` after each state mutation (plan generated, unit executed, report generated)
  - `load()` called on session open (GET /sessions/{id})
- **Mirror**: `src/api/session.py` (existing SessionStore class)
- **Validate**: `pytest -v -m unit tests/api/test_session.py` (new file)

### Task 4: Remove dead subprocess code
- **Action**: After Task 2, the subprocess path is only used for Terminal units:
  - `_build_unit_code_prompt` and `_build_unit_react_fix_prompt` → keep only Terminal variant(s)
  - Remove CSV/JSON-parsing logic from the Transform/Filter flow (already unused after Task 2)
  - `sandbox/executor.py` → mark `run_script` as Terminal-only with docstring
  - Remove imports no longer needed in analysis.py
- **Mirror**: `src/agent/nodes/analysis.py:47-361` (current complete _execute_unit)
- **Validate**: `pytest -v` — all existing tests pass

### Task 5: Update tests
- **Action**:
  - Add `test_exec_llm_function_safe` — valid code compiles and runs
  - Add `test_exec_llm_function_blocked` — unsafe code rejected by static_guard
  - Add `test_exec_llm_function_syntax_error` — broken code raises
  - Add `test_inprocess_transform_llm` — Haiku generates transform fn, exec runs it, contract validated
  - Add `test_inprocess_filter_llm` — same for filter
  - Add `test_inprocess_react_retry` — broken fn → Haiku fixes → succeeds
  - Add `test_session_persist_roundtrip` — save state, load state, verify equality
  - Update existing analysis tests that mock `run_script` / `subprocess` to use the new exec path
- **Mirror**: `tests/test_analysis.py`, `tests/test_templates.py`
- **Validate**: `pytest -v` — all tests pass

## Validation

```bash
pytest -v -m unit tests/test_templates.py     # exec_llm_function
pytest -v -m unit tests/test_analysis.py      # in-process LLM flow
pytest -v -m unit tests/test_dag.py           # contract validation still works
pytest -v                                       # full suite (269 passed at closure)
ruff check .
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `exec()` restricted namespace incomplete — LLM code accesses `open()` via `__builtins__` loophole | Medium | Audit `__builtins__` allowlist carefully; keep `static_guard` as first line of defense (rejects `open`, `os`, `subprocess` at AST level) |
| Haiku generates lower-quality code than Sonnet for Transform/Filter | Low | Contracts are extremely constrained (2-3 input cols, ~5 lines of pandas); Haiku handles this easily |
| ReAct loop with `exec()` leaks namespace state between retries | Low | Fresh namespace dict per `exec()` call; no shared state across retries |
| Session JSON files grow large (100+ unit results) | Low | Store per-unit chart PNGs separately; JSON only has paths, insights, source code (text) |
| Existing subprocess-mock tests break | Medium | Update tests in Task 5 alongside the refactoring; test incrementally after each task |

## Acceptance

- [x] Transform/Filter LLM units execute in-process via `exec()` + restricted namespace
- [x] Terminal LLM units still run in subprocess sandbox
- [x] Source code and concrete model metadata are stored in unit results
- [x] Session state survives restart (`state.json` on disk)
- [x] ReAct retry handles generation, compilation, execution, and contract failures
- [x] All tests pass (269)
- [x] `ruff check .` clean
- [x] `mypy src/` clean

---
*Status: COMPLETE — closed with Cycle 4.*
