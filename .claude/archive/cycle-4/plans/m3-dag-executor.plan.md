# Plan: DAG Executor

**Source PRD**: .claude/prds/dag-executor.prd.md
**Selected Milestone**: M3 — DAG Executor
**Complexity**: Large

## Summary

Replace the current `ThreadPoolExecutor` flat-parallel execution in `analysis_node` with
topological-sort-driven DAG execution. Units are grouped into levels by dependency depth;
units within the same level run in parallel, levels run sequentially. Intermediate data
flows through `output.csv` files — each unit saves its transformed DataFrame, and the DAG
executor merges upstream outputs for downstream units. Column-existence validation runs
before each unit to fail fast with clear errors.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Naming | `src/agent/nodes/analysis.py:156` | `_execute_unit` — private function, verb_noun style |
| Error handling | `src/agent/nodes/analysis.py:302-314` | Return `{"error": "..."}` dict, `status: "failed"` in result, never raise from nodes |
| Logging | `src/agent/nodes/analysis.py:188-189` | `logger.info("Analysis unit [%d]: ...")` with unit_id prefix |
| Immutability | `src/agent/nodes/analysis.py:397-404` | Return `{**state, "key": value}`, never mutate state |
| Test fixtures | `tests/conftest.py:184-213` | `sample_plan_multi` — 3-unit Plan, factory pattern `make_plan` |
| Sandbox | `src/sandbox/executor.py:18-59` | `subprocess.run` with timeout, `SandboxResult` NamedTuple |
| LLM invoke | `src/agent/nodes/planner.py:209-215` | `get_llm(temperature=0)` → `.invoke([SystemMessage, HumanMessage])` |

## Architecture Decision: New `dag.py` Module

The DAG logic (topological sort, cycle detection, level grouping, column validation,
upstream merge) is a **pure algorithm** independent of LLM calls and sandbox execution.
Extracting it into `src/agent/dag.py` keeps `analysis.py` under the 800-line limit
and makes the DAG logic testable without mocking LLMs or subprocess.

