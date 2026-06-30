# Plan: DataInsight V2.1 — Test Hardening & Debt Repayment

**Depends on**: [data-insight-agent-v2.plan.md](data-insight-agent-v2.plan.md) (Phase 0-6)
**Status**: Pre-Phase-5 — pay down testing debt before Analysis node development
**Complexity**: Medium

## Motivation

Phase 3-4 实施过程中暴露了 3 类可重现的测试脆弱性问题，其中 L1 和 L3 会在
Phase 5（Analysis 节点）完全重现（`analysis_steps=[]` → skip 路径，
mock 断言再次不匹配）。本 Plan 在继续 Phase 5 之前系统性清偿这些债务。

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

**影响范围**：三个测试文件各自有独立的 `_make_plan()` helper，行为不一致
（`or` fallback vs 硬编码 `[]`），缺乏共享工厂。

**重现风险**：Phase 5 `analysis_steps` 有相同语义——空列表表示"无分析步骤"。

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

**重现风险**：Phase 5 的 `analysis_steps` 空 → analysis 节点 skip → 同样的
`mock_analysis.invoke` 不会被调用 → 断言失败。

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

### Phase 5a: Testing Debt Repayment

**5a.1 — 统一 `make_execution_plan` 工厂** (T1)

在 `tests/conftest.py` 中新增 `make_execution_plan` fixture，使用 `is not None`
模式处理所有 Optional 集合字段：

```python
@pytest.fixture
def make_execution_plan() -> Callable[..., ExecutionPlan]:
    def _make(**overrides: Any) -> ExecutionPlan:
        defaults: dict[str, Any] = {
            "feasibility_map": [
                {"intent_dimension": "region", "matched_columns": ["region"],
                 "feasibility": "可直接实现", "confidence": "High",
                 "reasoning": "Direct match"},
            ],
            "model_selections": [],
            "preprocessing_steps": [
                {"step": 1, "action": "drop_null_rows", "target_columns": ["region"],
                 "urgency": "高优先", "reason": "2% nulls"},
            ],
            "analysis_steps": [
                {"step": 1, "action": "compute_correlation",
                 "target_columns": ["sales"], "method": "pandas.DataFrame.corr",
                 "expected_output": "correlation matrix"},
            ],
            "alignment_notes": "Test plan.",
        }
        merged = {k: overrides.get(k, v) for k, v in defaults.items()}
        merged.update({k: v for k, v in overrides.items() if k in defaults})
        return ExecutionPlan(**merged)
    return _make
```

替换 `test_execution.py`、`test_preprocessing.py`、`test_graph.py` 中的独立 `_make_plan()`。

**5a.2 — 废弃全局 `_EXECUTION_PLAN_JSON`** (T2)

删除 `tests/test_graph.py` 中的 `_EXECUTION_PLAN_JSON` 和 `_REVISED_PLAN_JSON`。
集成测试改用 `make_execution_plan` 显式构造。

**5a.3 — 全量 `set_llm_env` 审查** (T3)

审查所有 `*_node_*` 测试，确保每个都挂了 `set_llm_env` fixture。
添加 pre-commit 检查规则（grep 测试签名）。

**5a.4 — Smoke test 骨架** (T4)

新建 `tests/test_smoke.py`：
- mock LLM 返回固定代码（dropna + describe + corr）
- 不 mock `run_script`
- 验证 subprocess 真实执行成功，JSON 输出可解析

```python
@pytest.mark.smoke
def test_preprocessing_real_sandbox(sample_csv_path, set_llm_env, tmp_path):
    """Preprocessing sandbox executes real Python code (mock LLM only)."""
    plan = ExecutionPlan(
        feasibility_map=[], model_selections=[],
        preprocessing_steps=[{"step": 1, "action": "drop_null_rows",
                              "target_columns": ["age"], "urgency": "高优先",
                              "reason": "test"}],
        analysis_steps=[], alignment_notes="",
    )
    # Mock LLM returns a real cleaning script
    # Do NOT mock run_script — this exercises the actual subprocess path
```

**5a.5 — 移除 `contextlib.suppress`** (T5)

修改 `test_graph_data_track_integration`：mock report_gen 节点 LLM，
移除 `contextlib.suppress(NotImplementedError)`。

### Phase 5b: Analysis Node Development

同 [V2 plan Phase 5](data-insight-agent-v2.plan.md)。

## Files to Change

| File | Action | Phase |
|------|--------|-------|
| `tests/conftest.py` | UPDATE | 5a.1 — 新增 `make_execution_plan` fixture |
| `tests/test_graph.py` | REFACTOR | 5a.2 — 废弃全局 JSON，使用共享 factory |
| `tests/test_execution.py` | REFACTOR | 5a.1 — 替换 `_make_plan()` |
| `tests/test_preprocessing.py` | REFACTOR | 5a.1 — 替换 `_make_plan()` |
| `tests/test_report_gen.py` | REFACTOR | 5a.1 — 替换 `_make_plan()` |
| `tests/test_smoke.py` | CREATE | 5a.4 — 真实沙箱 smoke test |
| `tests/test_analysis.py` | CREATE | 5b — Analysis 节点测试 |
| `src/agent/nodes/analysis.py` | CREATE | 5b — Analysis 节点 |
| `src/agent/state.py` | UPDATE | 5b — 新增 `analysis_result` 字段 |
| `src/agent/graph.py` | UPDATE | 5b — 插入 analysis 节点，替换 execution |
| `src/agent/nodes/execution.py` | DELETE | 5b — 被 preprocessing + analysis 替代 |
| `src/agent/nodes/__init__.py` | UPDATE | 5b — 导出 analysis_node |

## Validation

```bash
# 5a 完成后：
ruff check . && ruff format --check .
mypy src/
pytest -v  # 78 → ~82 (新增 smoke tests)

# 5b 完成后：
ruff check . && ruff format --check .
mypy src/
pytest -v  # ~82 → ~92 (新增 analysis tests)

# 完整端到端：
python -m src data.csv "分析问题" -s -v
```

## Dependencies

```
Phase 5a (Debt Repayment) ──→ Phase 5b (Analysis Node) ──→ Phase 6 (Report Gen Refactor)
```

Phase 5a 必须在 5b 之前完成——否则 L1/L3 在 analysis 节点测试中完全重现。

## Acceptance

- [ ] Phase 5a: `make_execution_plan` 工厂统一，全局 JSON 废弃，smoke test 通过
- [ ] Phase 5b: Analysis 节点 + ReAct，execution.py 删除
- [ ] Phase 6: Report Gen 重构
- [ ] 端到端测试：`python -m src data.csv "问题" -s -v`
- [ ] ruff check + mypy src/ + pytest -v 全部绿灯

---
*Plan for DataInsight V2.1 — Test hardening derived from Phase 3-4 lessons learned.*
