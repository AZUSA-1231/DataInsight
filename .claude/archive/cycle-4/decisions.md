# Architecture Decision Log — DataInsight (Cycle 4)

Decisions made during Cycle 4 development. Cycle 3 decisions are archived at
[Cycle 3 decisions](../cycle-3/decisions.md).

---

## D54 — PlanUnit `model` → `model_hint` 重命名策略

**Date**: 2026-07-11
**Milestone**: M1 (PlanUnit model refactor + DAG engine overhaul)

**Decision**: 将 PlanUnit 的 `model` 字段重命名为 `model_hint`，但**保留 `model` 作为 deprecated property**（读 `model_hint`，写 `model_hint`），直到 M3 (LLM prompt refactor) 完成后移除。

**Rationale**:
- `model_hint` 更准确地表达了字段语义：这是给 LLM 的提示（"建议用线性回归"），而非强制的模型选择。随着 `execution_mode`（template/llm）引入，template mode 下模型由 template 决定，llm mode 下模型由 LLM 自行选择，`model_hint` 只是建议
- 保留 deprecated property 避免一次性破坏所有现有代码 —— Planner JSON 输出、`conftest.py` fixtures、workspace API 等数十处引用点
- M3 会系统性地更新 Planner system prompt，届时可以安全移除 property

**Impact**:
- `PlanUnit.model` 返回 `self.model_hint`（deprecation warning 不抛出，避免打断正常流程）
- 所有新代码使用 `model_hint`
- Planner 的 `_parse_plan_from_json` 同时接受 JSON 中的 `"model"` 和 `"model_hint"` key，统一映射到 `model_hint`
- M3 完成后移除 property + 统一 Planner prompt 输出 `model_hint`

**Re-evaluate**: M3 完成时确认所有引用点已迁移，然后移除 deprecated property。

---

## D55 — Parquet checkpoint 替代 CSV concatenation

**Date**: 2026-07-11
**Milestone**: M1 (PlanUnit model refactor + DAG engine overhaul)

**Decision**: 废除 `merge_upstream_outputs` (CSV axis=1 concat)，改用 Parquet checkpoint 链式传递数据。每个 Transform/Filter unit 执行成功后保存一个 Parquet checkpoint；downstream unit 直接读取上游最新的 checkpoint Parquet，不再合并多个 CSV。

**Rationale**:
- CSV concat 假设所有上游产出相同行数——这在 FilterUnit（减少行数）+ TransformUnit（保持行数）的混合 DAG 中结构性地失败
- Parquet 保留 dtype 信息，避免 CSV round-trip 的类型推断问题（e.g. 日期列被读回为 string）
- 链式 checkpoint（`wide_l{N}.parquet`）天然支持单 unit rerun：只需加载 rerun unit 的输入 checkpoint，执行，然后重放 downstream
- 每个 checkpoint 是完整 wide table，downstream unit 不需要知道哪些列来自哪个上游——简化了 LLM prompt

**Data flow**:
```
Transform unit (input_from=None): wide_l{N}.parquet → execute → wide_l{N+1}.parquet
Transform unit (input_from="recent"): snapshots/recent_l{N}.parquet → execute → snapshots/recent_l{N+1}.parquet
Filter unit: wide_l{N}.parquet → execute → snapshots/{name}_l0.parquet
Terminal unit: reads parquet → produces artifacts/ only (no data checkpoint)
```

**Re-evaluate**: 如果 Parquet I/O 在 100K+ 行数据上超过 2s，考虑添加压缩级别配置或 lazy checkpoint 策略。

---

## D56 — Single-unit rerun input via directory-scan checkpoint resolution

**Date**: 2026-07-12
**Milestone**: M4 (Single-unit rerun API)

**Decision**: 使用目录扫描 (`resolve_rerun_input`) 来确定 rerun unit 的输入 checkpoint 路径，而非尝试重建 `execute_dag` 运行时的 in-memory 状态（`main_level`/`snapshot_levels`）。

**Rationale**:
- `execute_dag` 的 `main_level` / `snapshot_levels` 是运行时局部变量，不在 state 中持久化。session 重启后这些信息丢失
- 目录扫描是幂等的 — 只需检查 `{output_dir}/checkpoints/` 下存在哪些 Parquet 文件，按 level 排序取最新的
- 每个 unit 的 branch（main wide table 或 snapshot）可以从 `unit.input_from` 字段确定，不需要运行时上下文
- Fallback to original data file 当 checkpoint 不存在时，保证首次 rerun 也能工作

**Impact**:
- `resolve_rerun_input(unit, parent_output_dir)` 返回 `str | None`（None = 使用原始数据文件）
- 依赖文件系统作为 checkpoint 状态的 source of truth，不引入额外持久化
- Level 计算：扫描 `wide_l*.parquet` 或 `{snapshot}_l*.parquet`，取 `max(level)`

**Re-evaluate**: 当 checkpoint 数量超过 10 时，考虑缓存 level 信息到 state 以减少目录扫描开销。

---

## D57 — Stale marking via unit result metadata

**Date**: 2026-07-12
**Milestone**: M4 (Single-unit rerun API)