`analysis_node` becomes thinner: it calls `dag.execute_dag()` which handles ordering,
then delegates to the existing `_execute_unit` for per-unit LLM + sandbox execution.

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/dag.py` | CREATE | Topological sort, cycle detection, column validation, upstream merge, level-parallel executor |
| `src/agent/nodes/analysis.py` | UPDATE | `_build_unit_code_prompt` — add upstream data context + output.csv rule; `analysis_node` — delegate to dag executor |
| `tests/test_dag.py` | CREATE | Pure-function tests for all DAG shapes, column validation, merge logic |
| `tests/test_analysis.py` | UPDATE | Update tests for new prompt fields, DAG-aware execution flow |
| `tests/test_graph.py` | UPDATE | Update integration tests for DAG execution |
| `tests/conftest.py` | UPDATE | Add DAG-specific Plan fixtures (chain, diamond, fan-out shapes) |

## Tasks

### Task 1: Create `src/agent/dag.py` — Topological Sort + Cycle Detection

- **Action**: Implement `topological_levels(units: list[PlanUnit]) -> list[list[PlanUnit]]` using Kahn's algorithm:
  1. Build adjacency list `{unit_id: [dependent_ids]}` from `depends_on`
  2. Compute in-degree for each unit
  3. Start with all units having in-degree 0 → level 0
  4. For each level: collect nodes, decrement in-degrees of their dependents, nodes reaching 0 go to next level
  5. If any nodes never reach in-degree 0 → cycle detected → raise `DagCycleError` (custom exception with unit_ids in the cycle)
- **Mirror**: `src/agent/state.py:109-117` PlanUnit model — `depends_on: list[int]`
- **Edge cases**:
  - Empty units list → `[]`
  - Single unit → `[[unit]]`
  - Self-loop (`depends_on` includes own unit_id) → cycle error
  - Missing dependency (depends_on references non-existent unit_id) → cycle error (can't resolve)
- **Validate**: `pytest -v -k "test_topological"` (after Task 6 tests written)

### Task 2: Create `src/agent/dag.py` — Column Validation

- **Action**: Implement `validate_columns(required: list[str], available: set[str]) -> tuple[list[str], list[str]]`:
  - Returns `(missing, found)` — columns that are required but not available, and columns that are available
  - If `required` is empty, return `([], [])` — no validation needed
  - Column names are compared **case-sensitively** and **exactly** (per PRD: strict matching first, fuzzy later if needed)
- **Mirror**: `src/agent/nodes/planner.py:179-182` — early-return pattern for missing data
- **Edge cases**:
  - Empty required → skip validation
  - All found → `([], required)`
  - All missing → `(required, [])`
  - Partial match → `(missing_subset, found_subset)`
- **Validate**: `pytest -v -k "test_validate_columns"`

### Task 3: Create `src/agent/dag.py` — Upstream Output Merge

- **Action**: Implement `merge_upstream_outputs(unit: PlanUnit, upstream_outputs: dict[int, str], original_path: str, output_dir: str) -> str | None`:
  1. If `unit.depends_on` is empty → return `None` (use original data)
  2. Load all upstream `output.csv` files into DataFrames
  3. Merge on index: `pd.concat([dfs], axis=1)`, dropping duplicate column names (keep first occurrence)
  4. If some `input_columns` are still missing after merge, also load the original file and merge those columns
  5. Save merged result to `<output_dir>/merged_input.csv`
  6. Return path to merged file
- **Mirror**: `src/sandbox/executor.py:38-43` — `errors="replace"` on encoding, tolerant I/O
- **Edge cases**:
  - Upstream unit failed (no output.csv) → skip that upstream, try remaining deps
  - All upstreams failed → return `None`, unit will fail column validation
  - Duplicate column names across upstreams → keep first, log warning
- **Validate**: `pytest -v -k "test_merge_upstream"` (requires temp CSV files)

### Task 4: Update Code-Gen Prompt — Upstream Context + output.csv

- **Action**: Modify `_build_unit_code_prompt` in `analysis.py`:
  1. Add `upstream_context: str` parameter — when unit has dependencies, describe what new columns are available from upstream units and which file contains them
  2. Add rule 14: "Save the final DataFrame (after all transformations, before creating charts) to `os.path.join(output_dir, 'output.csv')` using `df.to_csv(index=False)`. This output will be used by downstream analysis units."
  3. Add rule 15: "When UPSTREAM DATA section is present, the input file already contains columns produced by previous analysis steps. Use these columns as needed but do NOT overwrite them."
  4. Add `UPSTREAM DATA` section between ANALYSIS TASK and DATA FILE PATH when `upstream_context` is non-empty
  5. Keep backward compat: when `upstream_context` is empty/None, prompt is unchanged
- **Mirror**: Existing prompt structure at `analysis.py:48-91` — Chinese-aware, numbered CRITICAL RULES
- **Validate**: `pytest -v -k "test_build_unit_code_prompt"` — verify new rules appear when upstream_context is provided

### Task 5: Create `src/agent/dag.py` — Level-Parallel Executor

- **Action**: Implement `execute_dag(state: AgentState, parent_output_dir: str, prev_unit_results: dict[int, dict]) -> dict[str, Any]`:
  1. Call `topological_levels(plan.units)` → handle `DagCycleError` → return error result
  2. Initialize `upstream_outputs: dict[int, str] = {}` (unit_id → output.csv path)
  3. Initialize `available_columns = set(state.unified_columns)` (from original data)
  4. For each level:
     a. **Resolve inputs**: for each unit in level, compute `unit_input_path` (merged upstream or original), compute `unit_available_columns` (original + upstream output_columns)
     b. **Validate columns**: call `validate_columns(unit.input_columns or unit.related_fields, unit_available_columns)`. If missing columns → record failed result immediately, do NOT submit to executor
     c. **Parallel execute**: `ThreadPoolExecutor(max_workers=min(len(level), _MAX_WORKERS))` — submit `_execute_unit_with_input(unit, unit_input_path, unit_output_dir, prev_state)`
     d. **Collect results**: for each completed future, record result. On success → add `upstream_outputs[unit_id] = <output_dir>/output.csv`; on failure → dependent units in later levels will fail column validation (isolated blast radius)
  5. Return `{unit_results, status, output_dir}`
- **Key invariant**: units in the same level have NO dependencies on each other (guaranteed by Kahn's) → safe to run in parallel
- **Failure isolation**: if unit 1 fails, unit 2 (depends on 1) will fail column validation, but unit 3 (no deps, same level as unit 1) continues successfully
- **Mirror**: `src/agent/nodes/analysis.py:353-383` — ThreadPoolExecutor, as_completed, error collection pattern
- **Validate**: `pytest -v -k "test_analysis_node"` (after existing tests updated)

### Task 6: Modify `_execute_unit` — Accept Optional Input Path

- **Action**: Update `_execute_unit` signature and logic:
  1. Add `input_data_path: str | None = None` parameter
  2. Pass `input_data_path or data_path` to `_build_unit_code_prompt` as `file_path`
  3. After successful execution, verify `output.csv` exists in unit_output_dir. If missing and unit has dependents → log warning (not error — charts/insights are still valid)
  4. Build `upstream_context` string from `unit.input_columns` and `unit.output_columns` for the prompt
- **Mirror**: Existing `_execute_unit` at `analysis.py:156-299`
- **Validate**: `pytest -v -k "test_analysis_unit"` (after test updates)

### Task 7: Rewrite `analysis_node` — Delegate to DAG Executor

- **Action**: Replace the ThreadPoolExecutor flat-execution block in `analysis_node` with a call to `execute_dag()`:
  1. Keep existing guard clauses (no plan → error, no units → skip)
  2. Restore `prev_unit_results` from `state.analysis_result` (same as current logic for ReAct retry state)
  3. Call `execute_dag(state, parent_output_dir, prev_unit_results)`
  4. Return `{analysis_result: dag_result, error: ...}`
  5. `analysis_node` is now ~50 lines (down from ~105 lines of execution logic)
- **Mirror**: `src/agent/nodes/planner.py:161-238` — node function pattern: guard → execute → return dict
- **Validate**: `pytest -v -k "test_analysis_node"` — all existing tests pass with DAG path

### Task 8: Write `tests/test_dag.py` — Pure Function Tests

- **Action**: Create comprehensive test file for dag.py functions (no LLM/sandbox mocking needed):
  1. **Topological sort shapes**:
     - Linear chain: `[1→2→3]` → 3 levels `[[1], [2], [3]]`
     - Fan-out: `[1→2, 1→3]` → 2 levels `[[1], [2, 3]]`
     - Fan-in: `[1→3, 2→3]` → 2 levels `[[1, 2], [3]]`
     - Diamond: `[1→2, 1→3, 2→4, 3→4]` → 3 levels `[[1], [2, 3], [4]]`
     - Independent: `[1, 2, 3]` (no deps) → 1 level `[[1, 2, 3]]`
     - Single unit → `[[1]]`
     - Empty → `[]`
  2. **Cycle detection**:
     - Direct cycle: `[1→2, 2→1]` → `DagCycleError`
     - Self-loop: `[1→1]` → `DagCycleError`
     - Three-node cycle: `[1→2, 2→3, 3→1]` → `DagCycleError`
     - Missing dependency: unit depends on non-existent id → `DagCycleError`
  3. **Column validation**:
     - Exact match: `(["A", "B"], {"A", "B", "C"})` → `([], ["A", "B"])`
     - All missing: `(["X"], {"A", "B"})` → `(["X"], [])`
     - Partial: `(["A", "X"], {"A", "B"})` → `(["X"], ["A"])`
     - Empty required: `([], {"A"})` → `([], [])`
     - Case sensitive: `(["a"], {"A"})` → `(["a"], [])`
- **Mirror**: `tests/test_planner.py` — pure-function tests at top, parameterized where possible
- **Validate**: `pytest -v tests/test_dag.py`

### Task 9: Update Existing Tests

- **Action**: Update tests for the new DAG-aware execution:
  1. **`tests/conftest.py`**: Add DAG fixtures:
     - `sample_plan_chain` — 3 units with `depends_on=[1→2→3]`, `input_columns`/`output_columns` populated
     - `sample_plan_diamond` — 4 units diamond shape
  2. **`tests/test_analysis.py`**:
     - Update `test_build_unit_code_prompt_structure` — verify upstream_context injection
     - Add `test_build_unit_code_prompt_with_upstream` — prompt includes UPSTREAM DATA section
     - Add `test_build_unit_code_prompt_output_csv_rule` — verify rule 14 in prompt
     - Update `test_analysis_node_single_unit_success` — verify DAG path works for single unit
     - Update `test_analysis_node_multi_unit_all_succeed` — threads go through DAG levels
     - Add `test_analysis_node_dag_chain_execution` — chain 1→2→3, verify serial execution order via mock tracking
     - Add `test_analysis_node_dag_column_validation_fails` — unit with missing input_columns fails fast
     - Add `test_analysis_node_dag_failure_isolation` — independent unit succeeds while dependent fails
  3. **`tests/test_graph.py`**:
     - Update `test_graph_m3_execution_integration` — use DAG-aware fixtures
     - Update `test_graph_m4_full_pipeline` — use DAG-aware fixtures
- **Mirror**: Existing test patterns in `tests/test_analysis.py` and `tests/test_graph.py`
- **Validate**: `pytest -v` — all tests pass

### Task 10: Full Validation

- **Action**: Run full test suite, linter, and type checker
- **Validate**: `pytest -v && ruff check . && mypy src/`

## Validation

```bash
pytest -v && ruff check . && mypy src/
```

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| LLM fails to save output.csv in generated script | Medium | Downstream units can't access new columns | Prompt rule 14 is explicit; post-execution check logs warning; downstream falls back to original columns |
| Cycle detection false positive (Planner generates valid complex DAG) | Low | Execution blocked | Kahn's algorithm is deterministic and well-tested; if it happens, examine the Plan JSON to debug Planner |
| Merged intermediate CSV grows large (cartesian product on index merge) | Low | Disk space, merge time | Merge on index (not cross join); if columns explode, log warning and skip duplicate columns |
| column validation too strict (Planner names columns slightly differently) | Medium | Valid units fail pre-check | Strict match first per PRD; fallback to `related_fields` when `input_columns` is empty; M4 may add fuzzy matching |
| Existing tests break due to DAG serialization overhead | Low | CI red | DAG for single-unit and no-dep cases is identical to flat execution (1 level, 1 unit) |
| ThreadPoolExecutor inside sequential levels reduces parallelism benefit | Low | Performance | Most real Plans have 2-3 levels with 1-2 units each; parallelism is at the level boundary, which is the correct granularity |

## Acceptance

- [ ] All tasks complete
- [ ] Validation passes (pytest + ruff + mypy)
- [ ] `topological_levels` correctly handles: chain, fan-out, fan-in, diamond, cycle, empty, single
- [ ] Column validation fails fast with clear missing-column errors
- [ ] Upstream output.csv is merged and passed to downstream units
- [ ] Independent units continue executing when another unit fails
- [ ] Code-gen prompt includes output.csv save rule and upstream data context
- [ ] All existing tests updated and passing
