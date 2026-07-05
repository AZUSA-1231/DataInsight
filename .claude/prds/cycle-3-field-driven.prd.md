# DataInsight Cycle 3 — Field-Driven Analysis Architecture

## Problem

DataInsight currently operates as a black-box pipeline: data_track and business_track feed into planner, which produces a monolithic Plan. Three architectural gaps prevent it from evolving into a BI-like analysis platform:

1. **No explicit field schema**. The column list is buried inside `DataProfile`. Planner receives it indirectly via a large JSON blob. There is no "contract" — a clean, dedicated list of available columns that both users and planner can reason about.
2. **Mandatory business_track dependency**. Planner always consumes `AnalysisIntent` from business_track. Users who already know what analysis they want (e.g., "profile the 销量, 地区, 年龄 columns") cannot bypass the intent extraction step or directly compose a Plan.
3. **Fields and units are disconnected**. `PlanUnit` has `purpose`, `model`, `cautious` — but no `related_fields`. A unit that says "analyze regional sales trends" has no structured reference to which columns it actually operates on. This makes plan validation impossible and blocks future frontend field-wiring interactions.

**M1 完成后发现的新问题**：

4. **`draft_plan` vs `plan` 语义分裂**：M1 引入 `draft_plan` 来区分"用户组装的"和"系统生成的"Plan，但 planner 不关心来源——它只看到当前 workspace 里有什么。两个字段造成状态管理的冗余和调用方的困惑。
5. **business_track 被二元路由浪费**：`_should_skip_business_track` 在有 `draft_plan` 时跳过 business_track，但 business_track 在 workspace 非空时本可以消费 workspace 产出 Contextualized Intent（理解对话在修改哪个 unit/字段）。
6. **Planner 三模式分支僵硬**：feedback > draft_plan > generate 的 if/elif/else 编码了固定的优先级，但实际场景中用户可能同时有 workspace 和对话，LLM 应该自行判断修订深度。

## Evidence

- **data_track does unnecessary LLM work**: the cleaning insights prompt runs on every invocation, but in BI scenarios data is assumed relatively clean — this is a holdover from the scraping-data era → **M1 resolved**
- **No column-level audit trail**: report_gen has no structured way to know which columns each unit used; it relies on the LLM to extract column names from free-text purpose strings
- **Single-table architecture baked deep**: `AgentState.file_path` is a scalar string; `inspection_script.py` takes exactly one file argument; the word "merge" does not appear in the codebase
- **Planner is the bottleneck for user agency**: the only way to influence the Plan is via the post-hoc CLI review loop (add/remove/modify commands), which is a debug tool, not a design surface

## Users

- **Primary**: non-technical business users who want to select columns and specify analysis logic — they understand their data domain but cannot write Python
- **Secondary**: developers building analysis workflows who need programmatic control over column-to-unit wiring
- **Currently**: the project developer validating the architecture through CLI demos
- **Not for**: casual "glance at a CSV" exploration (upload to a chatbox suffices)

## Hypothesis

We believe that establishing a **unified field schema** (`unified_columns`) as a first-class state concept and adding **`related_fields`** to `PlanUnit` will:

1. Give planner a clean, structured view of available columns for validation and correction
2. Enable a **workspace-centric model** where the user can freely assemble Plans (drag, modify, regenerate) and the agent adapts to whatever is in the workspace
3. Create the foundation for future frontend field-wiring interactions (drag columns to logic units)

We'll know we're right when: planner can validate that all `related_fields` in a Plan exist in `unified_columns`; when the user can put any Plan in `state.plan` (regardless of origin) and the agent correctly handles it; and when business_track consumes workspace to produce contextualized intent.

## Architecture (Post-M2 Target)

```
                    START
                      │
                      ▼
                 data_track
              (deterministic)
              ┌──────┴──────┐
              │ unified_columns (表层) ──→ business_track + planner
              │ data_profile     (深层) ──→ planner only
              └──────┴──────┘
                      │
                      ▼
               business_track
          (workspace-aware intent)
           ┌─────────────────────┐
           │ workspace 空 → 纯翻译 │
           │ workspace 有 → 上下文 │
           │   感知的 Intent       │
           └─────────────────────┘
                      │
                      ▼
                   planner
             (唯一 Plan 出口)
           ┌─────────────────────┐
           │ 输入: workspace_plan  │
           │       intent         │
           │       data_profile   │
           │       unified_cols   │
           │ LLM 自行判断修订深度   │
           └─────────────────────┘
                      │
                      ▼
               preprocessing
                      │
                      ▼
                  analysis
                      │
                      ▼
                 report_gen
                      │
              ┌───────┴───────┐
              │ feedback?     │
              │ → business_track (重新解析意图)
              │ → END          │
              └───────────────┘
```

**数据认知分层**：

| 层 | 产出者 | 消费者 | 内容 |
|----|--------|--------|------|
| 表层 | data_track | business_track, planner | `unified_columns`（列名列表） |
| 深层 | data_track | planner only | `data_profile`（类型、统计、空值率） |

**关键原则**：

