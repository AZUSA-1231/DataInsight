# 修复方案：Cycle 3 代码审查问题整改

**来源审查**: `.claude/audits/` (本地审查，2026-07-11)
**审查结论**: REQUEST CHANGES — 2 CRITICAL, 7 HIGH, 8 MEDIUM, 4 LOW
**复杂度**: Medium

---

## Summary

修复两个阻塞合并的安全漏洞（路径穿越、提示注入），解决 7 个 HIGH 级别问题（上传限制、速率限制、长函数拆分、异常边界、非状态键泄露、测试覆盖率），并清理 8 个 MEDIUM 和 4 个 LOW 级别的代码质量问题。预计 2-3 个会话完成全部修复。

---

## Patterns to Mirror

| 类别 | 来源 | 模式说明 |
|------|------|----------|
| 路径校验 | `src/__main__.py:55-69` | `Path.resolve()` + 基准目录前缀比对，已有成熟实现 |
| 注入清洗 | `src/__main__.py:33-52` | `_INJECTION_DELIMITERS` + `_sanitize_user_input()`，复用即可 |
| API 路由 | `src/api/routes/execution.py:38-58` | FastAPI `HTTPException` 抛错模式 + `store.update()` 状态写入 |
| 错误边界 | `src/agent/nodes/analysis.py` | 节点返回 `{"error": str}` 而非 raise |
| 日志 | `src/agent/dag.py:20` | `logger = logging.getLogger(__name__)` 模块级 |
| 测试 | `tests/test_dag.py` | `@pytest.mark.unit` + `_u()` helper 工厂 + AAA 结构 |

---

## Files to Change

| 文件 | 操作 | 原因 |
|------|------|------|
| `src/agent/input_guard.py` | **CREATE** | 共享输入清洗工具（从 `__main__.py` 提取） |
| `src/__main__.py` | UPDATE | 导入共享 `input_guard`，删除本地 `_sanitize_user_input` |
| `src/api/routes/data.py` | UPDATE | 添加路径穿越检查 + 文件大小限制 |
| `src/api/routes/dialogue.py` | UPDATE | 调用 `input_guard` 清洗用户输入；删除冗余 `hasattr` |
| `src/api/routes/execution.py` | UPDATE | 删除死常量 `MAX_RETRIES`；`_run_execution` 加 try/except；派生 `output_dir` |
| `src/agent/nodes/business_track.py` | UPDATE | 解析函数加日志；裸 `except` 加 `exc_info`；docstring 补全 |
| `src/agent/nodes/planner.py` | UPDATE | 复用 `utils._extract_json`；单单元校验报错 |
| `src/agent/nodes/report_gen.py` | UPDATE | `import os` 提升到模块级 |
| `tests/test_input_guard.py` | **CREATE** | 新增输入清洗测试 |
| `tests/api/test_data.py` | UPDATE | 新增路径穿越 + 大文件拒绝测试 |

---

## Tasks

### Phase 1: CRITICAL 修复（阻塞合并）

#### Task 1.1: 创建共享输入清洗模块 `src/agent/input_guard.py`
- **Action**: 将 `__main__.py` 中的 `_INJECTION_DELIMITERS`、`_sanitize_user_input()` 提取为公共函数 `sanitize_user_input(text, max_len=2000)`；`_validate_file_path()` 提取为 `validate_upload_path(upload_dir, filename) -> Path`，返回解析后的安全路径（已包含 `resolve()` + 前缀校验）
- **Mirror**: `src/__main__.py:33-69` 现有实现
- **Validate**: `pytest -v tests/test_input_guard.py`

#### Task 1.2: 修复 `data.py` 路径穿越 + 上传大小限制
- **Action**:
  - 在 `upload_file` 中用 `validate_upload_path(upload_dir, file.filename)` 替换直接拼接
  - 添加 `MAX_UPLOAD_BYTES = 500 * 1024 * 1024`，读取前检查 `Content-Length` header
- **Mirror**: `src/api/routes/execution.py:122-127` 的路径穿越检查模式
- **Validate**: `pytest -v -k "test_upload"`

#### Task 1.3: 修复 `dialogue.py` 提示注入
- **Action**:
  - 在 `send_message()` 中调用 `sanitize_user_input(body.message, 2000)`
  - 在 `stream_intent()` 中对 `message` 参数做同样处理
  - 删除 `_build_fallback_prompt()` 中的直接插值（清洗后再传入）
- **Mirror**: `src/__main__.py:45-52` 的 `_sanitize_user_input` 逻辑
- **Validate**: `pytest -v -k "test_dialogue"`

### Phase 2: HIGH 修复

#### Task 2.1: 执行器异常边界
- **Action**: `_run_execution()` 中 `analysis_node(state)` 加 try/except，异常时写入 `{"analysis_result": {"status": "failed"}, "error": str(e)}`
- **Mirror**: `src/agent/nodes/analysis.py` 的错误处理模式
- **Validate**: `pytest -v -k "test_execution"`

#### Task 2.2: 非状态键泄露问题 `business_track_node`
- **Action**: 在 `AgentState` TypedDict 中添加 `bt_response: str` 和 `bt_tool_called: bool`（`NotRequired`），或者更干净的做法：改为返回 `tuple[dict, dict]` 分离元数据。推荐方案二（更干净、不污染 State）
- **Mirror**: 当前 `dialogue.py:51-63` 的消费模式
- **Validate**: `pytest -v -k "test_business_track"`

