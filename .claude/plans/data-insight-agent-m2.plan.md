# Plan: DataInsight — Milestone 2 — Business Track + Decision Match

**Source PRD**: [.claude/prds/data-insight-agent.prd.md](../.claude/prds/data-insight-agent.prd.md)
**Selected Milestone**: #2 — Business Track + Decision Match node
**Complexity**: Medium

## Summary

Implement the remaining two nodes of Stage 1+2: **Business Track** (pure LLM reasoning about the user's business question — derives ideal metrics without seeing data) and **Decision Match** (LLM-driven alignment: maps business ideals to available data columns, identifies gaps, proposes trade-offs, produces a concrete execution plan). Both are pure LLM nodes with no sandbox execution. After M2, the pipeline from START through execution_plan will be fully functional.

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Node signature | [data_track.py:62](src/agent/nodes/data_track.py#L62) | `node(state: AgentState) -> AgentState` — read fields, return `{**state, "new_field": value}` |
| Error signaling | [data_track.py:75](src/agent/nodes/data_track.py#L75) | Write `state["error"]` string, return early. Never raise from node. |
| LLM invocation | [data_track.py:83-85](src/agent/nodes/data_track.py#L83-L85) | `get_llm(temperature=0)` → `llm.invoke(prompt)` → extract `.content` |
| Prompt pattern | [data_track.py:18-59](src/agent/nodes/data_track.py#L18-L59) | `_build_*_prompt()` private function returning f-string with role instructions + structure requirements |
| Immutable update | [data_track.py:90](src/agent/nodes/data_track.py#L90) | `{**state, "key": value}` — never mutate |
| Logging | [data_track.py:69,89](src/agent/nodes/data_track.py#L69) | `logger.info()` on entry/exit, `logger.error()` on failures |
| Tests | [test_data_track.py](tests/test_data_track.py) | Mock LLM via `MagicMock`, verify prompt content, verify state keys, verify state preservation |
| Fixtures | [conftest.py](tests/conftest.py) | Reuse `sample_csv_path`, `set_llm_env` |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/nodes/business_track.py` | UPDATE | Replace stub with real LLM-driven business reasoning node |
| `src/agent/nodes/decision_match.py` | UPDATE | Replace stub with real LLM-driven alignment node |
| `tests/test_business_track.py` | CREATE | Unit tests: prompt structure, node success, error handling |
| `tests/test_decision_match.py` | CREATE | Unit tests: prompt structure, node success, state preservation |
| `tests/test_graph.py` | UPDATE | Expand integration test to cover Business Track + Decision Match with real nodes |
| `.claude/decisions.md` | UPDATE | Record D11 (sequential dual-track) and any new decisions |

## Design Notes

### Business Track — "What would ideal look like?"

The LLM receives ONLY the user's business requirement — it MUST NOT see the data or the Data Track report. This is the core PRD philosophy: business reasoning is independent of data constraints.

Prompt structure (Chinese):
1. 业务问题重述 — restate the business question
2. 理想指标体系 — what KPIs/metrics would answer this question (assuming perfect data)
3. 维度与切分 — needed dimensions, filters, comparison windows
4. 理想图表方案 — what charts would tell the story best
5. 数据需求清单 — what columns/types are needed (abstract, not referring to actual data)

### Decision Match — "What can we actually do?"

The LLM receives both `data_report` (Data Track output) and `business_plan` (Business Track output). It must align them and produce a concrete, prioritized execution plan.

Prompt structure (Chinese):
1. 指标可行性映射 — for each business metric: which column(s) can compute it? Confidence level?
2. 数据缺口与替代方案 — where data falls short, propose alternatives or declare infeasible
3. 清洗优先级 — based on Data Track's audit, what MUST be cleaned before analysis
4. 分析执行步骤 — numbered, ordered list of concrete steps (clean → EDA → model → chart)
5. 数据与业务对齐备忘 **(mandatory per PRD)** — explicit alignment notes

### Sequential vs Parallel Dual-Track

The PRD describes Stage 1 as "Parallel Dual-Track Assessment." In the current graph, data_track and business_track run sequentially (data_track → business_track). True parallel execution in LangGraph 1.0 requires the `Send` API, which adds complexity (fan-out from START, fan-in to decision_match, error aggregation). For MVP CLI usage, the benefit of parallelism is negligible (both are LLM calls, user waits either way). Sequential execution is a deliberate simplification — recorded as D11 in decisions.md.

## Tasks

### Task 1: Implement Business Track node
- **Action**: Replace `business_track_node()` stub in `src/agent/nodes/business_track.py` with:
  1. `_build_business_prompt(user_requirement: str) -> str` — Chinese prompt with 5 sections
  2. `business_track_node(state: AgentState) -> AgentState` — call LLM, write `state["business_plan"]`, handle errors
- **Mirror**: [data_track.py](src/agent/nodes/data_track.py) — same node shape, same LLM call pattern, same error handling
- **Validate**: `pytest tests/test_business_track.py -v` green, ruff + mypy clean

### Task 2: Implement Decision Match node
- **Action**: Replace `decision_match_node()` stub in `src/agent/nodes/decision_match.py` with:
  1. `_build_decision_prompt(data_report: str, business_plan: str) -> str` — Chinese prompt with 5 sections, mandatory alignment notes
  2. `decision_match_node(state: AgentState) -> AgentState` — call LLM, write `state["execution_plan"]`, handle errors
- **Mirror**: [data_track.py](src/agent/nodes/data_track.py) — same node shape, plus reading TWO upstream fields (data_report + business_plan)
- **Validate**: `pytest tests/test_decision_match.py -v` green, ruff + mypy clean

### Task 3: Unit tests for Business Track
- **Action**: Create `tests/test_business_track.py` with 5 tests:
  1. `test_build_business_prompt_structure` — all 5 Chinese sections present
  2. `test_build_business_prompt_includes_requirement` — user requirement embedded in prompt
  3. `test_business_track_node_success` — mocked LLM, verify `business_plan` in returned state
  4. `test_business_track_node_preserves_state` — input fields carried forward
  5. `test_business_track_node_llm_error` — LLM exception → error in state
- **Mirror**: [test_data_track.py](tests/test_data_track.py) — same structure, mock pattern, assertion style
- **Validate**: `pytest tests/test_business_track.py -v` — 5 passed

### Task 4: Unit tests for Decision Match
- **Action**: Create `tests/test_decision_match.py` with 5 tests:
  1. `test_build_decision_prompt_structure` — all 5 Chinese sections + mandatory alignment notes heading
  2. `test_build_decision_prompt_includes_both_inputs` — data_report and business_plan embedded
  3. `test_decision_match_node_success` — mocked LLM, verify `execution_plan` in returned state
  4. `test_decision_match_node_preserves_state` — all input fields carried forward
  5. `test_decision_match_node_missing_data_report` — error when upstream data missing
- **Mirror**: [test_data_track.py](tests/test_data_track.py) + [test_data_track.py:73-79](tests/test_data_track.py#L73-L79) (error path pattern)
- **Validate**: `pytest tests/test_decision_match.py -v` — 5 passed

### Task 5: Expand graph integration test
- **Action**: Update `tests/test_graph.py` to test the real Business Track + Decision Match nodes (mocked LLM). Verify:
  1. Full M1+M2 pipeline (data_track → business_track → decision_match) runs end-to-end
  2. `execution_plan` is populated after decision_match
  3. Graph still fails gracefully at execution stub
- **Mirror**: [test_graph.py](tests/test_graph.py) — existing `test_graph_data_track_integration`
- **Validate**: `pytest tests/test_graph.py -v` — expanded test passes

### Task 6: Update decisions.md
- **Action**: Add D11 (sequential dual-track simplification) to `.claude/decisions.md`
- **Mirror**: D1-D10 format
- **Validate**: File reads cleanly

## Validation

```bash
# Lint & type check
ruff check . && ruff format --check . && mypy src/

# Unit tests (new nodes)
pytest -v tests/test_business_track.py tests/test_decision_match.py

# Graph integration
pytest -v tests/test_graph.py

# Full suite
pytest -v
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Business Track prompt is too vague → LLM produces generic output | Medium | Prompt forces 5-section structure with concrete subsections; test validates all sections present |
| Decision Match prompt overflows context window (data_report + business_plan both long) | Low | Truncate or summarize inputs if needed; for now, both are LLM outputs of ~1-2k chars each |
| LLM in Decision Match invents column names not in data | Medium | Prompt explicitly requires quoting from data_report; test validates data_report content is embedded in prompt |
| Sequential dual-track violates user expectation of parallelism | Low | Documented as D11; trivial to upgrade to Send API later |

## Acceptance

- [ ] Business Track node produces structured `business_plan` from `user_requirement`
- [ ] Decision Match node produces structured `execution_plan` from `data_report` + `business_plan`
- [ ] Decision Match output includes mandatory "数据与业务对齐备忘" section
- [ ] Both nodes follow existing error handling pattern (`state["error"]`, not exceptions)
- [ ] All tests pass (10 new + existing 14 = 24 total)
- [ ] ruff check + mypy src/ clean
- [ ] Graph compiles with all real nodes (data_track, business_track, decision_match)
- [ ] PRD Delivery Milestones table updated: M1 → complete, M2 → in-progress

---
*Plan for Milestone 2 of 4.*