**Decision**: 在 `unit_results` 的每个 entry 中添加 `stale: bool` 字段来标记下游过期状态，而非引入独立的 stale-tracking 数据结构。

**Rationale**:
- 最小侵入 — `unit_results` 已经是 state 中关于执行结果的 single source of truth
- Frontend 可以直接从现有的 `GET /execution/results` 响应中读取 `stale` 字段，无需额外 API 调用
- `stale` 标记是 transient 的 — 下一次 full rerun 后自然清除
- 不需要额外的持久化或清理逻辑

**Impact**:
- `UnitResultResponse` schema 新增 `stale: bool = False`
- Rerun 端点返回 `RerunUnitResponse.stale_units: list[int]` 明确告知 frontend 哪些 units 过期
- Cascade rerun 不会产生 stale 标记（所有下游已被重新执行）
- 非 cascade rerun 后，transitive dependents 被标记为 `stale: true`

**Re-evaluate**: 如果 frontend 需要在 session 重启后仍然看到 stale 状态，可能需要将 stale 信息持久化到 state 中（当前实现已持久化到 `analysis_result`，session 重启后仍存在）。

---

## D58 — Synchronous rerun for single units

**Date**: 2026-07-12
**Milestone**: M4 (Single-unit rerun API)

**Decision**: `POST /execution/units/{id}/rerun` 同步执行并直接返回结果，而非像 `POST /execution/run` 那样使用 `asyncio.create_task` 后台执行 + 轮询 status。

**Rationale**:
- Single-unit rerun 执行时间远短于完整 DAG run：一个 template 函数调用（<1s）或一个 LLM→sandbox 调用（<30s），用户在 API 调用时等待是可接受的
- 同步返回简化了 frontend 集成：一次 HTTP 调用得到完整结果，无需 status-polling 循环
- 避免了 "running" 状态管理复杂度 — 单个 unit rerun 的中间状态信息量很低，不值得维护
- Cascade rerun 仍然同步：units 按拓扑顺序串行执行（≤5 units，总时长可控）

**Impact**:
- 端点不需要 `asyncio.create_task`，也不需要 `GET /execution/status` 支持 "rerun in progress" 状态
- HTTP 响应直接包含 unit 执行结果 + stale_units 列表
- Timeout 风险：单个 LLM-mode unit 最多 120s（sandbox timeout），对于 HTTP 请求较长但可接受

**Re-evaluate**: 如果 cascade rerun 扩展到 10+ units 且总时长超过 60s，考虑改为后台任务 + WebSocket 推送进度。

---

## D59 — Transform/Filter 使用进程内临时模板，Terminal 保留 subprocess

**Date**: 2026-07-13
**Milestone**: M6 (In-Process LLM)

**Decision**: LLM-mode Transform/Filter 不再生成完整脚本或经过 CSV round-trip。
LLM 生成符合 `TemplateFunc` 契约的 `_unit(df, input_columns, params)`，经静态检查和
受限 namespace 编译后，与永久模板共用结果构建、契约校验和 checkpoint 路径。
Terminal 仍生成完整脚本并在带超时的 subprocess 中运行。

**Rationale**:
- Transform/Filter 的行列契约严格，完整脚本的 CLI、文件读写和 JSON stdout 都是重复样板
- 两种来源共用函数契约后，重试与 checkpoint 行为一致
- Terminal 需要绘图和开放式 artifact 生成，继续保留进程边界更合适

**Boundary**: 进程内路径只面向可信的本地单用户场景。受限 builtins 和 static guard
不是 OS sandbox，也没有硬 CPU/内存隔离。外部托管前必须重新评估 worker isolation。

---

## D60 — SessionStore 采用 JSON durable state + 瞬态值剥离

**Date**: 2026-07-31
**Milestone**: M6 closure

**Decision**: `SessionStore` 保留内存缓存，同时在每次 create/update 后原子写入
`data/sessions/{session_id}/state.json`。进程重启后，`get()` 首次访问时从磁盘懒加载。

**Serialization contract**:
- `analysis_result` 中以 `_` 开头的 key 是 executor-only，不持久化
- `_result_df` 只用于当前执行写 Parquet checkpoint，不进入 JSON
- source code、真实 model name、insights、chart references、Plan、pins、report 均持久化
- `persisted_at` 记录最近一次成功写盘时间

**Rationale**: 让完成的分析成为可重新打开的 workspace，同时避免把 DataFrame
复制进 JSON。Parquet 和 artifact 文件仍是大数据/二进制结果的 source of truth。

---

## D61 — API execution 使用稳定 session output root

**Date**: 2026-07-31
**Milestone**: M6 closure

**Decision**: API analysis 输出固定在 `data/output/{session_id}/analysis/`，不再使用
进程临时目录。图表 API 只返回并接受相对于 `data/output/{session_id}` 的路径。

**Rationale**:
- JSON state 持久化只有在 artifact 路径跨进程有效时才有意义
- 相对引用使 workspace 可以在重启后加载，同时避免向前端泄露本机绝对路径
- chart serving 继续校验 resolved path 位于 session output root 内
