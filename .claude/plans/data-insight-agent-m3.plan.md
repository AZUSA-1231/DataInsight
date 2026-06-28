# Plan: DataInsight — Milestone 3 — Sandbox Execution + ReAct Self-Correction

**Source PRD**: [.claude/prds/data-insight-agent.prd.md](../.claude/prds/data-insight-agent.prd.md)
**Selected Milestone**: #3 — Sandbox execution + ReAct self-correction loop
**Complexity**: Large

## Summary

Implement the Execution node — the most complex node in the pipeline. The LLM receives the `execution_plan` (from Decision Match) and generates a complete Python analysis script (cleaning + EDA + charting). The script runs in the sandbox. On failure (syntax error, runtime error, timeout, invalid output), the LLM receives the error via a ReAct prompt and regenerates the code — up to 3 retries. On success, `execution_result` captures cleaned data stats, chart file paths, and key insights. The existing `_should_retry_execution` conditional edge in graph.py already implements the retry routing; this milestone makes it actually fire.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Node signature | [data_track.py:62](src/agent/nodes/data_track.py#L62) | `node(state: AgentState) -> AgentState`, immutable return |
| Prompt builder | [data_track.py:18](src/agent/nodes/data_track.py#L18) | `_build_*_prompt()` private function returning Chinese f-string |
| LLM call | [data_track.py:83-85](src/agent/nodes/data_track.py#L83-L85) | `get_llm(temperature=0)` → `invoke()` → `.content` with isinstance narrowing |
| Error signaling | [data_track.py:73-75](src/agent/nodes/data_track.py#L73-L75) | `state["error"]` string, never raise |
| Sandbox call | [data_track.py:71](src/agent/nodes/data_track.py#L71) | `run_script(script_path, [args...])` → `SandboxResult` |
| Logging | [data_track.py:69,89](src/agent/nodes/data_track.py#L69) | `logger.info()` entry/exit, `logger.error()` on failure |
| Tests | [test_data_track.py](tests/test_data_track.py) | Mock LLM, verify prompt content, verify state keys |
| Immutability | [data_track.py:90](src/agent/nodes/data_track.py#L90) | `{**state, "key": value}` |
| Retry routing | [graph.py:16-19](src/agent/graph.py#L16-L19) | `_should_retry_execution` — already wired, execution node just sets error + retry_count |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/nodes/execution.py` | UPDATE | Replace stub with real implementation: code generation + sandbox run + ReAct retry |
| `tests/test_execution.py` | CREATE | Unit tests: prompt structure, code gen, sandbox success, sandbox error → retry, max retries exhausted |
| `tests/conftest.py` | UPDATE | Add `temp_output_dir` fixture for chart output testing |
| `tests/test_graph.py` | UPDATE | Expand integration test: mock LLM-generated code that succeeds in sandbox, verify execution_result populated |
| `.claude/decisions.md` | UPDATE | Record D12 (LLM code generation approach), D13 (temp script lifecycle) |

## Design Notes

### Execution Flow

```
execution_node(state)
  │
  ├─ execution_result exists with error? ─── YES ──→ ReAct fix prompt (include prior code + error)
  │                                                      │
  │                                                      └─→ LLM generates fixed code
  │
  └─ NO (fresh attempt) ──→ Code generation prompt (execution_plan only)
                                │
                                └─→ LLM generates analysis script
  │
  ▼
  Write code to temp .py file
  │
  ▼
  run_script(temp_script, [file_path, output_dir])
  │
  ├─ exit_code == 0 + valid JSON stdout ──→ SUCCESS
  │   └─→ Populate execution_result with parsed output + chart paths
  │
  └─ exit_code != 0 OR invalid JSON OR timeout ──→ FAILURE
      ├─ retry_count < 3 ──→ Store code + error in execution_result["attempts"]
      │                      Set state["error"], increment retry_count
      │                      Conditional edge routes back to execution
      │
      └─ retry_count >= 3 ──→ Give up, set state["error"]
                                Conditional edge routes to report_gen
```

### Generated Script Contract

The LLM-generated script receives two CLI args: `file_path` and `output_dir`. It must:
1. Load the data file (CSV or Excel, with encoding detection)
2. Apply cleaning steps from the execution plan
3. Run EDA (distributions, correlations, group-bys)
4. Generate matplotlib charts and save them to `output_dir/` (use `Agg` backend)
5. Print a single JSON line to stdout with structure:
```json
{
  "cleaned_shape": {"rows": N, "cols": M},
  "cleaning_actions": ["dropped X rows...", "imputed Y with median..."],
  "charts": ["output_dir/bar_sales.png", ...],
  "statistics": {"correlations": {...}, "distributions": {...}},
  "insights": ["Sales peaked in Q3...", ...]
}
```

### Prompt Design

**Code generation prompt** (fresh attempt):
- Role: senior data engineer
- Input: execution_plan + file_path + output_dir
- Output: complete, runnable Python script
- Constraints: no network, Agg backend, handle Chinese fonts (fallback to sans-serif), use try/except, output valid JSON

**ReAct fix prompt** (retry):
- Role: debugging specialist
- Input: execution_plan + previous code + error message (stderr + stdout)
- Output: FIXED complete Python script
- Additional instruction: identify root cause first, then fix minimally

### Temp Script Lifecycle

Generated scripts are written to `tempfile.mkstemp(suffix=".py")`. They are NOT cleaned up after execution — the path is stored in `execution_result["script_path"]` for debugging. The OS temp directory handles eventual cleanup.

### Retry State Schema

`execution_result` during retry:
```python
{
    "retry_count": 2,
    "attempts": [
        {"code": "...", "error": "NameError: name 'df' is not defined"},
        {"code": "...", "error": "ValueError: ..."},
    ],
}
```

`execution_result` on success:
```python
{
    "retry_count": 1,
    "attempts": [...],
    "script_path": "/tmp/...",
    "stdout": "...",
    "parsed_output": {...},  # the JSON from the script
}
```

## Tasks

### Task 1: Implement code generation & ReAct prompts
- **Action**: Add `_build_code_gen_prompt(execution_plan, file_path, output_dir)` and `_build_react_fix_prompt(execution_plan, previous_code, error_message, file_path, output_dir)` in `execution.py`. Both return Chinese-structured prompts; code-gen instructs the LLM to write a complete Python script; ReAct adds prior code + error with fix instructions.
- **Mirror**: [data_track.py:18-59](src/agent/nodes/data_track.py#L18-L59) — prompt builder pattern
- **Validate**: `pytest tests/test_execution.py -k "prompt"` — all sections present, constraints embedded

### Task 2: Implement execution node with retry logic
- **Action**: Implement `execution_node(state)` in `execution.py`:
  1. Read `execution_plan`, `file_path`, `execution_result` (for retry context)
  2. Determine fresh vs retry → pick prompt builder
  3. LLM generates code → write to temp `.py` file
  4. `run_script()` with args `[file_path, output_dir]`
  5. Parse stdout as JSON; on parse failure → treat as error
  6. On success: populate `execution_result` with parsed output
  7. On failure: append to attempts, increment retry_count, set `state["error"]`
- **Mirror**: [data_track.py:62-90](src/agent/nodes/data_track.py#L62-L90) — node shape, error handling, LLM call
- **Validate**: `pytest tests/test_execution.py -v` green

### Task 3: Unit tests for execution node
- **Action**: Create `tests/test_execution.py` with 8 tests:
  1. `test_build_code_gen_prompt_structure` — all constraint sections present
  2. `test_build_react_fix_prompt_includes_error` — prior error embedded
  3. `test_execution_node_success_first_attempt` — mock LLM returns valid script, sandbox succeeds, verify `execution_result`
  4. `test_execution_node_react_retry_then_success` — first attempt fails, second succeeds, verify attempts history
  5. `test_execution_node_sandbox_error_triggers_retry` — sandbox error → `state["error"]` set, `retry_count` incremented
  6. `test_execution_node_max_retries_exhausted` — 3 failures → error, no infinite loop
  7. `test_execution_node_invalid_json_output` — sandbox succeeds but stdout isn't valid JSON → treated as error
  8. `test_execution_node_preserves_state` — all input fields carried forward on success
- **Mirror**: [test_data_track.py](tests/test_data_track.py) — mock pattern, assertion style
- **Validate**: `pytest tests/test_execution.py -v` — 8 passed

### Task 4: Add output_dir fixture
- **Action**: Add `temp_output_dir` fixture to `conftest.py` — creates a `tempfile.TemporaryDirectory`, yields the path, cleans up on teardown.
- **Mirror**: [conftest.py:11-23](tests/conftest.py#L11-L23) — existing tempfile fixture pattern
- **Validate**: fixture is importable and creates/deletes directory correctly

### Task 5: Expand graph integration test
- **Action**: Update `test_graph_m2_full_pipeline` in `test_graph.py` (or create new `test_graph_m3_pipeline`):
  1. Mock LLMs for data_track, business_track, decision_match
  2. Mock execution LLM to return a valid analysis script
  3. Run full pipeline: data_track → business_track → decision_match → execution
  4. Verify `execution_result` populated, `execution_plan` used
- **Mirror**: [test_graph.py:30-63](tests/test_graph.py#L30-L63) — existing integration test pattern
- **Validate**: `pytest tests/test_graph.py -v` — integration test passes

### Task 6: Update decisions.md
- **Action**: Add D12 (LLM generates analysis code — accepted hallucination risk mitigated by sandbox + ReAct) and D13 (temp scripts not cleaned up — debugging value > disk clutter for MVP)
- **Mirror**: D1-D11 format in [decisions.md](.claude/decisions.md)

## Validation

```bash
# Lint & type check
ruff check . && ruff format --check . && mypy src/

# Execution node tests
pytest -v tests/test_execution.py

# Graph integration (with execution)
pytest -v tests/test_graph.py

# Full suite
pytest -v
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| LLM generates code with destructive operations (`rm -rf`, `os.system`) | Low | Prompt explicitly forbids; sandbox timeout caps damage; no root privileges |
| LLM generates syntactically valid but logically wrong code (wrong column names) | High | ReAct loop catches runtime errors; column name hallucination caught by KeyError/AttributeError in sandbox |
| Generated charts have garbled Chinese text (no CJK fonts) | Medium | Prompt instructs `plt.rcParams['font.sans-serif'] = ['SimHei', ...]` with fallback to 'sans-serif'; font issue logged but doesn't fail execution |
| ReAct loop oscillates — LLM makes same mistake repeatedly | Low | Max 3 retries; each ReAct prompt includes full error history so LLM sees prior failures |
| Prompt + code + error exceeds LLM context window | Low | Code is ~100-200 lines; errors are typically <1KB; context is well within limits |
| Temp script files accumulate on disk | Low | OS temp dir handles cleanup; paths stored in state for debugging if needed |

## Acceptance

- [ ] Execution node generates Python code from execution_plan via LLM
- [ ] Generated code runs in sandbox with timeout protection
- [ ] Successful execution populates `execution_result` with parsed JSON output
- [ ] Sandbox errors trigger ReAct retry (LLM sees error, regenerates code)
- [ ] Max 3 retries, then routes to report_gen with error
- [ ] `_should_retry_execution` (existing) correctly gates the retry loop
- [ ] All tests pass (8 execution + existing 26 = 34 total)
- [ ] ruff check + mypy src/ clean
- [ ] PRD Delivery Milestones table updated: M2 → complete, M3 → in-progress

---
*Plan for Milestone 3 of 4.*
