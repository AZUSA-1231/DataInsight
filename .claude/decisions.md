# Architecture Decision Log — DataInsight (Cycle 3)

Decisions made during Cycle 3 development. Cycle 2 decisions (D39-D41) are
archived at [.claude/archive/cycle-2/decisions.md](.claude/archive/cycle-2/decisions.md).

---

## D42 — data_track 砍掉 cleaning_insights LLM 调用

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: data_track 不再调用 LLM 生成清洗建议（`_build_cleaning_insights_prompt` + `get_llm().invoke()`）。节点变为纯确定性：inspection script → parse DataProfile → 提取 `unified_columns` → 返回。

**Rationale**:
- BI 场景下数据假定相对干净，不需要 LLM 预判清洗策略
- 清洗策略的决策应由 planner 根据 data_profile 直接做出，而非在 data_track 中预消化
- 减少一次 LLM 调用，降低延迟和成本
- 未来 M2 多表场景时，data_track 可能需要 LLM 辅助理解表关系并生成 merge 代码——但那是对"表关系"的理解，不是"数据清洗建议"，职责不同

**Risk**: report_gen 的 Section 1（数据画像与清洗）之前依赖 cleaning_insights 做数据质量总结。改为直接使用 data_profile_json，由 report_gen 的 LLM 自行总结。信息源一致（data_profile），只是总结者从 data_track 的 LLM 换成了 report_gen 的 LLM。

---

## D43 — business_track 降级为可选路径

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: business_track 不再是 planner 的强制上游。graph 在 data_track 之后通过条件边 `_should_skip_business_track` 决定是否运行 business_track：
- `state.draft_plan is not None` → 跳过 business_track，直接进入 planner（审核模式）
- `state.draft_plan is None` → 运行 business_track，产出 Intent，然后 planner（生成模式）

**Rationale**:
- 用户已有明确分析意图时（通过 draft_plan 表达），不需要 business_track 再翻译一遍
- business_track 的翻译对自然语言有价值，但对已结构化的 Plan 是冗余的（且会丢失多 unit 的丰富度，因为 Intent 的 core_question 是一个单一字符串）
- 保持 business_track 作为"快速开始"入口——用户一句话 → Intent → Plan，这条路径不受影响

**Risk**: 审核模式下 planner 缺少 business_track 提供的 `analysis_intent`（dimensions, suggestions, caution_notes 等结构化上下文），可能影响审核质量。缓解：审核模式 prompt 中可选地传入 analysis_intent（如果存在）；planner 可从 draft_plan 自身的 purpose + related_fields + data_profile 推导足够上下文。

---

## D44 — Planner 双模式：生成 + 审核

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: `planner_node` 支持两种模式，由 `state.draft_plan` 是否为空决定：
- **生成模式**（draft_plan 为空）：`_build_planner_prompt` — 从 Intent + unified_columns + data_profile 生成 Plan
- **审核模式**（draft_plan 非空）：`_build_planner_review_prompt` — 校验 draft_plan 的 related_fields、purpose/model 逻辑、补漏纠偏，输出修正后的 Plan
- **反馈模式**（feedback 非空）：`_build_planner_prompt_with_feedback` — 保持现有逻辑，增加 unified_columns 参数

**Rationale**:
- planner 是唯一的 Plan 产出者——这是架构的"唯一真相源"原则
- 生成模式和审核模式的输入不同（Intent vs draft_plan），但输出规范一致（Plan with related_fields）
- 三个模式共享同一套 JSON schema 和 parse 逻辑，减少分支
- 优先级：feedback > draft_plan > 正常生成。feedback 是用户对上一次报告的修正意见；draft_plan 是用户主动组装的草稿；正常生成是自动模式

**Risk**: 审核模式下 planner 可能过度修改用户的 draft_plan（比如删掉用户有意添加的 unit）。缓解：prompt 明确指示"Preserve the user's original structure as much as possible — only correct actual errors"。

---