#### Task 2.3: `main()` 函数拆分
- **Action**:
  - 提取 `_run_planning_phase()` — 包含 Phase 1 的所有 YAML 打印 + 计划展示
  - 提取 `_run_analysis_phase()` — 包含 Phase 2 的图执行 + 报告生成
  - 提取 `_interactive_modify_loop()` — 包含计划修改 + 反馈迭代
  - `main()` 仅剩编排逻辑（约 40 行）
- **Mirror**: 当前 `__main__.py` 中 `_display_plan`、`_handle_plan_modification` 等已拆分的辅助函数
- **Validate**: `pytest -v -k "test_smoke"`

#### Task 2.4: `_save_intermediates()` 拆分
- **Action**:
  - 提取 `_save_results_json()` — JSON 序列化
  - 提取 `_save_per_unit_scripts()` — 每个 unit 的脚本 + stdout
  - 提取 `_copy_chart_images()` — 图表复制（复用已有的 `_copy_charts_next_to_report`）
- **Mirror**: 当前 `__main__.py` 中 `_copy_charts_next_to_report` 的提取模式
- **Validate**: `python -m src <test_csv> "test" --save-intermediates`

#### Task 2.5: 测试覆盖率提升到 80%
- **Action**:
  - `tests/test_business_track.py` — 补充 LLM 错误路径、fallback 文本提取、tool-call 错误处理
  - `tests/api/test_dialogue.py` — 补充 SSE streaming、fallback 路径、错误 yield
  - `tests/test_llm.py` — 补充 `get_llm()` 工厂测试
- **Mirror**: `tests/test_dag.py` 的 `@pytest.mark.unit` + helper factory 模式
- **Validate**: `pytest --cov=src --cov-report=term-missing`

### Phase 3: MEDIUM 修复

#### Task 3.1: 删除死常量
- **Action**: 删除 `src/api/routes/execution.py:19` 的 `MAX_RETRIES = 3`
- **Validate**: `ruff check .`

#### Task 3.2: 解析函数加错误日志
- **Action**: `business_track.py` 中 `_parse_unit_suggestions` / `_parse_suggestions` 的 `except` 块内加 `logger.warning("...", exc_info=True)`
- **Validate**: `pytest -v -k "test_business_track"`

#### Task 3.3: 删除 `_extract_json` 重复
- **Action**: `planner.py` 导入 `from src.agent.utils import _extract_json`，删除本地副本
- **Validate**: `pytest -v -k "test_planner"`

#### Task 3.4: 删除冗余 `hasattr`

- **Action**: `dialogue.py:68-70` 中 `instruction.model_dump()` 直接调用，移除 `hasattr` + `else` 分支
- **Validate**: `pytest -v -k "test_dialogue"`

#### Task 3.5: 图表服务 `output_dir` 硬化
- **Action**: `execution.py:120` 不信任 `ana.get("output_dir")`，改为 `OUTPUT_DIR / session_id`
- **Validate**: `pytest -v -k "test_execution"`

#### Task 3.6: `business_track_node` 裸 `except` 加日志
- **Action**: `except Exception:` 块内加 `logger.warning("...", exc_info=True)`
- **Validate**: `pytest -v -k "test_business_track"`

### Phase 4: LOW 修复

#### Task 4.1: 模块级 import
- **Action**: `report_gen.py` 中 `import os` 和 `import re` 移到模块顶部
- **Validate**: `ruff check .`

#### Task 4.2: docstring 补全
- **Action**: `business_track_node` docstring 的 "Writes" 段增加 `_bt_response`、`_bt_tool_called`、`feedback` 的说明
- **Validate**: review only

#### Task 4.3: `_get_store` 类型标注
- **Action**: 所有路由文件中的 `_get_store` 返回 `SessionStore` 类型，删除 `Any`
- **Mirror**: `src/api/session.py` 的 `SessionStore` 类型
- **Validate**: `mypy src/api/`

---

## Validation

```bash
# 全部修复完成后执行
ruff check .                           # lint 零告警
mypy src/                              # 类型检查零错误
pytest -v                              # 全部测试通过
pytest --cov=src --cov-report=term --cov-fail-under=80  # 覆盖率 >= 80%
```

---

## Risks

| 风险 | 可能性 | 缓解措施 |
|------|--------|----------|
| `business_track_node` 返回类型改为 `tuple` 破坏现有调用方 | 低 | `dialogue.py` 和 `graph.py` 是仅有的调用方，同步修改 |
| `_sanitize_user_input` 提取为共享模块影响 CLI 行为 | 低 | API 和 CLI 共用同一实现，行为一致；加测试覆盖 |
| 覆盖率从 71% 提升到 80% 需大量测试 | 中 | 优先补 `business_track` 和 `dialogue` 的 error-path 测试；`llm.py` 写 3-5 个测试即可大幅提升 |
| 速率限制引入 `slowapi` 依赖 | 低 | 如不想引入新依赖，可手写简单的 `time`-based throttle middleware |

---

## Acceptance

- [ ] Phase 1: 两个 CRITICAL 全部修复
- [ ] Phase 2: 七个 HIGH 全部修复
- [ ] Phase 3: 八个 MEDIUM 全部修复
- [ ] Phase 4: 四个 LOW 全部修复
- [ ] `ruff check .` 零告警
- [ ] `pytest -v` 全部通过
- [ ] 测试覆盖率 ≥ 80%
- [ ] 无新增安全漏洞
