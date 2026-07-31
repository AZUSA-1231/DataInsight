# Plan: Single-Unit Rerun API

**Source PRD**: `../prds/cycle-4-dag-executor.prd.md`
**Selected Milestone**: 4 — Single-unit rerun API
**Complexity**: Medium

## Summary

Add `POST /api/sessions/{session_id}/execution/units/{unit_id}/rerun` to the execution router. The endpoint resolves the unit's input checkpoint, re-executes only that unit (or cascades through dependents), and marks unaffected downstream units as stale. A helper in `dag.py` computes transitive dependents and resolves the correct input checkpoint for rerun.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/api/routes/execution.py:43-64` | FastAPI `@router.post("/run")`, `_get_store`, `HTTPException` |
| Error handling | `src/api/routes/workspace.py:111-116` | 404 if unit not found, 400 if no plan |
| Async execution | `src/api/routes/execution.py:26-40` | `asyncio.create_task(_run_execution(...))` for background work |
| State immutability | `src/api/session.py:27-30` | `store.update(session_id, patch)` — never mutate in place |
| DAG helpers | `src/agent/dag.py:37-88` | Pure functions, `list[PlanUnit]` input, `logger.info/error` |
| API schemas | `src/api/schemas.py:91-102` | Pydantic `BaseModel` response types |
| Tests | `tests/api/test_execution.py:8-21` | `@pytest.mark.unit`, class-based, `api_client` + `test_session` fixtures |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/dag.py` | UPDATE | Add `transitive_dependents()` and `resolve_rerun_input()` helpers |
| `src/api/routes/execution.py` | UPDATE | Add `POST /units/{unit_id}/rerun` endpoint |
| `src/api/schemas.py` | UPDATE | Add `RerunUnitResponse` schema |
| `tests/api/test_execution.py` | UPDATE | Add rerun endpoint tests |

## Tasks

### Task 1: Add DAG helpers for rerun
- **Action**: Add two pure functions to `dag.py`:
  - `transitive_dependents(unit_id: int, units: list[PlanUnit]) -> list[int]` — returns sorted list of all unit IDs that transitively depend on `unit_id` (follow `depends_on` edges forward). Used for stale marking and cascade selection.
  - `resolve_rerun_input(unit: PlanUnit, parent_output_dir: str) -> str | None` — determines the best checkpoint path to use as input for re-running a single unit. Reads the existing checkpoint directory to find the latest Parquet for the unit's branch (`input_from` snapshot or main wide table). Returns `None` if no checkpoint exists (meaning: use original data file).
- **Mirror**: `src/agent/dag.py:37-88` (pure functions, clear signatures, `logger`)
- **Validate**: `python -c "from src.agent.dag import transitive_dependents, resolve_rerun_input; print('OK')"`

### Task 2: Add `POST /execution/units/{unit_id}/rerun` endpoint
- **Action**: 
  - Add `RerunUnitResponse` to schemas (unit_id, status, stale_units as list[int])
  - Add endpoint that:
    1. Validates session and plan existence
    2. Finds the target unit by `unit_id`
    3. Resolves the input checkpoint via `resolve_rerun_input`
    4. Calls `_execute_unit(unit, input_path, output_dir)` directly (synchronous — no background task for single unit)
    5. Computes transitive dependents via `transitive_dependents`
    6. If `?cascade=true`: re-executes each dependent in topological order with updated input paths
    7. Marks non-rerun downstream units as stale in the updated `analysis_result`
    8. Returns the unit's new result + list of stale unit IDs
  - Query param: `cascade: bool = False`
- **Mirror**: `src/api/routes/execution.py:43-64` (existing `/run` endpoint structure)
- **Validate**: `pytest -v tests/api/test_execution.py`

### Task 3: Update schemas
- **Action**: Add `RerunUnitResponse(BaseModel)` with fields `unit_id: int`, `status: str`, `stale_units: list[int]`. Add a `stale: bool = False` field to `UnitResultResponse` so the frontend can display which units are out of date.
- **Mirror**: `src/api/schemas.py:91-102` (existing `UnitResultResponse` pattern)
- **Validate**: `python -c "from src.api.schemas import RerunUnitResponse; print(RerunUnitResponse(unit_id=1, status='success', stale_units=[]))"`

### Task 4: Add tests
- **Action**: Add to `tests/api/test_execution.py`:
  - `test_rerun_unit_success` — mock `_execute_unit`, verify 200 + stale_units populated
  - `test_rerun_unit_not_found` — unit 99 → 404
  - `test_rerun_unit_no_plan` — no plan → 400
  - `test_rerun_unit_cascade` — cascade=true reruns transitive dependents
  - `test_rerun_unit_session_not_found` — bad session → 404
- Add to `tests/test_dag.py`:
  - `test_transitive_dependents_direct` — unit 2 depends on 1 → dependents of 1 = [2]
  - `test_transitive_dependents_chain` — 1→2→3 → dependents of 1 = [2, 3]
  - `test_transitive_dependents_diamond` — diamond DAG dependency tracking
  - `test_transitive_dependents_none` — leaf unit has no dependents
  - `test_resolve_rerun_input_wide` — returns correct wide_l{N}.parquet path
  - `test_resolve_rerun_input_snapshot` — returns correct snapshot checkpoint path
  - `test_resolve_rerun_input_none` — no checkpoint → returns None
- **Mirror**: `tests/api/test_execution.py:10-21` (API test pattern), `tests/test_dag.py:52-87` (DAG test pattern)
- **Validate**: `pytest -v -m unit tests/test_dag.py tests/api/test_execution.py`

## Validation

```bash
pytest -v -m unit tests/test_dag.py                   # Dag helpers
pytest -v -m unit tests/api/test_execution.py          # API endpoint
pytest -v                                               # Full suite
ruff check .
mypy src/ --ignore-missing-imports
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| `resolve_rerun_input` can't find the right checkpoint after partial runs | Medium | Fall back to original data file; log warning; test with various checkpoint states |
| Cascade rerun changes checkpoint levels, confusing subsequent reruns | Medium | Each rerun rewrites its own checkpoint; downstream units always read the latest checkpoint via `resolve_rerun_input` which scans the directory |
| Rerun produces different row counts than original, breaking downstream | Low | Same unit type contract enforced (M3 prompts); Filter unit column-set-invariant guarantee |
| Existing `POST /run` endpoint state conflicts with partial rerun results | Low | Rerun updates `analysis_result` in-place via `store.update`; the `stale` flag prevents misleading results display |

## Acceptance

- [ ] `POST /execution/units/{unit_id}/rerun` returns 200 with correct stale_units
- [ ] `?cascade=true` re-executes transitive dependents in order
- [ ] Unit not found returns 404, no plan returns 400
- [ ] `transitive_dependents` correctly handles chains, diamonds, leaves
- [ ] `resolve_rerun_input` detects existing checkpoints
- [ ] All existing tests still pass
- [ ] `ruff check .` clean
- [ ] `mypy src/` no new errors