## D45 — related_fields 替代独立的 user_specified_columns

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: 不新增 `user_specified_columns` 字段。用户对列的指定通过 `PlanUnit.related_fields` 承载：
- 生成模式：planner 自动为每个 unit 分配 `related_fields`
- 审核模式：用户在 draft_plan 中直接指定每个 unit 的 `related_fields`，planner 审核修正
- 用户关心的所有列 = 所有 unit 的 `related_fields` 的并集

**Rationale**:
- `user_specified_columns` 是全局概念（"用户关心哪些列"），但列的意义是 per-unit 的（"销量在 unit_1 是分析目标，在 unit_2 是分组维度"）
- `related_fields` 能承载更丰富的语义：同一个列在不同 unit 中可以扮演不同角色
- 避免 state 中两个字段的同步问题（user_specified_columns 和 related_fields 的并集之间的关系）
- 未来前端场景：用户将字段连到特定 unit，而不是标记"我关心这些字段"

---

## D46 — draft_plan 作为新增 AgentState 字段

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: 新增 `draft_plan: Plan | None = None` 字段承载用户组装的草稿 Plan。与 `plan: Plan | None` 的关系：
- `draft_plan` = 用户输入（untrusted），来自前端或 CLI
- `plan` = planner 输出（validated），经过审核或生成
- `draft_plan` 在 planner 处理后**不清空**，保留供前端/CLI 参考对比
- graph 路由仅依赖 `draft_plan is not None` 判断

**Rationale**:
- 复用 `plan` 字段承载 draft 会造成语义混乱——同一个字段既是输入又是输出
- `draft_plan` 与 `plan` 的类型相同（Plan），减少新 model 定义
- 保留 draft_plan 不清空，调用方可以对比 draft vs final plan 的差异
- `plan` 保持为 planner 的唯一输出，下游节点（preprocessing/analysis/report_gen）只读 `state.plan`

---

## D47 — Graph 去并行化：data_track 串行先行

**Date**: 2026-07-05
**Milestone**: M1

**Decision**: Cycle 2 的 graph 结构是 `START → data_track ∥ business_track → planner`（并行 fan-out）。Cycle 3 改为串行：`START → data_track → [条件] → business_track → planner`。data_track 总是先运行，business_track 按条件跳过。

**Rationale**:
- data_track 的产出 `unified_columns` 是 planner 的必需输入。在旧架构中 data_track 和 business_track 并行运行，planner 直接消费两者的产出——但 planner 并不依赖 business_track 的产出做字段校验
- 审核模式下 business_track 完全跳过，graph 需要支持这条路
- 串行化 data_track → business_track 对总延迟影响很小（data_track 只是 subprocess 跑 inspection script，几秒内完成）
- 并行保留仅当 data_track 和 business_track 互不依赖时才合理——但 business_track 不需要 data_track 的产出，条件路由打破了这一假设

**Risk**: 总延迟增加 ~2-3 秒（data_track inspection 时间）。考虑到 inspection 通常在 1-2 秒内完成（确定性脚本，无 LLM），影响可忽略。

---

## D48 — PlanUnit.related_fields 的默认值和空值语义

**Date**: 2026-07-05
**Milestone**: M1 (implementation)

**Decision**: `related_fields` 默认值为 `[]`（空列表），空列表表示"未指定"（由 planner/executor 根据 purpose 自行推断）。这与 `None` 不同——`None` 表示字段未初始化（向后兼容旧 Plan），`[]` 明确表示"审查过了，没有特别需要关注的列"。

**Rationale**:
- `[]` 是安全的默认值——PlanUnit 构造时不需要强制填充
- 生成模式下 planner 会给每个 unit 填充具体字段名
- 审核模式下用户可能有意留空某些 unit（"这个分析不需要特定列"）
- CLI 的 `_display_plan` 对空列表显示 `(未指定)` 而非静默跳过

---

## D49 — planner 三模式优先级：feedback > draft_plan > generate

**Date**: 2026-07-05
**Milestone**: M1 (implementation)

**Decision**: `planner_node` 内部按优先级检查三个条件：
1. `state.feedback is not None` → 反馈模式（修订现有 Plan）
2. `state.draft_plan is not None` → 审核模式（审计用户草稿）
3. 否则 → 生成模式（从 analysis_intent 生成）

