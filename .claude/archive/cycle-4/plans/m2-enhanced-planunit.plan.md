# Plan: Enhanced PlanUnit

**Source PRD**: .claude/prds/dag-executor.prd.md
**Selected Milestone**: M2 — Enhanced PlanUnit
**Complexity**: Small

## Summary
Add `input_columns` and `output_columns` fields to `PlanUnit`, update the Planner
system prompt so the LLM populates them, and thread them through the analysis
code-gen prompt. These fields are the contract that M3's DAG executor will use
for column-existence validation and inter-unit data passing. No executor logic
changes — pure model + prompt work.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Naming | `state.py:112-117` | `list[str] = []` default, snake_case matching `related_fields` |
| Pydantic defaults | `state.py:116-117` | `= []` for backward compat with all existing PlanUnit constructions |
| Prompt schema | `planner_system.txt:60-80` | JSON schema in comments, field descriptions in Chinese |
| JSON parse | `planner.py:142-158` | `.get("field", [])` in dict comprehension |
| Prompt injection | `analysis.py:31-43` | `_serialize_unit` adds fields to code-gen prompt context |
| Tests | `test_planner.py:42-74` | Mock LLM returns JSON string, assert on parsed Plan fields |

## Files to Change
| File | Action | Why |
|---|---|---|
| `src/agent/state.py` | UPDATE | Add `input_columns`/`output_columns` to PlanUnit |
| `src/agent/prompts/planner_system.txt` | UPDATE | Schema + rules for new fields |
| `src/agent/nodes/planner.py` | UPDATE | Parse new fields in `_parse_plan_from_json` |
| `src/agent/nodes/analysis.py` | UPDATE | Include new fields in `_serialize_unit` |
| `src/api/routes/workspace.py` | UPDATE | `_reindex_units` preserves new fields |
| `tests/conftest.py` | UPDATE | Add new fields to Plan fixtures |
| `tests/test_planner.py` | UPDATE | Update JSON strings, add field assertions |
| `tests/test_analysis.py` | UPDATE | Verify `_serialize_unit` includes new fields |
| `tests/api/test_workspace.py` | UPDATE | Remove residual `cleaning=` references from M1 |
| `tests/test_graph.py` | UPDATE | May need PlanUnit fixture updates |
| `tests/test_business_track.py` | UPDATE | May need PlanUnit fixture updates |

## Tasks

### Task 1: Add `input_columns`/`output_columns` to PlanUnit model
- **Action**: Add `input_columns: list[str] = []` and `output_columns: list[str] = []` to `PlanUnit` in `src/agent/state.py`
- **Mirror**: Same pattern as existing `depends_on: list[int] = []` and `related_fields: list[str] = []`
- **Validate**: `python -c "from src.agent.state import PlanUnit; p=PlanUnit(unit_id=1, purpose='test', cautious=''); assert p.input_columns == []; assert p.output_columns == []"`

### Task 2: Update Planner system prompt
- **Action**: Add `input_columns` and `output_columns` to the JSON output schema in `planner_system.txt`. Add rules:
  - `input_columns`: list columns from raw data that this unit reads, AND columns produced by upstream units (those listed in `depends_on`). If `depends_on` is empty, list only raw data columns.
  - `output_columns`: name the new columns this analysis will add (e.g. KMeans → `["Cluster"]`, LinearRegression → `["prediction"]`). If analysis produces only statistics/charts (no new columns), use `[]`.
  - Rule: when a unit has non-empty `depends_on`, its `input_columns` MUST include the `output_columns` of every upstream unit.
- **Mirror**: Chinese descriptions matching existing field doc style in prompt
- **Validate**: Visual review of prompt — schema is valid, rules are clear

### Task 3: Update `_parse_plan_from_json` in planner.py
- **Action**: Add `input_columns=u.get("input_columns", [])` and `output_columns=u.get("output_columns", [])` to the PlanUnit constructor call in `_parse_plan_from_json`
- **Mirror**: Same `.get()` pattern as `depends_on` and `related_fields`
- **Validate**: `pytest -v -k "test_planner_agent"` (after test JSON fixtures updated)

### Task 4: Update `_serialize_unit` in analysis.py
- **Action**: Add `input_columns` and `output_columns` to the JSON dict in `_serialize_unit`, and add guidance to `_build_unit_code_prompt` about what these fields mean
- **Mirror**: Same `indent=2, ensure_ascii=False` serialization style
- **Validate**: `pytest -v -k "test_serialize_unit or test_build_unit_code_prompt"`

### Task 5: Update `_reindex_units` in workspace.py
- **Action**: Add `input_columns=u.input_columns` and `output_columns=u.output_columns` to the PlanUnit constructor in `_reindex_units`
- **Mirror**: Same pattern as existing `depends_on=u.depends_on`
- **Validate**: `pytest -v -k "test_delete_unit"` (reindex is called after delete)

### Task 6: Update test fixtures
- **Action**: Update all PlanUnit constructions and JSON strings across test files to include the new fields. Add a dedicated test in `test_planner.py` that verifies `input_columns`/`output_columns` are parsed correctly from LLM JSON (especially when `depends_on` is non-empty).
- **Mirror**: Existing fixture conventions (`conftest.py` PlanUnit constructor calls)
- **Validate**: `pytest -v` — all tests pass

### Task 7: Clean residual `cleaning=` references in test_workspace.py
- **Action**: Remove `cleaning=PlanUnit(...)` from `test_generate_plan` and `test_generate_plan_no_workspace` — these were silently ignored by Pydantic (v2 default `extra="ignore"`), but are dead code after M1
- **Mirror**: Other tests in the same file that already construct Plan without `cleaning=`
- **Validate**: `pytest -v -k "test_generate_plan"`

### Task 8: Full validation
- **Action**: Run full test suite, linter, and type checker
- **Mirror**: M1 validation workflow
- **Validate**: `pytest -v && ruff check . && mypy src/`

## Validation
```bash
pytest -v && ruff check . && mypy src/
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM fails to populate input_columns correctly | Medium | Fields default to `[]` — M3 executor falls back to checking `related_fields` union when `input_columns` is empty |
| Planner over-infers output_columns (e.g. always fills something) | Low | Prompt explicitly says `[]` when analysis only produces stats/charts |
| Existing tests break on new fields | None | Default `[]` ensures full backward compat — existing constructions work without change |

## Acceptance
- [ ] All tasks complete
- [ ] Validation passes (pytest + ruff + mypy)
- [ ] `input_columns` and `output_columns` appear in PlanUnit model
- [ ] Planner prompt includes new fields with usage guidance
- [ ] Residual `cleaning=` references removed from test_workspace.py
