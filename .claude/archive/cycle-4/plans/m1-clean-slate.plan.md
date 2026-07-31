# Plan: M1 — Clean Slate

**Source PRD**: .claude/prds/dag-executor.prd.md
**Selected Milestone**: M1 — Clean Slate
**Complexity**: Small

## Summary

Remove the preprocessing/cleaning stage entirely from the pipeline. Unblock `import os` in static guard. Clean up state models (Plan, AgentState), graph, executor route, planner prompts, and report prompts. After this, data flows directly from planner → analysis with no intermediate transformation.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Node error return | `business_track.py:38` | `return {"error": "...", ...}` — never raise |
| Logging | `analysis.py:16` | `logger = logging.getLogger(__name__)` |
| Graph edges | `graph.py:81-83` | `graph.add_edge("planner", "analysis")` |
| Tests | `tests/test_analysis.py` | `@pytest.mark.unit`, mock LLM, verify result dict |
| State model | `state.py:133-155` | Pydantic `BaseModel` with defaults |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/sandbox/static_guard.py` | UPDATE | Remove `"os"` from `_BANNED_IMPORTS` |
| `src/agent/state.py` | UPDATE | Remove `cleaning` from Plan; remove `preprocessing_result`, `cleaning_insights` from AgentState |
| `src/agent/nodes/preprocessing.py` | DELETE | Cleaning stage removed |
| `src/agent/nodes/__init__.py` | UPDATE | Remove preprocessing_node export |
| `src/agent/graph.py` | UPDATE | Remove preprocessing node + `_should_retry_preprocessing`; planner → analysis direct edge |
| `src/agent/nodes/planner.py` | UPDATE | `_parse_plan_from_json` — remove `cleaning` key expectation |
| `src/agent/prompts/planner_system.txt` | UPDATE | Remove cleaning unit from output schema; renumber rules |
| `src/agent/nodes/analysis.py` | UPDATE | `data_path` reads from `state.file_path` directly; remove `preprocessing_result` refs |
| `src/agent/nodes/report_gen.py` | UPDATE | Remove "数据画像与清洗" section from both report prompts |
| `src/agent/nodes/business_track.py` | UPDATE | Remove cleaning-related references (if any) |
| `src/__main__.py` | UPDATE | Remove `plan.cleaning` reference in CLI progress |
| `src/api/routes/execution.py` | UPDATE | `_run_execution` calls analysis_node directly; remove preprocessing loop |
| `src/api/schemas.py` | UPDATE | `ExecutionResultResponse` — remove `preprocessing` field |
| `tests/test_preprocessing.py` | DELETE | No more preprocessing |
| `tests/conftest.py` | UPDATE | Remove `cleaning` from all `sample_plan*` fixtures; Plan model now has no cleaning |
| `tests/test_planner.py` | UPDATE | Remove `plan.cleaning.unit_id` / `plan.cleaning.related_fields` assertions |
| `tests/test_graph.py` | UPDATE | Remove preprocessing edge tests; update state assertions |
| `tests/test_analysis.py` | UPDATE | Remove `preprocessing_result` from test states; use `file_path` directly |
| `tests/test_report_gen.py` | UPDATE | Remove cleaning section assertions |
| `tests/test_smoke.py` | UPDATE | Remove preprocessing_result assertions |
| `tests/api/test_execution.py` | UPDATE | Remove preprocessing state/assertions |

## Tasks

### Task 1: Unblock `import os`
- **Action**: In `static_guard.py:72`, remove `"os"` from `_BANNED_IMPORTS` set. Regex layer (`os.system(`, `os.popen(`, etc.) already catches dangerous calls precisely.
- **Validate**: `pytest -v -k static_guard`

### Task 2: Purge state models
- **Action**:
  - `Plan`: remove `cleaning: PlanUnit` → only `units: list[PlanUnit]` + `alignment_notes: str`
  - `AgentState`: remove `cleaning_insights: str | None = None` and `preprocessing_result: dict[str, Any] | None = None`
- **Validate**: `mypy src/` (will fail on remaining refs — those are fixed in later tasks)

### Task 3: Delete preprocessing + update graph
- **Action**:
  - Delete `src/agent/nodes/preprocessing.py`
  - Remove from `__init__.py`: delete `preprocessing_node` import + export
  - In `graph.py`: remove `preprocessing_node` import, remove `_should_retry_preprocessing`, remove `add_node("preprocessing", ...)`, remove `add_edge("planner", "preprocessing")`, add `add_edge("planner", "analysis")`, remove `add_conditional_edges("preprocessing", ...)`
- **Validate**: `pytest -v -k "graph"` then `pytest -v`

### Task 4: Fix planner (prompt + parser)
- **Action**:
  - `planner_system.txt`: remove `cleaning` object from output schema JSON. Plan now is `{units: [...], alignment_notes: "..."}`. Remove cleaning-related rules (rule 5 "must explain WHY cleaning", rule 9 "cleaning unit_id is 0"). Renumber remaining rules.
  - `planner.py`: in `_parse_plan_from_json`, remove the `cleaning` key parsing. `Plan(**parsed)` should now receive only `units` + `alignment_notes`.
- **Validate**: `pytest -v -k planner`

### Task 5: Fix analysis_node data source
- **Action**: In `analysis_node`, line 333: change `data_path = parsed.get("cleaned_data_path") or state.file_path` to `data_path = state.file_path`. Remove `pre_result = state.preprocessing_result or {}` block.
- **Validate**: `pytest -v -k analysis`

### Task 6: Fix report_gen prompts
- **Action**: Remove "## 1. 数据画像与清洗" section from both `_build_full_report_prompt` and `_build_partial_report_prompt`. Renumber sections (2→1, 3→2, 4→3, 5→4, 6→5). Remove cleaning action descriptions from prompt text.
- **Validate**: `pytest -v -k report_gen`

### Task 7: Fix execution route
- **Action**: In `execution.py`: remove `preprocessing_node` import. Simplify `_run_execution` — remove the for loop with retry, just call `analysis_node` directly. Remove `preprocessing_result` status checks in `get_status`. Update `_run_execution` docstring.
- **Validate**: `pytest -v -k execution`

### Task 8: Fix CLI main + schemas
- **Action**:
  - `__main__.py`: remove `plan.cleaning` reference (line 353)
  - `schemas.py`: in `ExecutionResultResponse`, remove `preprocessing` field
- **Validate**: `mypy src/` + `ruff check .`

### Task 9: Update all tests
- **Action**:
  - Delete `tests/test_preprocessing.py`
  - `conftest.py`: remove `cleaning=` from `sample_plan`, `sample_plan_multi`, `make_plan` fixtures. Plan now only takes `units` + `alignment_notes`.
  - `test_planner.py`: remove assertions on `plan.cleaning.unit_id`, `plan.cleaning.related_fields`
  - `test_graph.py`: remove preprocessing-related tests/assertions
  - `test_analysis.py`: remove `preprocessing_result` from test states; `_execute_unit` gets original file path
  - `test_report_gen.py`: remove cleaning section assertions
  - `test_smoke.py`: remove `preprocessing_result` assertions
  - `tests/api/test_execution.py`: remove preprocessing state references
- **Validate**: `pytest -v` — all remaining tests pass

## Validation

```bash
pytest -v && ruff check . && mypy src/
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Test churn — many tests reference cleaning/preprocessing | High | Systematic grep before starting; fix all refs in Task 9 |
| report_gen hardcodes section numbers | Low | Review prompt strings carefully |
| Frontend/API schemas expect `preprocessing` field | Medium | Already identified `ExecutionResultResponse.preprocessing` — remove from schema |
