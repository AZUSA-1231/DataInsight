# Plan: DAG-Native Executor — Milestone 1

**Source PRD**: `../prds/cycle-4-dag-executor.prd.md`
**Selected Milestone**: 1 — PlanUnit model refactor + DAG engine overhaul
**Complexity**: Large

## Summary

Refactor the PlanUnit Pydantic model to introduce three unit types (Transform/Filter/Terminal) and two execution modes (template/llm), then overhaul `dag.py` to replace CSV concatenation (`merge_upstream_outputs`) with Parquet-based checkpoint management. `topological_levels` and `validate_columns` are preserved as-is. All existing 201 tests must continue to pass — new fields are added as optional with safe defaults.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/agent/state.py:109-119` | Pydantic BaseModel, `snake_case` fields, `str \| None` for optional, `list[str] = []` defaults |
| Enums | `src/agent/tools.py:1-3` | `str, Enum` base class for string enumerations |
| Error handling | `src/agent/dag.py:25-33` | Custom exception (`DagCycleError`), nodes return `{"error": str}` dicts, never raise |
| Logging | `src/agent/dag.py:20` | `logger = logging.getLogger(__name__)` at module level, `logger.info()` for key events, `logger.error()` for failures |
| Immutability | `src/api/session.py:27-30` | `model_copy(update=patch)` for state updates, never mutate in place |
| Tests | `tests/test_dag.py:20-36` | `@pytest.mark.unit`, factory helper `_u()`, `tmp_path` fixture, `PlanUnit(...)` constructor calls |
| Test fixtures | `tests/conftest.py:166-181` | `PlanUnit(...)` in `sample_plan` and `sample_plan_multi` fixtures |
| API schemas | `src/api/schemas.py:50-55` | `UnitCreateRequest` / `UnitUpdateRequest` — request bodies that construct PlanUnits |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/state.py` | UPDATE | Add `UnitType`/`ExecutionMode` enums; refactor `PlanUnit` with new fields + safe defaults |
| `src/agent/dag.py` | UPDATE | Remove `merge_upstream_outputs`; add Parquet checkpoint helpers; refactor `execute_dag` |
| `src/agent/nodes/analysis.py` | UPDATE | Adapt `_execute_unit` and prompt builders to new PlanUnit fields |
| `src/agent/nodes/planner.py` | UPDATE | Adapt `_parse_plan_from_json` to pass new fields from LLM output |
| `src/api/routes/workspace.py` | UPDATE | Adapt `PlanUnit` constructors, `_reindex_units`, `add_unit`, `update_unit` |
| `src/api/schemas.py` | UPDATE | Add `unit_type`, `execution_mode`, `depends_on` to `UnitCreateRequest`/`UnitUpdateRequest` |
| `tests/test_dag.py` | UPDATE | Replace `merge_upstream_outputs` tests with checkpoint tests; update `_u()` helper |
| `tests/test_analysis.py` | UPDATE | Update PlanUnit construction in analysis tests |
| `tests/test_planner.py` | UPDATE | Update PlanUnit parsing assertions |
| `tests/test_business_track.py` | UPDATE | Update any PlanUnit references |
| `tests/conftest.py` | UPDATE | Update `sample_plan`, `sample_plan_multi`, `make_plan` fixtures |

## Tasks

### Task 1: Refactor PlanUnit model in `state.py`
- **Action**: Add `UnitType` (transform/filter/terminal) and `ExecutionMode` (template/llm) enums. Add new fields to PlanUnit: `unit_type` (default `"transform"`), `execution_mode` (default `"llm"`), `input_from` (default `None`), `template_name` (default `None`), `template_params` (default `None`). Rename `model` to `model_hint`. Keep `purpose`, `cautious`, `depends_on`, `input_columns`, `output_columns`, `related_fields`. All new fields have defaults so existing call sites don't break.
- **Mirror**: `src/agent/state.py:109-119` (PlanUnit existing pattern), `src/agent/tools.py:1-3` (enum pattern)
- **Validate**: `python -c "from src.agent.state import PlanUnit; u = PlanUnit(unit_id=1, purpose='test', cautious=''); print(u.unit_type, u.execution_mode)"` outputs `transform llm`

### Task 2: Overhaul `dag.py` — remove merge, add Parquet checkpoints
- **Action**: Remove `merge_upstream_outputs` function entirely. Add `save_parquet(df, path)` and `load_parquet(path)` helpers. Add `resolve_input_path(unit, session_dir, checkpoints)` that returns the correct Parquet path for a unit's input. Refactor `execute_dag` to: (a) track checkpoint levels per branch (main table + per-snapshot), (b) save TransformUnit output as `wide_l{N}.parquet` or `snapshot_{name}_l{N}.parquet`, (c) save FilterUnit output as `snapshots/{name}_l0.parquet`, (d) skip checkpoint for TerminalUnit. Keep `topological_levels` and `validate_columns` unchanged.
- **Mirror**: `src/agent/dag.py:162-362` (existing execute_dag structure), `src/sandbox/executor.py:18-59` (subprocess patterns)
- **Validate**: `pytest -v -m unit tests/test_dag.py` — all 22 dag tests pass (after updating in Task 6)

