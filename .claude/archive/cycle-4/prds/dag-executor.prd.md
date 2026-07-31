# DAG Execution Engine — Remove Preprocessing, Enable Dependencies

## Problem

DataInsight 的沙盒执行层存在三个互锁缺陷：(1) Planner 生成带依赖链的分析单元，但 executor 用 `ThreadPoolExecutor` 全并行执行，导致 upstream unit 产出的列（如 Cluster）对 downstream unit 不可见；(2) 所有 unit 共享一条数据链路，一次失败全部重来，无法单独重跑，这对可能生成上千行 Python 代码的长链路分析来说不可接受；(3) preprocessing 阶段过度清洗（one-hot encoding 等特征工程），破坏了原始列名，使得 Planner 指定的列在下游找不到。

## Evidence

真实执行日志（2026-07-08）：

```
Analysis unit [2]: FAILED — Missing required columns: ['Cluster']
  → Unit 1 产出 Cluster 列，但 Unit 2 并行读取原始文件，数据断流

Analysis unit [1]: FAILED — Missing required columns: ['Category', 'Sub-Category', 'Sales']
  → preprocessing one-hot encoding 将 Category 变成 Category_Furniture_proportion

Preprocessing: static guard rejected code: Banned imports: os
  → import os 被 ban，但 os.path.join 是合法文件操作
```

## Users

- **Primary**: 我自己（YANdz），作为 DataInsight 的使用者和开发者，在上传 CSV 并描述分析需求后，期望一次生成可执行的 Plan 并跑出结果
- **Not for**: 外部用户（目前）、不涉及沙盒执行的纯浏览场景

## Hypothesis

We believe **DAG 拓扑执行 + 移除 preprocessing + 中间数据文件传递 + PlanUnit 增强（input_columns/output_columns）** will **让 DataInsight 沙盒执行真正可用于多步骤依赖分析** for **上传数据后要求多维度分析的场景**。
We'll know we're right when **一次提交 3 个 units 的 Plan（至少 1 条 depends_on 链），3 个 units 均成功执行，且 downstream unit 能正确读取 upstream unit 产出的新列**。

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| DAG Plan 端到端执行成功率 | >= 2/3 units 成功 | 真实 CSV 运行 3 次 |
| 中间列传递正确性 | downstream unit 不报 Missing column | 检查执行日志 |
| 独立 unit 不受失败 unit 影响 | 无依赖的 unit 在旁路失败时继续成功 | 构造含失败 unit 的 Plan |
| `import os` false positive | 0 | static_guard tests |

## Scope

**MVP** — 4 个里程碑，按顺序交付：

1. **M1: Clean Slate** — 删除 preprocessing 节点，解禁 `import os`，清理 state/graph 模型
2. **M2: Enhanced PlanUnit** — PlanUnit 增加 `input_columns`/`output_columns`，Planner prompt 更新
3. **M3: DAG Executor** — 拓扑排序 + 分层并行执行 + 中间数据文件传递 + 列存在性校验
4. **M4: Test & Validate** — 更新全部测试，真实数据端到端验证

**Out of scope**
- 单 unit re-run API（`POST /execution/units/{id}/rerun`）— 下一个 PRD，因为依赖 M3 完成
- 前端 workspace 显示 DAG 依赖图 — 下一个 PRD
- preprocessing 的替代方案（data_track 后续增强）— 后续版本
- 跨 unit 的变量/对象传递（目前只传文件 + 列）— 后续版本

## Delivery Milestones

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | Clean Slate | preprocessing 节点完全移除，`import os` 不再被 ban，Plan 模型无 cleaning 字段 | complete | [m1-clean-slate.plan.md](../plans/m1-clean-slate.plan.md) |
| 2 | Enhanced PlanUnit | PlanUnit 增加 input_columns/output_columns，Planner 产出包含新字段的 Plan JSON | complete | [m2-enhanced-planunit.plan.md](../plans/m2-enhanced-planunit.plan.md) |
| 3 | DAG Executor | analysis_node 拓扑排序执行，中间数据通过 output.csv 传递，列存在性执行前校验 | complete | [m3-dag-executor.plan.md](../plans/m3-dag-executor.plan.md) |
| 4 | Test & Validate | 全部旧测试更新通过，新行为有覆盖，真实数据跑通 | complete | [m4-test-and-validate.plan.md](../plans/m4-test-and-validate.plan.md) |

## Open Questions

- [ ] Planner 生成的 `depends_on` 准确率多高？— M4 用真实数据验证
- [ ] `input_columns` 校验是否要支持模糊匹配（大小写、下划线 vs 空格）？— 先严格匹配，M4 看 false negative 频率再决定

## Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Planner 生成循环依赖 | Low | 执行卡死 | 拓扑排序检测到环 → 返回 error，不执行 |
| input_columns 校验过严导致 false negative | Medium | 正常 unit 被误判失败 | 先严格匹配，收集实际失败案例再决定是否 fuzzy |
| 中间 CSV 文件数量膨胀 | Low | 磁盘占用 | 每个 unit 只保留最终 output.csv，临时文件用完后清理 |
| 去掉 preprocessing 后数据质量问题暴露 | Medium | analysis unit 更易失败 | data_track 已提供完整 data profile，Planner 在 cautious 中标记问题 |

---
*Status: DRAFT — requirements only. Implementation planning pending via /plan.*
