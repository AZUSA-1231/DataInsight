# Plan: DataInsight — Milestone 4 — Report Generation + In-Session Iteration

**Source PRD**: [.claude/prds/data-insight-agent.prd.md](../.claude/prds/data-insight-agent.prd.md)
**Selected Milestone**: #4 — Report assembly + in-session iteration
**Complexity**: Medium

## Summary

Implement the final Report Generation node — an LLM assembles all four intermediate outputs (data_report, business_plan, execution_plan, execution_result) into a comprehensive Markdown report with mandatory "Data & Business Alignment Notes" chapter. Add a `feedback` field to AgentState and a conditional edge from report_gen back to decision_match, enabling in-session iteration: the user reviews the report, provides feedback, and the graph re-plans and re-executes without re-running Data Track or Business Track. Finally, create a simple CLI entry point so the agent is actually runnable.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Node signature | [data_track.py:62](src/agent/nodes/data_track.py#L62) | `node(state: AgentState) -> AgentState`, immutable return |
| Prompt builder | [data_track.py:18](src/agent/nodes/data_track.py#L18) | `_build_*_prompt()` private function returning Chinese f-string |
| LLM call | [data_track.py:83-85](src/agent/nodes/data_track.py#L83-L85) | `get_llm(temperature=0)` → `invoke()` → `.content` with isinstance narrowing |
| Error signaling | [data_track.py:73-75](src/agent/nodes/data_track.py#L73-L75) | `state["error"]` string, never raise |
| Conditional edge | [graph.py:43-47](src/agent/graph.py#L43-L47) | `add_conditional_edges(src, router, mapping)` with `Literal` return type |
| Immutable state consume | [execution.py:200-202](src/agent/nodes/execution.py#L200-L202) | `new_state.pop("error", None)` to remove a field from spread dict |
| Logging | [data_track.py:69,89](src/agent/nodes/data_track.py#L69) | `logger.info()` entry/exit, `logger.error()` on failure |
| Tests | [test_data_track.py](tests/test_data_track.py) | Mock LLM, verify prompt content, verify state keys |
| Graph integration test | [test_graph.py](tests/test_graph.py) | Sequential node chaining with mocked LLMs + sandbox |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/state.py` | UPDATE | Add `feedback: NotRequired[str]` field |
| `src/agent/nodes/report_gen.py` | UPDATE | Replace stub with real LLM-driven report assembly |
| `src/agent/nodes/decision_match.py` | UPDATE | Incorporate `feedback` into prompt when present; consume feedback from state |
| `src/agent/graph.py` | UPDATE | Add `_should_iterate` router + conditional edge from report_gen back to decision_match |
| `src/__main__.py` | CREATE | CLI entry point: argparse → build graph → invoke → print report → feedback loop |
| `pyproject.toml` | UPDATE | Add `[project.scripts]` console_scripts entry point |
| `tests/test_report_gen.py` | CREATE | Unit tests: prompt structure, success, partial report on error, feedback incorporation |
| `tests/test_graph.py` | UPDATE | Full 5-node integration test + feedback iteration test |
| `tests/conftest.py` | UPDATE | Add `sample_execution_result` fixture |
| `.claude/decisions.md` | UPDATE | Record D14 (feedback loop design), D15 (CLI simplicity) |

## Design Notes

### Report Structure

The LLM receives all 4 intermediate outputs and assembles a Markdown report:

```
# DataInsight Analysis Report

## Executive Summary
(LLM-written 3-5 sentence summary of findings)

## 1. Data Technical Audit
(Reproduced/condensed from data_report)

## 2. Business Analysis Framework
(Reproduced/condensed from business_plan)

## 3. Analysis Execution & Results
(From execution_result: charts, statistics, insights)

## 4. Data & Business Alignment Notes ← MANDATORY
- What the business asked vs. what the data could answer
- Gaps and trade-offs made
- Limitations the reader should understand
- Honesty statement

## 5. Charts
(Embedded chart references from execution_result["parsed_output"]["charts"])

## 6. Caveats & Next Steps
```

### Error Handling (Partial Report)

If `state["error"]` is set (execution failed after 3 retries), report_gen produces a **partial report**: includes Data Audit, Business Framework, and Alignment Notes, but replaces execution results with an error section explaining what failed and why. This ensures the user always gets *something* — even a failed pipeline produces audit-level value.

### Feedback Loop

```
report_gen → _should_iterate(state):
  if state["feedback"] and state["feedback"] != "":
    → "decision_match"  (re-plan with feedback, skip data+business tracks)
  else:
    → END

decision_match (with feedback):
  - Prompt includes: original execution_plan + user feedback
  - LLM generates revised execution_plan
  - Returns state WITHOUT "feedback" (consumes it)
  - Then: execution → report_gen → END (feedback already consumed)
```

Key insight: data_track and business_track are NOT re-run during iteration.
The user's feedback is about the *analysis execution*, not the raw data.
This saves LLM calls and respects the PRD's "reuses prior analysis context."

### CLI Interface

```bash
# First run
python -m src data.csv "Why did Q2 sales drop by 15%?"

# Agent runs pipeline, saves report to data_analysis_report.md
# Agent prints: "Report saved. Enter feedback or press Enter to exit:"
# User types feedback
# Agent re-runs from decision_match with feedback
# Outputs revised report
```

Simple argparse-based, single-file, no external CLI framework.

## Tasks

### Task 1: Add feedback field to AgentState
- **Action**: Add `feedback: NotRequired[str]` to `AgentState` TypedDict in `src/agent/state.py`.
- **Mirror**: Existing `NotRequired` fields in [state.py](src/agent/state.py)
- **Validate**: `mypy src/` clean

### Task 2: Implement report_gen node
- **Action**: Replace stub in `report_gen.py` with:
  1. `_build_report_prompt(data_report, business_plan, execution_plan, execution_result, error)` — Chinese prompt instructing LLM to assemble all 4 outputs into the 6-section Markdown report, with mandatory "数据与业务对齐备忘" chapter
  2. `_build_partial_report_prompt(...)` — variant for when execution failed (error present)
  3. `report_gen_node(state)` — determine full vs partial → LLM → write `state["final_report"]`
- **Mirror**: [data_track.py:18-90](src/agent/nodes/data_track.py) — prompt builder + node shape
- **Validate**: `pytest tests/test_report_gen.py -v` green, ruff + mypy clean

### Task 3: Add feedback routing to graph
- **Action**: In `graph.py`:
  1. Add `_should_iterate(state) -> Literal["decision_match", "__end__"]` — checks `state.get("feedback")`
  2. Replace `graph.add_edge("report_gen", END)` with `graph.add_conditional_edges("report_gen", _should_iterate, {"decision_match": "decision_match", "__end__": END})`
- **Mirror**: [graph.py:43-47](src/agent/graph.py#L43-L47) — existing conditional edge pattern
- **Validate**: `pytest tests/test_graph.py -k "conditional"` passes

### Task 4: Update decision_match to handle feedback
- **Action**: In `decision_match.py`:
  1. Check `state.get("feedback")` — if present, modify prompt to include "USER FEEDBACK" section instructing LLM to revise the execution plan accordingly
  2. Return state WITHOUT `feedback` key (consume it via `new_state.pop("feedback", None)`)
- **Mirror**: [execution.py:200-202](src/agent/nodes/execution.py#L200-L202) — `pop("error", None)` pattern for consuming state keys
- **Validate**: `pytest tests/test_decision_match.py -v` green (add feedback test if needed)

### Task 5: Create CLI entry point
- **Action**: Create `src/__main__.py`:
  1. argparse: positional args for `file_path` and `requirement`
  2. Build graph, invoke with initial state
  3. Print report to stdout AND save to `{filename}_analysis_report.md`
  4. Interactive feedback loop: prompt user → set feedback in state → re-invoke graph
  5. Handle errors gracefully (print error, exit non-zero)
- **Mirror**: Standard Python CLI pattern (argparse, simple loop)
- **Validate**: `python -m src --help` prints usage; dry-run with env vars set

### Task 6: Unit tests for report_gen
- **Action**: Create `tests/test_report_gen.py` with 6 tests:
  1. `test_build_report_prompt_structure` — all 6 Chinese sections present
  2. `test_build_report_prompt_mandatory_alignment_notes` — "数据与业务对齐备忘" present
  3. `test_build_partial_report_prompt_includes_error` — error content embedded
  4. `test_report_gen_node_success` — mocked LLM, verify `final_report` populated
  5. `test_report_gen_node_partial_report` — error in state → partial report prompt used
  6. `test_report_gen_node_preserves_state` — all input fields carried forward
- **Mirror**: [test_data_track.py](tests/test_data_track.py) — mock pattern, structure assertions
- **Validate**: `pytest tests/test_report_gen.py -v` — 6 passed

### Task 7: Expand graph integration tests
- **Action**: Add tests to `test_graph.py`:
  1. `test_graph_m4_full_pipeline` — all 5 nodes chained, verify `final_report` populated
  2. `test_graph_feedback_iteration` — set feedback in state → verify decision_match consumes it → verify report_gen gets updated plan
- **Mirror**: [test_graph.py:67-120](tests/test_graph.py#L67-L120) — sequential node chaining pattern
- **Validate**: `pytest tests/test_graph.py -v` — new tests pass

### Task 8: Add sample_execution_result fixture
- **Action**: Add `sample_execution_result` fixture to `conftest.py` — a dict matching the shape of a successful `execution_result` (with parsed_output, charts, etc.)
- **Mirror**: [conftest.py:11-23](tests/conftest.py#L11-L23) — existing fixture pattern
- **Validate**: fixture importable in test_report_gen.py

### Task 9: Update decisions.md
- **Action**: Add D14 (feedback loop via conditional edge — skips data+business tracks), D15 (CLI simplicity — single-file argparse, no rich/tui framework)
- **Mirror**: Existing D1-D13 format

## Validation

```bash
# Lint & type check
ruff check . && ruff format --check . && mypy src/

# Report gen tests
pytest -v tests/test_report_gen.py

# Graph integration (full pipeline + feedback)
pytest -v tests/test_graph.py

# Full suite
pytest -v

# CLI smoke test
python -m src --help
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Report prompt overflows LLM context (4 intermediate outputs can be large) | Medium | Prompt instructs LLM to condense, not copy-paste; truncation fallback in node |
| Feedback loop infinite if LLM doesn't fix the issue | Low | Only one feedback cycle per user input (feedback consumed by decision_match); user must explicitly provide new feedback |
| Partial report (execution failed) looks broken to user | Medium | Report clearly labels sections as "PARTIAL" and explains what failed; user can still use data audit + business analysis |
| CLI interactive loop blocks on platforms without proper stdin | Low | argparse handles stdin; Windows/macOS/Linux all support basic input() |

## Acceptance

- [ ] Report Gen node produces comprehensive 6-section Markdown report
- [ ] Report includes mandatory "Data & Business Alignment Notes" chapter
- [ ] Partial report generated when execution failed (error in state)
- [ ] Feedback loop: user feedback → re-plan → re-execute → revised report
- [ ] CLI entry point works: `python -m src file.csv "question"`
- [ ] All tests pass (6 report_gen + graph integration + existing 40 = ~48 total)
- [ ] ruff check + mypy src/ clean
- [ ] PRD Delivery Milestones table: M4 → complete, all milestones done
- [ ] The agent is RUNNABLE end-to-end

---
*Final milestone. After M4, DataInsight MVP is feature-complete.*