- `state.plan` 是 workspace 中唯一的 Plan。它可以是用户拖拽的、系统生成的、用户修改过的——来源无关。
- business_track 始终运行，作为 context provider（非 gate）。行为随 workspace 状态变化。
- planner 始终是唯一的 Plan 出口。输入始终是 `(workspace_plan, intent, data_profile, unified_columns)`。无模式分支——LLM 自行判断。

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| data_track LLM calls eliminated | 0 (was 1 per run) | Inspection of data_track_node code path |
| Planner field validation coverage | 100% of related_fields checked against unified_columns | Unit test: inject invalid field name, assert planner flags it |
| Workspace Plan acceptance | Planner can process workspace Plan from any origin | Integration test: state with plan from user/modified/system |
| Backward compatibility | All existing tests pass after migration | `pytest -v` |
| State model simplicity | 1 Plan field (down from 2) | `AgentState` has `plan`, no `draft_plan` |

## Scope

**M1 — Table Unification + Planner Dual Mode** ✅ DONE

1. **data_track refactor**: remove cleaning_insights LLM call; extract and return `unified_columns` from inspection
2. **State model**: add `unified_columns` and `draft_plan` to `AgentState`; add `related_fields` to `PlanUnit`
3. **Planner dual mode**: generate mode (Intent → Plan) and review mode (draft_plan → corrected Plan)
4. **Graph routing**: conditional edge after data_track — skip business_track when `draft_plan` is present
5. **Downstream adaptation**: preprocessing, analysis, and report_gen updated to use new fields; report_gen removes dependency on cleaning_insights
6. **CLI adaptation**: display `related_fields` in plan review; update intermediate artifact saving

> **M1 遗留问题**：`draft_plan` vs `plan` 双字段、`_should_skip_business_track` 条件路由、planner 三模式分支——这些将在 M2 中解决。

**M2 — Workspace-Aware Architecture Refactor**

1. **State 统一**：移除 `draft_plan` 字段。`state.plan` 是 workspace 中唯一的 Plan（可为 None），来源无关。
2. **Graph 线性化**：移除 `_should_skip_business_track`。`START → data_track → business_track → planner` 始终按序执行。
3. **business_track 重构**：消费 workspace Plan + dialog → Contextualized Intent。workspace 为空时退化为纯翻译器。
4. **planner 简化**：移除三模式 if/elif/else。统一输入 `(workspace_plan, intent, data_profile, unified_columns)`。LLM 自行判断：workspace 空 → 生成；用户措辞轻微 → 微调；用户说推倒 → 重来。
5. **feedback 流调整**：`_should_iterate` 路由到 `business_track`（而非 planner），feedback 作为额外对话输入重新解析意图。

**M3 — Frontend Field Wiring (future)**

- Web UI: field list + logic unit canvas
- Drag-and-drop column-to-unit wiring
- Real-time planner feedback via API

**Out of scope for Cycle 3**

- Multi-table merge/join — data_track still operates on single files; `unified_columns` is a passthrough from inspection for now
- CLI commands for specifying `related_fields` — `related_fields` are set by planner (generate mode) or provided by user via workspace Plan
- `cleaning_insights` field removal from state — KEPT as `None`-default field for backward compat; just no longer populated
- Function template library — separate milestone

## Delivery Milestones

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| M1 | Table Unification + Planner Dual Mode | unified_columns as state contract, PlanUnit.related_fields, planner generate/review modes, graph conditional routing, data_track sans LLM | **done** | [plans/cycle-3-m1-table-unification.plan.md](../plans/cycle-3-m1-table-unification.plan.md) |
| M2 | Workspace-Aware Architecture Refactor | `draft_plan` removed, business_track workspace-aware, planner unified path, graph linearized, feedback → business_track | planned | [plans/cycle-3-m2-workspace-awareness.plan.md](../plans/cycle-3-m2-workspace-awareness.plan.md) |
| M3 | Frontend Field Wiring (future) | Web UI: field list + logic unit canvas, drag-and-drop column-to-unit wiring, real-time planner feedback via API | not started | — |

## Open Questions

- [x] ~~When planner review mode rejects a draft_plan, should it return an error or a corrected plan?~~ → **M2 resolves**: planner always produces corrected plan; LLM decides revision depth.
- [x] ~~Should `draft_plan` be consumed (set to None) after planner processes it?~~ → **M2 resolves**: `draft_plan` field removed; `plan` persists as workspace state.
- [ ] In M2, business_track always runs (no skip). Does the extra 1-2s LLM call per invocation justify the always-available structured Intent? Current assessment: yes — the benefit of workspace-aware intent extraction outweighs the latency cost.
- [ ] When business_track sees an incomplete workspace unit (purpose empty but related_fields populated), should it infer purpose from the linked columns? Current design: business_track flags it as `partial`, planner completes it.
- [ ] For future M3: does data_track's LLM merge-logic belong in the same node, or should it be a separate `table_merger` node? Decision deferred to M3 planning.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Merging `draft_plan` into `plan` breaks tests that distinguish user vs system origin | High | Medium | Grep all references; replace `draft_plan` with `plan` everywhere |
| Planner without dedicated review-mode prompt produces lower-quality revisions | Medium | Medium | Workspace presence + Intent context in unified prompt gives planner enough information; tune if quality degrades |
| Feedback re-routing to business_track breaks existing feedback loop | Medium | Medium | feedback enters from report_gen → business_track; business_track treats feedback as additional dialog; verify in integration test |
| business_track always runs (no skip) — 1 extra LLM call per invocation | High | Low | ~1-2s extra latency; acceptable for the benefit of always having structured Intent |

---
*Status: M1 done. M2 planned at [plans/cycle-3-m2-workspace-awareness.plan.md](../plans/cycle-3-m2-workspace-awareness.plan.md).*
