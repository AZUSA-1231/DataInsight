# Architecture Decision Log — DataInsight (Cycle 4)

Decisions made during Cycle 4 development. Cycle 3 decisions are archived at
[.claude/archive/cycle-3/decisions.md](.claude/archive/cycle-3/decisions.md).

---

## D51 — input_columns 严格匹配策略

**Date**: 2026-07-08
**Milestone**: M2 (Enhanced PlanUnit)

**Decision**: 执行前校验 `input_columns` 时采用**严格字符串匹配**（大小写敏感、空格敏感）。不引入模糊匹配（case-insensitive、underscore-vs-space normalization）。

**Rationale**:
- PlanUnit 的 `input_columns` 由 Planner 填写，Planner 已有明确的列名列表（来自 data_track 的 `unified_columns`），没有理由产出模糊列名
- 模糊匹配会掩盖 Planner 的 prompt 问题——如果 Planner 产出了错误的列名，应该修复 prompt 而非让 executor 容错
- 如果 fuzzy match 命中但实际是无关列（e.g. "sales" vs "Sales" vs "sales_amount"），会静默产生错误结果
- 保持执行引擎简单可预测——严格匹配的失败信息明确（"Column 'foo' not found. Available: ['bar', 'baz']"），用户或 Planner 可定位原因

**Re-evaluate**: 如果 M4 真实数据跑过后发现 false negative 比例过高（>20% 的失败是因为列名微小差异），则改成 case-insensitive + strip whitespace。

---

## D52 — 移除 preprocessing，不做替代方案

**Date**: 2026-07-08
**Milestone**: M1 (Clean Slate)

**Decision**: 直接删除 preprocessing 节点及整个 cleaning 管道，不在当前 cycle 提供替代方案。data_track 之后数据假定为干净可用，列名不修改、数据类型由 analysis unit 自行处理。

**Rationale**:
- 当前 preprocessing 的 one-hot encoding / feature engineering 破坏了原始列名，使得 Planner→analysis 的列名链路断裂
- Cleaning 的职责与 analysis unit 的职责重叠——每个 analysis unit 本来就有 try/except + 类型转换能力
- data_track 已经提供了完整的 data profile（null 率、dtype、样本值），Planner 可在 cautious notes 中标注数据问题，交给 analysis unit 自行处理
- 后续版本会重新审视数据质量层，但会是 data_track 的能力扩展（e.g. 列类型自动推断、编码检测增强），而非一个独立的 cleaning stage

**Risk**: 脏数据（大量 null、混合类型列）可能导致 analysis unit 失败率上升。缓解：Planner 的 cautious 机制 + analysis unit 的 try/except + ReAct retry 已经提供了足够的容错。如有具体失败案例，再针对性增强 data_track。

---

## D53 — DAG 执行模型：分层并行

**Date**: 2026-07-08
**Milestone**: M3 (DAG Executor)

**Decision**: DAG 执行采用**拓扑分层并行**模型：Kahn 算法排序 → 按层级分组 → 同层 units 用 ThreadPoolExecutor 并行（当前 max_workers=3），每层完成后下一层才开始。

不采用：
- **纯串行**：浪费独立 units 的并行能力
- **全并行 + 轮询依赖**：复杂且不可预测，依赖就绪检测逻辑脆弱
- **多进程 (ProcessPoolExecutor)**：Python GIL 对 pandas/numpy 的影响有限（它们 release GIL），多进程带来序列化开销

**Rationale**:
- 分层并行是分析 DAG 的自然模型——独立业务分析（e.g. 按地区 + 按时间）天然可并行，聚合型分析（e.g. 聚类后按 cluster 分析）天然串行
- 每层边界清晰，便于日志和调试：`Level 0: [U1, U3] completed. Level 1: [U2] starting...`
- max_workers=3 是当前经验值（3 个 LLM 并行调用的 API rate limit 边际），后续可环境变量配置

**Data passing**: 每个 unit 产出 `unit_{id}/output.csv`（原始列 + 输出新列）。Downstream unit 读取其最后一个 `depends_on` 上游的 output.csv。多个上游时，合并所有上游的新列。

---
