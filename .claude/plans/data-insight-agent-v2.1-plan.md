# Plan: DataInsight V2.1 — Post-V2 Test Hardening

**Depends on**: [data-insight-agent-v2.plan.md](data-insight-agent-v2.plan.md) Phase 6 全部完成
**Status**: 已完成 (2026-07-01)
**Complexity**: Medium

## Motivation

Phase 3-4 实施过程中暴露了 4 类可重现的测试脆弱性问题。这些问题对 Phase 5-6 的
src 开发**不构成破坏性影响**（新文件不依赖已有脆弱 helper），但会持续增加后续维护
摩擦。本 Plan 在 V2 全阶段开发完成后，集中清偿这些测试债务。

## Lessons Learned (Phase 3-4)

### L1: Python 空集合 truthiness 陷阱

**现象**：`_make_plan(preprocessing_steps=[])` 调用 `[] or [default]`，
空列表是 falsy，所以始终走默认值。导致 "no-steps skip" 测试实际走了 LLM 生成路径。

**根因**：
```python
# BAD: [] is falsy → default always wins
preprocessing_steps=preprocessing_steps or [default]

# GOOD: explicit None sentinel
preprocessing_steps=preprocessing_steps if preprocessing_steps is not None else [default]
```

**影响范围**：三个测试文件各自有独立的 `_make_plan()` helper（`test_execution.py`、
`test_preprocessing.py`、`test_graph.py`），行为不一致，缺乏共享工厂。

### L2: `set_llm_env` fixture 缺失 → 真实 API 调用

**现象**：`test_preprocessing_node_no_steps_skips` 未声明 `set_llm_env`。
L1 导致 LLM 被意外触发，OpenAI SDK 直接报 401。双重叠加使排查绕了一圈。

**规则**：任何 `*_node_*` 测试必须挂 `set_llm_env` fixture。
不依赖"LLM 不会被调用"的假设——skip 分支可能因 bug 不触发。

### L3: 集成测试 mock 断言与 skip 路径脱节

**现象**：`_EXECUTION_PLAN_JSON.preprocessing_steps = []`，预处理节点走 skip 分支
（不调 LLM、无 `parsed_output`），但测试断言了 `mock_pre.invoke.assert_called_once()`
和 `preprocessing_result["parsed_output"]`。三者对不上。

**根因**：集成测试 mock 期望是"硬编码"的——假定每个节点都会调 LLM。
当节点内部有 skip 分支时假设破裂。

### L4: `contextlib.suppress(NotImplementedError)` 掩盖下游失败

**现象**：`test_graph_data_track_integration` 用 `contextlib.suppress` 吞掉
graph.invoke 中未 mock 节点的错误。如果新插入节点未 mock，测试仍然绿。

**根因**：这个 suppress 最初是占位阶段的遗留（D6），但现在 graph 已完整，
不应该再有 `NotImplementedError`。

## Risks Addressed

| Risk | Severity | Lesson | Fix |
|------|----------|--------|-----|
| `analysis_steps=[]` skip → mock assertion mismatch | HIGH | L1, L3 | T1, T2 |
| 真实 LLM API 调用泄露 | HIGH | L2 | T3 |
| Mock 链未覆盖新节点但测试绿 | MEDIUM | L4 | T5 |
| 沙箱执行路径零覆盖 | MEDIUM | — | T4 |
| 各测试 helper 签名分歧 | MEDIUM | L1 | T1 |
| 全局 JSON 常量级联修改 | LOW | L3 | T2 |

## Implementation

### V2.1 — Testing Debt Repayment (单一 Phase)

V2 Phase 5-6 完成后执行，不改动 `src/` 任何逻辑，纯测试重构。

#### T1 — 统一 `make_execution_plan` 工厂

在 `tests/conftest.py` 中新增 `make_execution_plan` fixture，使用 `is not None`
模式处理所有 Optional 集合字段：

```python
@pytest.fixture
def make_execution_plan() -> Callable[..., ExecutionPlan]:
    def _make(**overrides: Any) -> ExecutionPlan:
        defaults: dict[str, Any] = {
            "feasibility_map": [...],
            "model_selections": [],
            "preprocessing_steps": [...],
            "analysis_steps": [...],
            "alignment_notes": "Test plan.",
        }
        merged = {k: overrides.get(k, v) for k, v in defaults.items()}
        merged.update({k: v for k, v in overrides.items() if k in defaults})
        return ExecutionPlan(**merged)
    return _make
```

替换所有测试文件中的独立 `_make_plan()` / `_make_execution_plan()` helper。

#### T2 — 废弃全局 `_EXECUTION_PLAN_JSON`

删除 `tests/test_graph.py` 中的 `_EXECUTION_PLAN_JSON` 和 `_REVISED_PLAN_JSON`。
集成测试改用 `make_execution_plan` 显式构造。

#### T3 — 全量 `set_llm_env` 审查

审查所有 `*_node_*` 测试，确保每个都挂 `set_llm_env` fixture。

#### T4 — Smoke test 骨架

新建 `tests/test_smoke.py`：
- mock LLM 返回固定代码
- 不 mock `run_script`
- 验证 subprocess 真实执行成功，JSON 输出可解析

#### T5 — 移除 `contextlib.suppress`

修改 `test_graph_data_track_integration`：mock 完整链，移除
`contextlib.suppress(NotImplementedError)`。

## Files to Change

| File | Action | Why |
|------|--------|-----|
| `tests/conftest.py` | UPDATE | T1 — 新增 `make_execution_plan` fixture |
| `tests/test_graph.py` | REFACTOR | T2, T5 — 废弃全局 JSON，移除 suppress |
| `tests/test_execution.py` | REFACTOR | T1 — 替换独立 `_make_plan()` |
| `tests/test_preprocessing.py` | REFACTOR | T1 — 替换独立 `_make_plan()` |
| `tests/test_report_gen.py` | REFACTOR | T1 — 替换独立 `_make_plan()` |
| `tests/test_analysis.py` | REFACTOR | T1 — 替换独立 `_make_plan()` （如有） |
| `tests/test_smoke.py` | CREATE | T4 — 真实沙箱 smoke test |

## Validation

```bash
ruff check . && ruff format --check .
mypy src/
pytest -v  # 测试总数因 smoke test 增加，src/ 行为不变
```

## Dependencies

```
V2 Phase 6 (Report Gen) ──→ V2.1 Test Hardening
```

V2.1 是纯测试重构，不改动 `src/` 逻辑。在 V2 全部功能节点就位后执行，
收益最大（此时所有 `_make_plan` 变体都已产生，需要统一）。

---
*Plan for DataInsight V2.1 — Post-V2 test hardening derived from Phase 3-4 lessons learned.*
