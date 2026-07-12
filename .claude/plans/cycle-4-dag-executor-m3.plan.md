# Plan: LLM Prompt Refactor — Per-Unit-Type Return Contracts

**Source PRD**: `.claude/prds/cycle-4-dag-executor.prd.md`
**Selected Milestone**: 3 — LLM prompt refactor
**Complexity**: Small

## Summary

Refactor the two LLM code-generation prompt builders in `analysis.py` to produce unit-type-specific prompts. Transform, Filter, and Terminal units each get tailored instructions specifying their exact return contract — matching the shape already produced by M2 templates. The sandbox output parser (`_extract_json` → `json.loads`) is unchanged; only the prompt text changes.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/agent/nodes/analysis.py:53,120` | `_build_unit_code_prompt`, `_build_unit_react_fix_prompt` — keep names, add branching |
| Prompt style | `src/agent/nodes/analysis.py:70-117` | F-strings with embedded unit_text; CRITICAL RULES list; Chinese-aware fonts |
| Return contract | `src/agent/templates.py` M2 templates | Transform → `{"columns": {...}, "artifacts": []}`, Filter → `{"filtered_df": ..., "snapshot_name": str, "artifacts": []}`, Terminal → `{"columns": {}, "artifacts": [...]}` |
| Error handling | `src/agent/nodes/analysis.py:296-328` | `_execute_unit` result dict shape unchanged; sandbox JSON parse unchanged |
| Enum usage | `src/agent/state.py:9-17` | `UnitType.TRANSFORM`, `UnitType.FILTER`, `UnitType.TERMINAL` for branching |
| Tests | `tests/test_analysis.py:29-38` | Assert on prompt substrings per unit type |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/nodes/analysis.py` | UPDATE | Refactor `_build_unit_code_prompt` and `_build_unit_react_fix_prompt` to branch by `unit.unit_type` |
| `tests/test_analysis.py` | UPDATE | Add tests for per-unit-type prompt content; update existing prompt assertions |

## Tasks

### Task 1: Refactor `_build_unit_code_prompt` with per-unit-type contracts
- **Action**: Branch by `unit.unit_type` inside the function (or extract per-type helpers). Each branch adds type-specific rules and return format:
  - **Transform** (default/fallback): Keep existing rules (rows 1-15) + add row-semantic conservation rule (row count invariant, no groupby.agg). The stdout JSON line is now: `{"charts": [...], "statistics": {...}, "insights": [...], "columns": {"new_col": [values], ...}}` — column-based return matching the template contract.
  - **Filter**: Different rules — column set invariant, return a boolean mask or filtered indices conceptually, save filtered df to output.csv. JSON stdout: `{"charts": [], "statistics": {"row_count_before": N, "row_count_after": M}, "insights": [...], "snapshot_name": str}`.
  - **Terminal**: Rules — no data columns produced, only artifacts (charts/reports). output.csv NOT required. JSON stdout: `{"charts": ["chart1.png", ...], "statistics": {...}, "insights": [...]}`.
- **Mirror**: `src/agent/nodes/analysis.py:70-117` (existing f-string prompt style)
- **Validate**: `python -c "from src.agent.nodes.analysis import _build_unit_code_prompt; from src.agent.state import PlanUnit; u = PlanUnit(unit_id=1, purpose='test', unit_type='terminal'); print(_build_unit_code_prompt(u, '/tmp/x.csv', '/tmp/out')[:100])"`

### Task 2: Refactor `_build_unit_react_fix_prompt` with per-unit-type context
- **Action**: Same branching by `unit.unit_type`. The ReAct prompt includes the failed code + error message, plus the type-specific rules from Task 1 so the LLM knows what contract to fix toward.
- **Mirror**: `src/agent/nodes/analysis.py:140-193` (existing ReAct prompt)
- **Validate**: Same import check as Task 1 for the ReAct variant

### Task 3: Update `_serialize_unit` for LLM prompt context
- **Action**: Already done in M2 — `unit_type`, `execution_mode`, `template_name` are already in the JSON. No changes needed here. Verify the LLM prompt correctly includes `unit_type` in the serialized unit context.
- **Mirror**: `src/agent/nodes/analysis.py:35-50` (_serialize_unit)
- **Validate**: `pytest -v -m unit tests/test_analysis.py::test_serialize_unit`

### Task 4: Update existing prompt tests + add per-unit-type tests
- **Action**:
  - Update `test_build_unit_code_prompt_structure` to verify type-specific rules appear
  - Add `test_build_unit_code_prompt_transform` — checks row-count-invariant rule
  - Add `test_build_unit_code_prompt_filter` — checks column-set-invariant rule + snapshot_name
  - Add `test_build_unit_code_prompt_terminal` — checks "no data columns" rule + no output.csv requirement
  - Update `test_build_unit_code_prompt_with_upstream` for all three types
  - Add corresponding ReAct prompt tests
- **Mirror**: `tests/test_analysis.py:29-43` (existing prompt tests)
- **Validate**: `pytest -v -m unit tests/test_analysis.py`

## Validation

```bash
pytest -v -m unit tests/test_analysis.py     # All analysis tests pass
pytest -v                                      # Full suite (237 tests)
ruff check .                                   # Clean
mypy src/ --ignore-missing-imports             # No new errors
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM-generated code quality degrades with new prompt wording | Low | Only add type-specific rules, don't remove existing rules (sandbox safety stays); template mode covers high-frequency ops |
| Transform prompt becomes too long (rules bloat) | Low | Keep common rules in a shared preamble; append type-specific rules after |
| Filter/Terminal LLM code doesn't save output.csv correctly | Medium | The sandbox still runs the code as-is; `_save_unit_checkpoint` in dag.py handles missing output.csv gracefully (logs warning, skips) |
| Existing prompt tests break from text changes | Medium | Tests check for key phrases ("data analyst", "Agg", "SimHei") — these stay in the common preamble, should still pass |

## Acceptance

- [ ] `_build_unit_code_prompt` branches by `unit.unit_type` with type-specific return contracts
- [ ] `_build_unit_react_fix_prompt` branches by `unit.unit_type`
- [ ] Common sandbox rules preserved across all three types (Agg backend, Chinese fonts, no network, try/except)
- [ ] All existing analysis tests pass
- [ ] New per-unit-type prompt tests pass
- [ ] `ruff check .` clean
- [ ] `mypy src/` no new errors
