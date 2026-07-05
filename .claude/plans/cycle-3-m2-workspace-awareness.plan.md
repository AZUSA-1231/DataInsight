# Plan: Cycle 3 M2 — Workspace-Aware Architecture Refactor

**Source PRD**: [.claude/prds/cycle-3-field-driven.prd.md](../prds/cycle-3-field-driven.prd.md)
**Depends on**: [D51 — business_track 重构为 workspace-aware Intent 提取器](../decisions.md#d51--business_track-重构为-workspace-aware-intent-提取器)
**Complexity**: High (state model change, 3 nodes refactored, graph simplified, all test files touched)

## Motivation

M1 引入了 `draft_plan` 和条件路由 `_should_skip_business_track`，造成了两个架构问题：

1. **`draft_plan` vs `plan` 语义分裂**：同一个 workspace 里的 Plan 被拆成两个字段，区别仅在于"谁放进去的"。实际上 planner 不关心来源——它只看到"当前 workspace 里有什么"。
2. **business_track 被二元路由浪费**：要么跳过、要么运行，但 business_track 在 workspace 非空时本可以提供有价值的 Contextualized Intent（理解对话在修改哪个 unit/字段）。跳过它意味着 planner 要独自处理自然语言理解。

## Summary

1. **State 统一**：移除 `draft_plan` 字段。`plan` 承载 workspace 中的 Plan（可为 None），来源无关。
2. **Graph 线性化**：移除 `_should_skip_business_track` 条件边。`START → data_track → business_track → planner` 始终按序执行。
3. **business_track 重构**：消费 workspace Plan + dialog → Contextualized Intent。workspace 为空时退化为纯翻译器。
4. **planner 简化**：移除三模式分支（feedback > draft_plan > generate）。统一为单一路径：消费 `(workspace_plan, intent, data_profile, unified_columns)`，LLM 自行判断修订深度。
5. **feedback 流保持不变**：`_should_iterate` 条件边（report_gen → planner）保留，feedback 作为额外的对话文本传入 planner。

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| State model | [src/agent/state.py](src/agent/state.py) | `AgentState(BaseModel)` with `| None` optional fields |
| Node signature | [src/agent/nodes/data_track.py](src/agent/nodes/data_track.py) | `xxx_node(state: AgentState) -> dict[str, object]` |
| Immutability | [src/agent/nodes/planner.py](src/agent/nodes/planner.py) | Nodes return `dict[str, object]`, never mutate |
| Prompt building | [src/agent/nodes/planner.py](src/agent/nodes/planner.py) | Chinese f-string with CRITICAL RULES block |
| LLM calls | [src/agent/nodes/planner.py](src/agent/nodes/planner.py) | `get_llm(temperature=0, node="xxx")` → `.invoke(prompt)` → `.content` |
| Test mocking | [tests/test_planner.py](tests/test_planner.py) | `patch("src.agent.nodes.xxx.get_llm")` → `MagicMock(content=...)` |
| Contextualized prompts | [src/agent/nodes/planner.py](src/agent/nodes/planner.py) | `_build_planner_prompt_with_feedback` — multi-input prompt assembly |

## Files to Change

| File | Action | Why |
|---|---|---|
| `src/agent/state.py` | UPDATE | Remove `draft_plan` field; `plan` is now the sole workspace Plan |
| `src/agent/nodes/business_track.py` | UPDATE | Workspace-aware: consume `state.plan` when present; export `_build_contextualized_intent_prompt` |
| `src/agent/nodes/planner.py` | UPDATE | Drop 3-mode branching; unify into single generate/revise path; remove `_build_planner_review_prompt` |
| `src/agent/graph.py` | UPDATE | Remove `_should_skip_business_track`; linear `ST → DT → BT → planner` |
| `src/__main__.py` | UPDATE | Remove `draft_plan` references in `_handle_plan_modification` and state construction |
| `tests/conftest.py` | UPDATE | Remove `draft_plan` from state fixtures; rename `draft_plan` constructions to `plan` |
| `tests/test_graph.py` | UPDATE | Remove `_should_skip_business_track` tests; update integration test routing |
| `tests/test_planner.py` | UPDATE | Remove review-mode tests (`test_planner_node_review_mode`, `test_build_planner_review_prompt_structure`); add workspace-aware tests |
| `tests/test_business_track.py` | UPDATE | Add workspace-aware intent tests |
| `tests/test_data_track.py` | NONE | Unchanged — data_track is stable |
| `tests/test_preprocessing.py` | NONE | Unchanged |
| `tests/test_analysis.py` | NONE | Unchanged |
| `tests/test_report_gen.py` | NONE | Unchanged |

## Tasks

### Task 1: State model — merge `draft_plan` into `plan` (`src/agent/state.py`)

**Remove**:
```python
draft_plan: Plan | None = None       # 用户组装的草稿 Plan (审核模式入口)
```

**Keep**:
```python
plan: Plan | None = None             # 当前 workspace 中的 Plan (用户组装、系统生成、或用户修改后)
```

**Rationale**: `plan` 的来源（用户拖拽 vs 系统生成 vs 用户修改）不影响下游节点的行为。business_track 和 planner 只看到"当前 workspace 里有什么"。

**Validate**: `python -c "from src.agent.state import AgentState; s = AgentState(file_path='x', user_requirement='y'); assert s.plan is None; print('OK')"`

### Task 2: Graph linearization (`src/agent/graph.py`)

**Remove**: `_should_skip_business_track` function (lines 17-23).

**Replace**:
```python
graph.add_edge(START, "data_track")
graph.add_conditional_edges(
    "data_track",
    _should_skip_business_track,
    {"planner": "planner", "business_track": "business_track"},
)
graph.add_edge("business_track", "planner")
```

With:
```python
graph.add_edge(START, "data_track")
graph.add_edge("data_track", "business_track")
graph.add_edge("business_track", "planner")
```

New flow:
```
START → data_track → business_track → planner → preprocessing → analysis → report_gen → END
                                                                                      ↑
                                                         feedback ─────────────────────┘
```

**Validate**: `pytest -v -k "graph" tests/`

### Task 3: business_track — workspace-aware intent extraction (`src/agent/nodes/business_track.py`)

#### 3a. Add `_build_contextualized_intent_prompt`

```python
def _build_contextualized_intent_prompt(
    user_requirement: str,
    workspace_plan_json: str,
    unified_columns: list[str],
) -> str:
```

Prompt content:
- Input: user's dialog text + current workspace Plan (JSON) + available column names
- Task: 理解用户对话在修改 workspace 的哪个 unit/字段，产 Contextualized Intent
- CRITICAL RULES:
  1. 逐条分析用户对话中提到的修改，匹配到 workspace 中的具体 unit
  2. 如果用户措辞是"增加/删除/修改/拆分 XXX"，定位目标 unit_id
  3. 如果用户措辞是"推倒重来/全部重做"，在 Intent 中标记 `reset_workspace: true`
  4. 如果用户提到列名但 workspace 中该 unit 的 `related_fields` 没有，在 Intent 中记录
  5. Intent 的 `suggestions` 字段按 unit 分组，每条建议关联到具体 unit_id

#### 3b. Refactor `business_track_node`

```python
def business_track_node(state: AgentState) -> dict[str, object]:
    workspace_plan = state.plan      # 统一名称，不再是 draft_plan
    unified_columns = state.unified_columns

    if workspace_plan is not None and unified_columns:
        # 有 workspace + 有对话 → 上下文感知的 Intent
        prompt = _build_contextualized_intent_prompt(
            state.user_requirement,
            workspace_plan.model_dump_json(indent=2),
            unified_columns,
        )
    else:
        # workspace 为空 → 纯翻译器（现有逻辑）
        prompt = _build_intent_prompt(state.user_requirement)

    # ... LLM invoke + parse (unchanged)
```

**Validate**: `pytest -v -k "business_track" tests/`

### Task 4: planner — 统一单路径 (`src/agent/nodes/planner.py`)

#### 4a. Remove review-mode prompt builder

Delete `_build_planner_review_prompt()` function (~60 lines).

#### 4b. Unify `_build_planner_prompt` and `_build_planner_prompt_with_feedback`

Merge into single prompt builder:

```python
def _build_planner_prompt(
    data_profile_json: str,
    analysis_intent_json: str | None,
    unified_columns: list[str],
    workspace_plan_json: str | None,
) -> str:
```

Prompt structure:
- **Section 1**: AVAILABLE COLUMNS
- **Section 2**: DATA PROFILE
- **Section 3**: ANALYSIS INTENT (if present)
- **Section 4**: CURRENT WORKSPACE PLAN (if present)
- **CRITICAL RULES**:
  1-11 (existing, unchanged)
  12. If WORKSPACE PLAN is present: 用户对话针对已有 workspace。尊重用户已构建的结构——仅修正用户明确要求修改的部分。如果 Intent 中标记了 `reset_workspace: true`，忽略 workspace 重新生成。
  13. If WORKSPACE PLAN is absent: 从 Intent + Data Profile 生成全新 Plan。
  14. 如果 WORKSPACE PLAN 中有不完整 unit（purpose 为空但 related_fields 有值），补全 purpose 和 model。

#### 4c. Simplify `planner_node`

```python
def planner_node(state: AgentState) -> dict[str, object]:
    """Stage 3 — Planner: unified Plan decision maker.

    Always consumes: workspace_plan, analysis_intent, data_profile, unified_columns.
    LLM decides: generate from scratch, revise existing, or audit + correct.
    """
    data_profile = state.data_profile
    unified_columns = state.unified_columns
    workspace_plan = state.plan
    analysis_intent = state.analysis_intent

    # Guards
    if not data_profile:
        return {"error": "Planner: data_profile not available"}
    if not unified_columns:
        return {"error": "Planner: unified_columns not available"}

    data_profile_json = data_profile.model_dump_json(indent=2)
    intent_json = analysis_intent.model_dump_json(indent=2) if analysis_intent else None
    workspace_json = workspace_plan.model_dump_json(indent=2) if workspace_plan else None

    prompt = _build_planner_prompt(
        data_profile_json, intent_json, unified_columns, workspace_json,
    )

    # ... LLM invoke + JSON parse (unchanged)

    return {"plan": plan}
```

Note: `feedback` is consumed via `_should_iterate` → re-runs business_track + planner from START. The feedback text is in `state.feedback` and gets incorporated by business_track into the Contextualized Intent. Planner no longer needs a separate feedback branch.

Wait — this breaks the current feedback flow. Currently feedback re-enters at planner (skipping data_track + business_track). With the new linear graph, feedback re-entry needs to go through business_track too. Let me reconsider...

**Option A**: feedback → business_track (natural: business_track incorporates feedback into Intent)
**Option B**: keep feedback → planner (but planner no longer has a dedicated feedback branch)

**Decision**: Option A. `_should_iterate` routes to `business_track` instead of `planner`. business_track treats feedback as additional dialog input. This is cleaner — all natural language (original requirement + feedback) flows through business_track for intent extraction.

```python
# graph.py
def _should_iterate(state: AgentState) -> Literal["business_track", "__end__"]:
    if state.feedback:
        return "business_track"
    return "__end__"
```

**Validate**: `pytest -v -k "planner" tests/`

### Task 5: CLI adaptation (`src/__main__.py`)

- Remove `draft_plan` references in `_handle_plan_modification`
- Plan assembly: user-added units go to `state.plan` directly
- `_display_plan`: no behavior change (still reads `state.plan`)

**Validate**: `python -c "from src.__main__ import _display_plan; print('OK')"`

### Task 6: Test updates

#### 6a. `tests/conftest.py`
- Remove `draft_plan` from all state fixtures
- Rename any `draft_plan=...` constructor args to `plan=...`

#### 6b. `tests/test_graph.py`
- Remove `test_should_skip_business_track_no_draft` and `test_should_skip_business_track_with_draft`
- Update `test_should_iterate` to expect `"business_track"` instead of `"planner"`
- Update integration tests: remove `draft_plan` references; both business_track and planner always called

#### 6c. `tests/test_planner.py`
- Remove `test_planner_node_review_mode` (no more review mode)
- Remove `test_build_planner_review_prompt_structure` (function deleted)
- Add `test_planner_node_with_workspace_plan`: pass `plan=<some Plan>` → verify prompt includes workspace JSON
- Add `test_planner_node_no_workspace`: pass `plan=None` → verify prompt works without workspace
- Update `test_build_planner_prompt_structure`: check for new workspace sections

#### 6d. `tests/test_business_track.py`
- Add `test_contextualized_intent_prompt_structure`: verify prompt includes workspace JSON when present
- Add `test_business_track_node_with_workspace`: verify workspace-aware path
- Add `test_business_track_node_without_workspace`: verify pure translation path (backward compat)

#### 6e. Other test files
- `tests/test_data_track.py`: NO changes
- `tests/test_preprocessing.py`: NO changes
- `tests/test_analysis.py`: NO changes
- `tests/test_report_gen.py`: NO changes (already cleaned up in M1)

## Validation

```bash
# Unit
pytest -v -m unit

# Integration
pytest -v -m integration

# Full suite
pytest -v

# Type check
mypy src/

# Lint
ruff check . && ruff format . --check
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Merging `draft_plan` into `plan` breaks tests that assert `state.plan is None` when draft is present | High | Grep all `draft_plan` references; replace with `plan` |
| Planner prompt without dedicated review rules produces lower-quality revisions | Medium | Workspace presence + Intent context in prompt gives planner enough information; tune if quality degrades |
| Feedback re-routing to business_track breaks existing feedback loop | Medium | feedback always enters from report_gen → business_track with full state preserved; business_track needs `state.feedback` awareness |
| business_track now always runs (no skip path) — 1 extra LLM call per invocation | Low | business_track LLM call is fast (~1-2s); acceptable for the benefit of always having structured Intent |

## Acceptance

- [ ] `draft_plan` field removed from AgentState; `plan` is sole workspace Plan
- [ ] Graph: `START → data_track → business_track → planner` (no conditional edge)
- [ ] `_should_skip_business_track` removed
- [ ] business_track: workspace-aware prompt built when `plan is not None`
- [ ] business_track: workspace-empty path unchanged (backward compat)
- [ ] planner: no 3-mode branching; unified `_build_planner_prompt` with optional workspace
- [ ] planner: `_build_planner_review_prompt` removed
- [ ] Feedback iteration: `_should_iterate` routes to `business_track` (not planner)
- [ ] All existing tests pass (`pytest -v`)
- [ ] Type check passes (`mypy src/`)
- [ ] Lint passes (`ruff check .`)
