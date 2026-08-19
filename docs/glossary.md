# DataInsight Glossary

Canonical product vocabulary across cycles. When a term appears in a PRD,
architecture plan, API, or UI, it means what is defined here. This document
resolves the "Canvas" ambiguity introduced in Cycle 7 and records the
Project / Agent-conversation model.

## Two axes that are easy to conflate

These are independent and must not be confused:

- **Isolation** — which conversation can see which messages and workspace.
- **Persistence location** — which file stores those messages.

Isolation is a logical model: an Agent conversation shares its Project's
workspace facts but never sees another conversation's messages, and two
Projects share nothing. Persistence location is a storage decision about which
file holds the messages. Changing one does not change the other.

## Core disambiguation

| Term | Meaning | Cycle |
|---|---|---|
| **Plan Canvas** | Visual DAG editor (React Flow nodes/edges) used to edit the Plan. | Cycle 7 |
| **Result Canvas / Board** | Presentation surface of tables, charts, and metric blocks that replaces the Markdown report. | Deferred to a later cycle |

These are different products. Do not refer to either one as just "Canvas".

## Vocabulary

| Term | 中文 | Meaning | Durable authority / boundary | Status |
|---|---|---|---|---|
| **Project** | 项目 | One analysis workspace: sources, Snapshots, Plan, results, report, layout, and its Agent conversations. | One session `state.json` + output directory | Existing session, surfaced as "Project" |
| **Agent conversation / Thread** | Agent 对话 / 线程 | One named, ordered conversation inside a Project. Shares that Project's workspace facts; never sees another thread's messages. | Project state (`AgentState.agent_threads` per Cycle 7 PRD) | Cycle 7 |
| **Plan** | 计划 | The executable, validated v2 DAG (units + `depends_on`). Semantic source of truth. | `AgentState.plan` | Existing |
| **Plan Canvas** | 计划画布 | Visual DAG editor for Plan units and dependency edges. | Derived from Plan + workspace layout | Cycle 7 |
| **Dashboard** | 结果 / 看板 | Presentation surface of tables, charts, and metric blocks replacing the Markdown report. | To be defined | Deferred |
| **Workspace layout** | 工作区布局 | Presentation-only positions, viewport, and collapsed state for Plan units. Never holds operation or dependency semantics. | `AgentState.workspace_layout` | Cycle 7 |
| **Source** | 数据源 | An uploaded CSV or Excel file. | Registry | Existing |
| **Snapshot** | 快照 | Logical data identity. | Registry | Existing |
| **Checkpoint** | 检查点 | An immutable version of a Snapshot. | Registry | Existing |
| **Qualified column** | 限定列 | A `source.snapshot.column` reference. | Registry | Existing |
| **Unit / Operation** | 单元 / 操作 | A node in the Plan DAG (Derive, Filter, Join, Terminal). | `Plan.units` | Existing |
| **Execution** | 执行 | Running the Plan DAG. | Execution service | Existing |
| **Result / Evidence** | 结果 | Execution output: warnings, stale state, row counts, charts. | Result area | Existing |
| **Report** | 报告 | The generated Markdown report. | Report area | Existing |
| **Dashboard** | 仪表盘 | Chart-pinning presentation surface. | Placeholder | Cycle 7 placeholder |
| **Lineage** | 血缘 | Column provenance tracking. | Lineage projection | Existing |
| **Copilot** | 副驾驶 / Agent 入口 | The bounded one-turn chat runtime. One LLM call per turn, no autonomous loop. | Selected thread history | Existing; thread-scoped in Cycle 7 |
| **Slash command / skill** | 斜杠命令 | Soft-injected command syntax; a leading `/` is a hint, not a hard requirement. | Prompt / static tool set | Existing |
