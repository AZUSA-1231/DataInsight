# Plan: M4 — Test & Validate

**Source PRD**: .claude/prds/dag-executor.prd.md
**Selected Milestone**: M4 — Test & Validate
**Complexity**: Medium

## Summary

M4 closes the DAG Executor PRD by filling test coverage gaps introduced in M3,
adding a real-sandbox DAG E2E smoke test, and verifying all four PRD success
metrics. M3 delivered 30 new tests (dag.py pure functions) and all 181 existing
tests pass — M4 tightens the remaining ~4% coverage gap in dag.py/analysis.py
and validates the end-to-end DAG flow with a real subprocess.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `tests/test_smoke.py:15` | `test_smoke_*` — real sandbox, mocks only LLM |
| Fixtures | `tests/conftest.py:253-258` | `temp_output_dir` — `TemporaryDirectory` context manager |
| Error handling | `src/agent/nodes/analysis.py:286-288` | `except Exception as e: logger.error(...)` |
| LLM mock | `tests/test_smoke.py:40-41` | `MagicMock() → MagicMock(content=script)` |
| Sandbox result | `tests/test_analysis.py:197` | `SandboxResult(stdout=..., stderr="", exit_code=0, timed_out=False)` |
| Unit construction | `tests/test_dag.py:20-36` | `_u()` helper — `PlanUnit(unit_id=, depends_on=, input_columns=, output_columns=)` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `tests/test_analysis.py` | UPDATE | Add tests for `_build_upstream_context`, prompt upstream sections, static guard rejection path |
| `tests/test_dag.py` | UPDATE | Add tests for corrupted CSV merge handler, executor exception handler |
| `tests/test_smoke.py` | UPDATE | Add `test_smoke_dag_chain_real_sandbox` — real subprocess DAG E2E |

## Tasks

### Task 1: Fill prompt-layer coverage gaps in test_analysis.py

- **Action**: Add 3 tests:
  1. `test_build_upstream_context_with_columns` — unit with `input_columns`, `output_columns`, and `depends_on` → verify all three parts in the returned string
  2. `test_build_upstream_context_empty` — unit with no columns/deps → returns None
  3. `test_build_unit_code_prompt_with_upstream` — unit with `depends_on` and `input_columns` → verify `UPSTREAM DATA` section and rules 14+15 in prompt
  4. `test_build_unit_react_fix_prompt_with_upstream` — same for the ReAct prompt
- **Mirror**: `tests/test_analysis.py:29-44` — `test_build_unit_code_prompt_structure`
- **Validate**: `pytest -v -k "test_build_upstream_context or test_build_unit_code_prompt_with_upstream or test_build_unit_react_fix_prompt_with_upstream"`

### Task 2: Fill DAG error-path coverage gaps in test_dag.py

- **Action**: Add 2 tests:
  1. `test_merge_upstream_corrupted_csv` — create a CSV file with garbage content → `merge_upstream_outputs` catches `pd.read_csv` exception, returns None (falls back to original data)
  2. `test_execute_dag_executor_exception` — mock `execute_unit_fn` that raises `RuntimeError` → DAG executor catches it, records failed result with error, continues other units
- **Mirror**: `tests/test_dag.py:230-235` — `test_merge_upstream_missing_files`; `tests/test_dag.py:296-325` — `test_execute_dag_failure_isolation`
- **Validate**: `pytest -v -k "test_merge_upstream_corrupted_csv or test_execute_dag_executor_exception"`

### Task 3: Add real-sandbox DAG E2E smoke test

- **Action**: Add `test_smoke_dag_chain_real_sandbox` to `tests/test_smoke.py`:
  1. Create a temp CSV with columns: `name`, `sales`, `region` (5 rows)
  2. Build a 3-unit chain Plan:
     - Unit 1: `depends_on=[]`, `output_columns=["sales_log"]` — mock LLM returns a script that computes `sales_log = log(sales)` and saves output.csv
     - Unit 2: `depends_on=[1]`, `input_columns=["sales_log"]`, `output_columns=["category"]` — mock LLM returns script that reads merged_input.csv (contains sales_log), computes category, saves output.csv
     - Unit 3: `depends_on=[2]`, `input_columns=["category"]` — mock LLM returns script that reads merged_input.csv, does a count, saves output.csv
  3. Mock only LLM (3 different script responses for the 3 units); `run_script` is NOT mocked — real sandbox execution
  4. Verify: all 3 units succeed, status=complete, unit 3 has access to unit 1's sales_log and unit 2's category
- **Mirror**: `tests/test_smoke.py:14-62` — `test_smoke_analysis_real_sandbox` (mocks LLM only, real subprocess)
- **Validate**: `pytest -v -k "test_smoke_dag_chain"`

### Task 4: Verify PRD success metrics

- **Action**: Run the 4 PRD success metrics and document results:
  1. **DAG Plan E2E success rate**: Run `test_smoke_dag_chain_real_sandbox` 3 times → all 3/3 units must succeed each run
  2. **Intermediate column passing**: Verify unit 2's `merged_input.csv` contains `sales_log` from unit 1; unit 3's contains `category` from unit 2 → no Missing column errors
  3. **Independent unit isolation**: Already tested in `test_execute_dag_failure_isolation` (unit 3 succeeds while unit 1 fails)
  4. **`import os` false positive: 0**: Already verified — `test_os_import_now_allowed` in test_static_guard.py passes
- **Mirror**: PRD success metrics table at `.claude/prds/dag-executor.prd.md:34-39`
- **Validate**: Pytest output + manual verification log

## Validation

```bash
pytest -v && ruff check . && mypy src/
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Real sandbox test flaky on Windows (GBK encoding) | Low | test_smoke_analysis_real_sandbox already handles this; use same pattern — English column names, simple math ops |
| DAG chain mock scripts produce wrong output columns | Medium | Keep scripts minimal — Unit 1 computes one column, Unit 2 reads it and computes another. Verify output.csv exists after each unit |
| Coverage gaps in analysis.py error paths hard to trigger | Low | Static guard rejection path can be triggered by mocking `check_static` return value; the retry-state restoration path needs a pre-populated `analysis_result` |

## Acceptance

- [x] All new tests pass (+7 tests: 4 analysis + 2 dag + 1 smoke)
- [x] Full suite passes (188 tests)
- [x] ruff + mypy clean
- [x] `test_smoke_dag_chain_real_sandbox` passes — real subprocess DAG execution
- [x] Coverage: dag.py 100%, analysis.py ~93%
- [x] All 4 PRD success metrics verified
