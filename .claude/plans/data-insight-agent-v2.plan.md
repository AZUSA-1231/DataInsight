# Plan: DataInsight V2 — Agent Architecture Refactor

**Source PRD**: [.claude/prds/data-insight-agent.prd.md](../prds/data-insight-agent.prd.md)
**Selected Milestone**: V2 — First Major Update (post-MVP)
**Complexity**: Large

## Summary

对 DataInsight MVP 的 agent 设计进行第一次重大重构。核心目标：提升 pipeline 成功率和输出质量，同时保持端到端一键出报告的体验。

六项 agent 设计改动 + 两项优化 + Pydantic 类型系统升级。

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Naming | [src/agent/state.py](../../src/agent/state.py) | `snake_case` fields; nodes 命名 `xxx_node`; `AgentState` PascalCase |
| Immutability | [src/agent/graph.py](../../src/agent/graph.py) | Pydantic: `state.model_copy(update={...})` |
| Error signaling | [src/agent/nodes/data_track.py](../../src/agent/nodes/data_track.py#L74-L75) | State field `error: Optional[str]`, never raise from node |
| Logging | [src/agent/nodes/business_track.py](../../src/agent/nodes/business_track.py#L66) | `logger.info("NodeName: message (%d chars)", len(x))` |
| LLM calling | [src/agent/nodes/data_track.py](../../src/agent/nodes/data_track.py#L84-L87) | `get_llm(temperature=0).invoke(prompt).content` |
| Graph edges | [src/agent/graph.py](../../src/agent/graph.py#L39-L62) | `graph.add_node()` + `graph.add_edge()` + `add_conditional_edges()` |
| Tests | [tests/test_data_track.py](../../tests/test_data_track.py) | pytest + `@pytest.mark.unit` / `@pytest.mark.integration`; AAA pattern; mock LLM |

## AgentState V2 Design

### SubModels

```python
class ColumnProfile(BaseModel):
    name: str
    dtype: str
    null_count: int
    null_pct: float
    unique_count: int
    unique_pct: float

class DataProfile(BaseModel):
    file_path: str
    shape: tuple[int, int]
    columns: list[ColumnProfile]
    statistics: dict[str, dict[str, Any]]
    head_sample: list[dict[str, Any]]
    encoding: str

class AnalysisIntent(BaseModel):
    core_question: str
    target_variable: str | None = None
    analysis_type: str
    dimensions: list[str]
    comparison_baseline: str | None = None

class ExecutionPlan(BaseModel):
    feasibility_map: list[dict[str, Any]]
    model_selections: list[dict[str, Any]]
    preprocessing_steps: list[dict[str, Any]]
    analysis_steps: list[dict[str, Any]]
    alignment_notes: str
```

### AgentState

| Field | Type | Source Node | Description |
|-------|------|-------------|-------------|
| `file_path` | `str` | CLI | 输入文件路径 |
| `user_requirement` | `str` | CLI | 用户自然语言需求 |
| `data_profile` | `DataProfile \| None` | data_track | 结构化数据画像（inspection JSON） |
| `cleaning_insights` | `str \| None` | data_track | LLM 精简清洗建议 |
| `analysis_intent` | `AnalysisIntent \| None` | business_track | 结构化分析意图 |
| `execution_plan` | `ExecutionPlan \| None` | decision_match | Planner 输出 |
| `preprocessing_result` | `dict[str, Any] \| None` | preprocessing | 清洗结果 |
| `analysis_result` | `dict[str, Any] \| None` | analysis | 分析结果 |
| `final_report` | `str \| None` | report_gen | 最终报告 |
| `error` | `str \| None` | any | 错误信息 |
| `feedback` | `str \| None` | CLI | 用户反馈（消费后清除） |

## Graph V2 Flow

```
                    START
                   /      \
                  v        v
          data_track    business_track
                  \      /
                   v    v
              decision_match (Planner)
                   |
                   v
              preprocessing
                /      \
       (success)    (error → ReAct × 3)
              /          \
             v            v
         analysis      report_gen (partial)
           /   \
   (success)  (error → ReAct × 3)
         /       \
        v         v
   report_gen   report_gen (partial)
        |
        v
       END
        ^
        |___ feedback → decision_match
```

变化点：
- `START → [data_track, business_track]` 并行（D11 升级）
- `execution` 拆为 `preprocessing → analysis` 两个独立节点
- 每个阶段有自己的 ReAct 回环（各自最多 3 次重试）
- report_gen 可以从 preprocessing 失败或 analysis 失败直接产出部分报告

## Files to Change

| File | Action | Why |
|------|--------|------|
| `src/agent/state.py` | REWRITE | TypedDict → Pydantic BaseModel，新增 SubModels |
| `src/agent/graph.py` | REWRITE | 并行 START、preprocessing/analysis 两个节点、条件边重组 |
| `src/agent/nodes/data_track.py` | REWRITE | 新增 `data_profile` 解析；LLM 只产 `cleaning_insights` |
| `src/agent/nodes/business_track.py` | REWRITE | 意图理解器，产出结构化 `AnalysisIntent` |
| `src/agent/nodes/decision_match.py` | REWRITE | Planner：指标映射 + 模型选型 + 执行计划 |
| `src/agent/nodes/execution.py` | DELETE | 拆为 preprocessing + analysis |
| `src/agent/nodes/preprocessing.py` | CREATE | 数据预处理节点 |
| `src/agent/nodes/analysis.py` | CREATE | 数据分析节点 |
| `src/agent/nodes/report_gen.py` | REWRITE | 从结构化数据组装报告 |
| `src/agent/llm.py` | UPDATE | 兼容新 state |
| `src/__main__.py` | UPDATE | 适配新 AgentState 构造 + 中间产物保存 |
| `src/agent/nodes/__init__.py` | UPDATE | 导出新节点 |
| `tests/conftest.py` | UPDATE | 适配 Pydantic fixture |
| `tests/test_*.py` (7 files) | UPDATE | 适配新 state 和新节点 |

## Implementation Phases

### Phase 0: Pydantic 迁移（基础，无逻辑变化）

- **Action**: 重写 `state.py` 为 Pydantic BaseModel；所有节点改 `{**state}` → `state.model_copy(update={...})`；`state.get("k")` → `state.k`（Optional 字段维持 None 语义）；测试全改
- **Mirror**: 当前 [state.py](../../src/agent/state.py) 字段结构，仅换容器
- **Validate**: `mypy src/` strict 通过；`pytest -v` 52 个测试全部通过
- **Complexity**: Medium

### Phase 1: 并行 Track + Data Track 精简

- **Action**:
  1. `graph.py`: `START → data_track` + `START → business_track`，两者都连向 `decision_match`
  2. `data_track.py`: inspection JSON → `DataProfile`；LLM prompt 改为只输出清洗建议
  3. `state.py`: 新增 `data_profile: DataProfile | None` + `cleaning_insights: str | None`；移除 `data_report`
- **Validate**: `pytest tests/test_data_track.py -v`；并行执行正确

### Phase 2: Business Track 收窄 → 意图理解器

- **Action**:
  1. `business_track.py`: prompt 重写，要求输出结构化 JSON（`AnalysisIntent` schema）
  2. `state.py`: 新增 `analysis_intent: AnalysisIntent | None`；移除 `business_plan`
  3. prompt 约束：不假设数据列名、不设计超出需求的指标体系
- **Validate**: 结构化 JSON 解析成功；解析失败时写入 `state.error` 不崩溃

### Phase 3: Decision Match → Planner

- **Action**:
  1. prompt 完全重写：输入 `DataProfile` + `AnalysisIntent` + `cleaning_insights`
  2. 强制输出：指标可行性映射、模型选型（含推理链）、预处理步骤、分析步骤
  3. 保留 `alignment_notes`（数据与业务对齐备忘）
  4. 保留 feedback 消费模式
- **Validate**: planner 输出可被后续节点直接消费；列名不匹配时输出 `[不可实现]` 标记

### Phase 4: Execution 分阶段 — Preprocessing

- **Action**:
  1. 新建 `preprocessing.py`：接收 `ExecutionPlan.preprocessing_steps`，生成数据清洗代码
  2. 执行成功 → `state.preprocessing_result` 固化
  3. 执行失败 → ReAct 重试（max 3），失败后路由到 report_gen（部分报告）
- **Mirror**: 当前 [execution.py](../../src/agent/nodes/execution.py) 的 code gen + sandbox + ReAct 模式
- **Validate**: `pytest tests/test_preprocessing.py -v`（新建）

### Phase 5: Execution 分阶段 — Analysis

- **Action**:
  1. 新建 `analysis.py`：接收 `ExecutionPlan.analysis_steps`，已知 preprocessed data context
  2. 生成的代码可引用预处理后的真实列名
  3. 执行成功 → `state.analysis_result`；失败 → ReAct → report_gen
- **Validate**: `pytest tests/test_analysis.py -v`（新建）

### Phase 6: Report Gen 重构

- **Action**:
  1. prompt 重写：只输入对最终报告有用的结构化数据
  2. 输出干净的 Markdown，不缝合中间产物
  3. 支持部分报告；保留 feedback 条件边
- **Validate**: `pytest tests/test_report_gen.py -v`

## Dependencies

```
Phase 0 (Pydantic) ──→ Phase 1 ──→ Phase 2 ──→ Phase 3 ──→ Phase 4 ──→ Phase 5 ──→ Phase 6
```

Phase 1+2 理论可并行但共享 state 变更，建议串行确保测试稳定。

## Validation

```bash
# 每个 Phase 完成后：
ruff check . && ruff format --check .
mypy src/
pytest -v

# Phase 6 完成后端到端验证：
python -m src data.csv "分析问题" -s -v
```

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Pydantic 迁移遗漏导致 graph failure | Medium | Phase 0 单独验证，所有测试在 Phase 0 后必须全绿 |
| 并行 Track 后 decision_match 等待逻辑出错 | Low | LangGraph 原生支持并行 fan-in |
| LLM 不支持结构化 JSON 输出 | Medium | prompt 中提供 JSON schema；解析失败走部分报告路径 |
| AgentState 字段膨胀（9 → ~14） | Low | Pydantic Optional 默认 None |
| 测试维护成本（52 → 60+） | Medium | 每个 Phase 增量更新测试 |

## Acceptance

- [x] Phase 0: Pydantic 迁移完成，52/52 测试通过
- [x] Phase 1: 并行 Track + Data Track 精简，54/54 测试通过
- [ ] Phase 2: Business Track 收窄为意图理解器
- [ ] Phase 3: Decision Match → Planner（模型选型 + 完整推理链）
- [ ] Phase 4: Preprocessing 节点（含 ReAct）
- [ ] Phase 5: Analysis 节点（含 ReAct）
- [ ] Phase 6: Report Gen 重构
- [ ] 端到端测试：`python -m src data.csv "问题" -s -v` 产出干净报告
- [ ] ruff check + mypy src/ + pytest -v 全部绿灯

---
*Plan for DataInsight V2 — First Major Update. Phase 0 starts with Pydantic migration.*
