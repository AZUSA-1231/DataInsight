# Plan: Template System + MVP Templates

**Source PRD**: `../prds/cycle-4-dag-executor.prd.md`
**Selected Milestone**: 2 — Template system + MVP templates
**Complexity**: Medium

## Summary

Create `src/agent/templates.py` with 4 MVP template functions (one per unit type + an extra transform), a `TEMPLATE_REGISTRY` lookup table, and a `dispatch()` function that routes by `execution_mode`. Template-mode units run in-process — `_execute_unit` gains a dispatch branch that short-circuits the LLM→sandbox→ReAct path when `execution_mode == "template"`.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/agent/dag.py:22-27` | `snake_case` functions, `logger = logging.getLogger(__name__)` at module level |
| Enums | `src/agent/state.py:23-31` | `(str, Enum)` base class — `UnitType`, `ExecutionMode` already exist |
| Return contract | `src/agent/nodes/analysis.py:316-328` | `{"unit_id", "status", "parsed_output", "charts", "insights", "statistics", "error", "retry_count", "scripts", "stdout", "output_dir"}` dict |
| Error handling | `src/agent/dag.py:25-33` | Return `{"status": "failed", "error": str}` dicts, never raise from templates |
| Logging | `src/agent/dag.py:210-212` | `logger.info()` on entry/exit, `logger.error()` on failure |
| Immutability | `src/agent/state.py` | Functions receive `pd.DataFrame`, return new column dicts; no in-place mutation |
| Tests | `tests/test_dag.py:22-47` | `@pytest.mark.unit`, factory helper, `tmp_path` fixture |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/templates.py` | CREATE | 4 template functions + registry + dispatch |
| `src/agent/nodes/analysis.py` | UPDATE | Add template dispatch branch in `_execute_unit` before LLM path |
| `tests/test_templates.py` | CREATE | Unit tests for each template + dispatch routing |
| `tests/test_dag.py` | UPDATE | Add test for template-mode unit through `execute_dag` |
| `tests/conftest.py` | UPDATE | Add `sample_csv_with_dates` fixture |

## Tasks

### Task 1: Create `src/agent/templates.py`
- **Action**: New module with:
  - `TemplateFunc` type alias: `Callable[[pd.DataFrame, list[str], dict], dict]`
  - `TEMPLATE_REGISTRY: dict[str, TemplateFunc]`
  - `transform_column_arithmetic(df, input_columns, params)` — `params: {"operator": "+|-|*|/", "new_column": str}`, returns `{"columns": {name: Series}, "artifacts": []}`
  - `transform_linear_regression(df, input_columns, params)` — sklearn `LinearRegression`, `input_columns` = [X, y], returns `{"columns": {pred_name: Series}, "artifacts": []}`
  - `filter_by_date(df, input_columns, params)` — `params: {"start": str, "end": str, "date_column": str}`, returns `{"filtered_df": DataFrame, "snapshot_name": str, "artifacts": []}`
  - `terminal_scatter_plot(df, input_columns, params)` — saves PNG to `output_dir`, returns `{"columns": {}, "artifacts": [path]}`
  - `dispatch(unit: PlanUnit, df: pd.DataFrame, output_dir: str) -> dict | None`:
    - `execution_mode == "llm"` → return `None` (caller falls through to LLM path)
    - `execution_mode == "template"` → lookup `unit.template_name`, call template, build result dict
    - Unknown template_name → return error dict
  - `_build_template_result(unit, template_output, output_dir)` → full 12-key result dict
- **Mirror**: `src/agent/nodes/analysis.py:296-328` (result dict), `src/agent/dag.py:22-27` (logging)
- **Validate**: `python -c "from src.agent.templates import TEMPLATE_REGISTRY; print(len(TEMPLATE_REGISTRY))"` → `4`

### Task 2: Wire template dispatch into `_execute_unit`
- **Action**: At top of `_execute_unit` (before LLM prompt), load df from `data_path`, call `dispatch(unit, df, unit_output_dir)`. If non-None, write output.csv from template result (for checkpoint chaining), return immediately. Otherwise continue to existing LLM path unchanged.
- **Mirror**: `src/agent/nodes/analysis.py:213-361` (existing `_execute_unit`)
- **Validate**: `pytest -v -m unit tests/test_analysis.py` — existing tests unchanged (LLM-mode units skip dispatch)

### Task 3: Update `_serialize_unit` for template metadata
- **Action**: Add `unit_type`, `execution_mode`, `template_name` fields to the JSON dict in `_serialize_unit`.
- **Mirror**: `src/agent/nodes/analysis.py:30-44`
- **Validate**: `pytest -v -m unit tests/test_analysis.py`

### Task 4: Create `tests/test_templates.py`
- **Action**: ~10 tests:
  - `test_arithmetic_add`, `test_arithmetic_subtract`, `test_arithmetic_multiply`, `test_arithmetic_divide_by_zero`
  - `test_linear_regression_basic`, `test_linear_regression_row_count_invariant`
  - `test_filter_by_date_basic`, `test_filter_by_date_no_match`
  - `test_scatter_plot_creates_file`
  - `test_dispatch_template_mode`, `test_dispatch_llm_mode_returns_none`
  - `test_dispatch_unknown_template`, `test_dispatch_missing_template_name`
  - `test_build_template_result_shape` — all 12 keys present
- **Mirror**: `tests/test_dag.py:22-47` (factory helper), `tests/test_dag.py:247-258` (round-trip test)
- **Validate**: `pytest -v -m unit tests/test_templates.py`

### Task 5: Update conftest.py
- **Action**: Add `sample_csv_with_dates` fixture — temp CSV with `date, region, revenue, cost, volume` columns, ~10 rows of realistic data spanning multiple dates.
- **Mirror**: `tests/conftest.py:12-27` (`sample_csv_path`)
- **Validate**: `pd.read_csv(path)` loads without error

### Task 6: Add template-mode DAG integration test
- **Action**: `test_execute_dag_template_chain` in `tests/test_dag.py` — 2 units (transform template → terminal template), mock executor calls real `dispatch()`, verifies checkpoint is produced.
- **Mirror**: `tests/test_dag.py:553-595` (checkpoint integration tests)
- **Validate**: `pytest -v -m unit tests/test_dag.py`

## Validation

```bash
pytest -v -m unit tests/test_templates.py     # Task 1, 4
pytest -v -m unit tests/test_analysis.py      # Task 2, 3
pytest -v -m unit tests/test_dag.py           # Task 6
pytest -v                                      # Full suite
ruff check .
mypy src/ --ignore-missing-imports
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Linear regression sklearn import fails at module level | Low | Lazy import inside `transform_linear_regression`; return error dict on ImportError |
| Template return shape mismatch with `_execute_unit` expected keys | Medium | `_build_template_result()` is the single mapping point; test for exact 12-key shape |
| `filter_by_date` column dtype confusion (string vs datetime) | Low | `pd.to_datetime()` with `errors="coerce"` in template; warn on parse failures |
| Templates produce output.csv that doesn't match `output_columns` | Low | Template writes output.csv with original columns + new columns; DAG checkpoint logic handles rest |

## Acceptance

- [ ] `src/agent/templates.py` exists with 4 templates + registry + dispatch
- [ ] `_execute_unit` dispatches template-mode units in-process, skips LLM/sandbox
- [ ] Each template tested independently
- [ ] `dispatch()` returns None for LLM-mode units (existing path unchanged)
- [ ] All existing tests still pass
- [ ] `ruff check .` clean
- [ ] `mypy src/` no new errors