### Task 3: Update analysis node for new PlanUnit fields
- **Action**: Update `_serialize_unit` to include `unit_type` and `execution_mode`. Update `_build_unit_code_prompt` to include unit type context. Update `_execute_unit` to handle `input_from` for upstream data resolution. The `analysis_node` entry point signature stays the same.
- **Mirror**: `src/agent/nodes/analysis.py:30-44` (_serialize_unit), `src/agent/nodes/analysis.py:47-112` (_build_unit_code_prompt)
- **Validate**: `pytest -v -m unit tests/test_analysis.py` — all analysis tests pass

### Task 4: Update planner node for new PlanUnit fields
- **Action**: Update `_parse_plan_from_json` to extract `unit_type`, `execution_mode`, `input_from`, `template_name`, `template_params` from LLM JSON output. LLM may omit these — default to `"transform"` / `"llm"` / `None`. The planner system prompt (`planner_system.txt`) does NOT need updating yet (M3 does that).
- **Mirror**: `src/agent/nodes/planner.py:129-147` (_parse_plan_from_json)
- **Validate**: `pytest -v -m unit tests/test_planner.py` — all planner tests pass

### Task 5: Update API routes and schemas
- **Action**: Add `unit_type`, `execution_mode`, `depends_on`, `input_from` to `UnitCreateRequest` and `UnitUpdateRequest`. Update `_reindex_units` in workspace.py to carry forward new fields. Update `add_unit` to accept new fields from request body. Update `update_unit` to allow patching new fields.
- **Mirror**: `src/api/schemas.py:50-62` (UnitCreateRequest/UnitUpdateRequest), `src/api/routes/workspace.py:26-42` (_reindex_units)
- **Validate**: `pytest -v -m unit tests/api/test_workspace.py` — all workspace API tests pass

### Task 6: Update tests for new model + engine
- **Action**: Update `_u()` factory in `test_dag.py` to accept and pass new fields. Replace `merge_upstream_outputs` tests with Parquet checkpoint tests (test `resolve_input_path`, test checkpoint save/load round-trip, test FilterUnit snapshot creation). Update `conftest.py` fixtures (`sample_plan`, `sample_plan_multi`, `make_plan`) to include new PlanUnit fields. Update any other test files that construct PlanUnit directly.
- **Mirror**: `tests/test_dag.py:20-36` (_u helper), `tests/conftest.py:166-215` (plan fixtures)
- **Validate**: `pytest -v` — all 201+ tests pass

## Validation

```bash
# After each task: run targeted tests
pytest -v -m unit tests/test_dag.py          # Task 2, 6
pytest -v -m unit tests/test_analysis.py     # Task 3
pytest -v -m unit tests/test_planner.py      # Task 4
pytest -v tests/api/test_workspace.py        # Task 5

# Final: full suite
pytest -v                                    # All 201+ tests pass
ruff check .                                 # No lint errors
mypy src/ --ignore-missing-imports           # No new type errors
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| PlanUnit field rename (`model` → `model_hint`) breaks many call sites | High | Grep for all `.model` accesses on PlanUnit objects first; add `model` as a deprecated `@property` that reads `model_hint` for backward compat, or just update all references |
| `model` → `model_hint` rename breaks LLM JSON parsing in planner | Medium | Keep `model` field name in LLM prompt for now (M3 updates prompts); normalize at parse time: `model` in JSON → `model_hint` in PlanUnit |
| `merge_upstream_outputs` removal breaks tests that import it | High | Remove import + tests together in Task 2/6; check no other module imports it |
| `execute_dag` signature change breaks `analysis_node` | Medium | Keep the same 4-param signature; internal behavior changes are transparent to callers |
| New PlanUnit fields with defaults break Pydantic validation of existing test data | Low | All new fields have `None` or `[]` defaults; Pydantic ignores extras by default |

## Acceptance

- [ ] All 201+ existing tests pass (`pytest -v`)
- [ ] `merge_upstream_outputs` removed from codebase (no references remain)
- [ ] `execute_dag` uses Parquet checkpoints, not CSV concatenation
- [ ] PlanUnit has `unit_type`, `execution_mode`, `input_from`, `template_name`, `template_params`, `model_hint` fields
- [ ] Existing code creating `PlanUnit(unit_id=1, purpose="x", cautious="")` still works (new fields have defaults)
- [ ] `ruff check .` clean
- [ ] `mypy src/` no new errors