当 feedback 和 draft_plan 同时存在时，feedback 优先（用户在审核完 draft 后又给了反馈），但这种情况在正常流程中不会发生（feedback 迭代时 draft_plan 已在上一轮被消费）。

**Rationale**:
- 三个路径共享同一 JSON schema 和 parse 逻辑，减少分支复杂度
- 优先级编码在 if/elif/else 中，一眼可见
- feedback 路径保持与原架构一致的行为（显式传 `previous_plan_json`）

---

## D50 — cleaning_insights 字段保留但不再填充

**Date**: 2026-07-05
**Milestone**: M1 (implementation)

**Decision**: `AgentState.cleaning_insights: str | None = None` 字段不从 state.py 中移除。data_track 不再填充它，report_gen 不再读取它。向后兼容：任何外部调用方仍可读取该字段（总是 None），不会崩溃。

**Rationale**:
- 移除 state 字段会破坏所有 AgentState 构造的向后兼容性（即使传了 `cleaning_insights="..."` 也会 TypeError）
- 保留字段为零成本——不影响运行时行为，不影响新功能
- 如果未来需要在 report_gen 中展示清洗策略的"前 vs 后"对比，这个字段可以复活
- 符合 PRD 中 "cleaning_insights field kept as None-default for backward compat" 的声明


---

## D51 — business_track 重构为 workspace-aware Intent 提取器

**Date**: 2026-07-05
**Milestone**: M2

**Decision**: business_track 不再是 "跳过/不跳过" 的二元路由节点，而是始终运行的 context provider。其行为由 workspace 状态决定：

- **workspace 为空**（`state.plan is None`）：纯 NL → Intent（现有逻辑，翻译器模式）
- **workspace 非空**（`state.plan is not None`）：对话 + workspace Plan → **Contextualized Intent**（理解对话在修改哪个 unit/字段）

business_track 的输入包括 `unified_columns`（列名层，来自 data_track），因为 workspace 中的 units 已包含 `related_fields`——用户将列连线到 unit 时，实际已将心智模型投影到真实列名上。business_track 理解"列名"就够了，不需要理解"列统计"。

**数据认知分层**：

```
data_track  ─┬→ unified_columns (表层: 列名) ──→ business_track + planner
             └→ data_profile     (深层: 统计) ──→ planner only
```

| 层 | 消费者 | 用途 |
|----|--------|------|
| `unified_columns` | business_track, planner | 列名校验、字段存在性检查 |
| `data_profile` | planner only | 数据质量感知、方法选择、统计推理 |

**Rationale**:
- 当 workspace 有内容时，对话的意义是**相对于 workspace 的**。"把地区分析拆成华东和华南"——脱离 workspace 无法理解"地区分析"指哪个 unit
- business_track 和 planner 的认知任务不同：前者理解用户想干什么（需要列名 + workspace），后者决定如何在数据上执行（需要全貌）
- 合并为一个超级 planner 会让 prompt 臃肿——两个认知任务所需的 context window 不同，分开保持专注度
- 移除条件路由 `_should_skip_business_track`——business_track 始终运行，只是行为随 workspace 状态变化

**Graph 变化**：

```
旧：START → data_track → [条件] → (planner | business_track → planner)
新：START → data_track → business_track → planner
```

不再需要 `draft_plan` 字段。workspace 中只有一个 `plan`（可为 None），不管它是用户拖拽的、系统生成的、还是用户修改过的。`plan` 的来源不重要——business_track 和 planner 只看到"当前 workspace 里有什么"。

**Planner 简化**：
- 移除三模式 if/elif/else 分支
- 输入始终是 `(workspace_plan, contextualized_intent, data_profile, unified_columns)`
- LLM 自行判断：workspace 空 → 生成；workspace 有 + 用户措辞轻微 → 微调；workspace 有 + 用户说推倒 → 无视 workspace 重新生成

**Risk**: business_track 现在消费 workspace，但 workspace 可能包含"用户拖了列但还没写 purpose"的不完整 unit。缓解：prompt 中对不完整 unit 标记为 `partial`，business_track 仅基于完整信息提取意图，不完整部分留给 planner 补全。
