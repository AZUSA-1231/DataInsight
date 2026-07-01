# Architecture Decision Log — DataInsight

Decisions and compromises made during implementation that are NOT specified in the PRD.
Review before Milestone 3/4 when execution and report nodes will be built on these foundations.

---

## D1 — Immutable state via `TypedDict` (not Pydantic)

**Date**: M1 | **Scope**: entire pipeline

LangGraph 1.0 expects dict-like state. We chose `typing.TypedDict` over Pydantic
`BaseModel` because LangGraph natively understands `TypedDict` fields as state
channels. Pydantic would require an extra `.model_dump()` on every node return.

**Trade-off**: No runtime validation on state shape. A node that writes a bogus
key won't be caught until the downstream consumer fails.

**Mitigation**: mypy strict catches most shape errors at dev time.

---

## D2 — Subprocess sandbox (not Docker)

**Date**: M1 | **Scope**: [src/sandbox/executor.py](src/sandbox/executor.py)

Execution isolation uses `subprocess.run()` with timeout, not Docker/container.
This is the simplest MVP sandbox but provides **no filesystem isolation, no
network isolation, no memory limit**.

**Why**: Docker adds a hard dependency for CLI users. Subprocess covers the
common case (script stuck in infinite loop) with timeout. For the remaining
risk (malicious code from a compromised LLM), we accept it in MVP.

**Revisit when**: someone reports a sandbox-escape concern, or when we add
user-uploaded scripts (currently only our own `inspection_script.py` runs).

---

## D3 — Deterministic inspection as package asset

**Date**: M1 | **Scope**: [src/sandbox/inspection_script.py](src/sandbox/inspection_script.py)

The PRD requires data inspection to be deterministic, not LLM-generated. We
implemented this as a `.py` file shipped inside the package and invoked via
subprocess. The alternative was a set of functions called in-process, but
subprocess gives us the same sandbox guarantees (timeout, isolated crash) as
future user-generated code will get.

**Trade-off**: Path resolution (`os.path.join(__file__, "..", "..", "sandbox", ...)`)
is fragile. If the package is installed as a wheel, `__file__` still works, but
flat-layout vs src-layout confusion could break it.

**Mitigation**: Deferred. Not a problem for editable installs.

---

## D4 — ReAct retry as conditional edge (not internal loop)

**Date**: M1 | **Scope**: [src/agent/graph.py](src/agent/graph.py)

The execution retry loop (max 3) is implemented as a LangGraph `conditional_edge`
that routes back to the `execution` node itself. The alternative was an internal
`for _ in range(3)` loop inside `execution_node`.

**Why edge-based**: Each retry is a separate graph step, which LangGraph can
trace, checkpoint, and interrupt. An internal loop would be opaque to the graph
runtime. This matters for future streaming and human-in-the-loop features.

**Trade-off**: Retry count must be stored in `state["execution_result"]["retry_count"]`
rather than a local variable, adding coupling between the node and the routing
function (`_should_retry_execution`).

---

## D5 — Error signaling via state field (not exceptions)

**Date**: M1 | **Scope**: all nodes

Nodes write errors into `state["error"]` rather than raising exceptions.
LangGraph can continue routing after a state error (e.g., skip to report_gen
with partial results). A raised exception would halt the entire graph.

**Trade-off**: Every downstream node must check `state.get("error")` before
assuming upstream data is valid. Currently only `_should_retry_execution`
and the conditional edge do this. Report Gen (M4) MUST handle the `error`
key to produce partial reports.

**Revisit when**: M4 — Report Gen needs an explicit "partial report on error"
path.

---

## D6 — Stub nodes throw `NotImplementedError` (not no-op)

**Date**: M1 | **Scope**: nodes/business_track.py, decision_match.py, execution.py, report_gen.py

Stub nodes deliberately crash the graph. The alternative was a no-op that
passes state through unchanged.

**Why fail-fast**: A no-op would let the graph reach END silently, producing
a "report" missing entire stages. `NotImplementedError` makes it impossible
to mistake an incomplete pipeline for a working one.

**Revisit when**: each stub is implemented. These errors are temporary scaffolding.

---

## D7 — LLM provider limited to OpenAI API

**Date**: M1 | **Scope**: [src/agent/llm.py](src/agent/llm.py)

`get_llm()` only supports `provider == "openai"`, returning `ChatOpenAI`.
All other values raise `ValueError`. The env-var naming (`DATAINSIGHT_LLM_*`)
is provider-agnostic, but the implementation is not.

**Why**: OpenAI-compatible APIs cover 90%+ of LLM providers already (DeepSeek,
Qwen, etc. via `base_url` override). True multi-provider support (Anthropic,
Gemini) would add SDK dependencies and per-provider parameter mapping for no
MVP benefit.

**Revisit when**: someone asks for Claude or Gemini as the LLM backend.

---

## D8 — Encoding detection chain for CSV

**Date**: M1 | **Scope**: [src/sandbox/inspection_script.py](src/sandbox/inspection_script.py)

CSV encoding detection tries 6 encodings in order: `utf-8 → utf-8-sig → latin-1
→ gbk → gb2312 → cp1252`. Falls back to `utf-8`.

**Why this order**: `gbk` and `gb2312` are common in Chinese CSV exports (Windows
Excel in Chinese locale outputs GBK by default). They come after `utf-8` because
UTF-8 is the modern default and should win when data is actually UTF-8. `latin-1`
never fails (any byte sequence is valid latin-1), so it's a fallback-of-last-resort
that will produce garbled text rather than crashing.

**Trade-off**: No auto-detection via `chardet` or similar library. Adding it
would require another dependency for a single function call.

**Revisit when**: users report encoding errors for files in other encodings
(e.g., Shift-JIS, EUC-KR).

---

## D9 — Chinese LLM prompts, English documentation

**Date**: M1 | **Scope**: data_track.py prompts, all .md files

The user communicates in Chinese and the LLM audit report is produced in
Chinese (prompts are written in Chinese). All code, comments, PRD, plans,
and decision logs are in English.

**Risk**: Chinese prompt engineering is a separate skill from code quality.
Prompt quality is not checked by ruff/mypy. Poor prompts produce poor audit
reports regardless of code correctness.

**Revisit when**: prompt evaluation framework (likely M4) — need to test
prompt quality as rigorously as code correctness.

---

## D10 — `line-length = 100` in ruff (not PEP 8 default 79)

**Date**: M1 | **Scope**: pyproject.toml

PEP 8 recommends 79 characters. We set 100.

**Why**: The LLM prompt strings in data_track.py are Chinese text blocks that
can't be wrapped at word boundaries without breaking readability. 100 columns
accommodates these without excessive line continuation noise.

---

## D11 — Sequential dual-track (not parallel)

**Date**: M2 | **Scope**: [src/agent/graph.py](src/agent/graph.py)

The PRD describes Stage 1 as "Parallel Dual-Track Assessment." The current graph
runs `data_track → business_track` sequentially, not in parallel.

**Why**: True parallelism in LangGraph 1.0 requires the `Send` API (fan-out from
START to both nodes, fan-in to decision_match, error aggregation for partial
failures). Both nodes are LLM calls — the user waits either way. Sequential
execution is simpler to test, debug, and reason about.

**Upgrade path**: To make them parallel: `graph.add_edge(START, "data_track")`
and `graph.add_edge(START, "business_track")` with both routing to
`decision_match`. LangGraph will wait for both before invoking decision_match.
Error from either would need a `should_continue` conditional edge.

**Revisit when**: streaming UI is built (user sees per-node progress), or when
one of the nodes becomes slow enough that parallelism actually saves wall-clock time.

---

## D12 — LLM generates analysis code (not deterministic)

**Date**: M3 | **Scope**: [src/agent/nodes/execution.py](src/agent/nodes/execution.py)

Unlike the Data Track inspection script (D3 — deterministic, human-written), the
execution phase generates Python analysis code dynamically via LLM. This is by
design per the PRD: the execution plan from Decision Match is an abstract
specification, and the LLM translates it into concrete code.

**Risk**: LLM hallucinates column names, invents pandas APIs, or generates code
that passes syntax check but produces wrong results (e.g., grouping by the wrong
column).

**Mitigation**: ReAct retry loop (D4) catches runtime errors (NameError, KeyError,
TypeError). Logically wrong but runnable code is NOT caught — this is an accepted
risk for MVP. The "Data & Business Alignment Notes" in the final report (M4) is
the user's opportunity to spot misalignment.

**Revisit when**: M4 report generation — the report should flag which columns
were actually used vs. planned, so users can spot discrepancies.

---

## D13 — Temp scripts not cleaned up

**Date**: M3 | **Scope**: [src/agent/nodes/execution.py](src/agent/nodes/execution.py)

LLM-generated analysis scripts are written to `tempfile.mkstemp()` and the paths
are stored in `execution_result["script_path"]` but never deleted.

**Why**: The script is valuable debugging artifact when a user reports "the
analysis looks wrong." Being able to inspect the exact code the LLM generated
is more important than saving a few KB of disk.

**Trade-off**: Accumulates temp files over many runs. OS temp dir cleanup
(reboot or tmpwatch) handles this eventually.

**Revisit when**: production deployment with high throughput — add a configurable
`--cleanup-scripts` flag or a max-retained limit.

---

## D14 — Feedback loop via conditional edge (not CLI restart)

**Date**: M4 | **Scope**: [src/agent/graph.py](src/agent/graph.py)

In-session iteration routes feedback through the graph itself: `report_gen →
_should_iterate → decision_match`. This skips Data Track and Business Track
(the data and business understanding haven't changed), reusing all prior context.

**Alternative considered**: CLI wrapper restarts the entire graph with feedback
injected into `user_requirement`. Rejected because it wastes LLM calls re-running
data audit and business analysis that are unaffected by feedback.

**Trade-off**: Only one feedback cycle per user input. Feedback is consumed
(popped from state) by decision_match, so the second pass through report_gen
sees no feedback and routes to END. If the user is still unhappy, they provide
new feedback in the CLI loop.

---

## D15 — CLI simplicity (argparse, no framework)

**Date**: M4 | **Scope**: [src/__main__.py](src/__main__.py)

The CLI uses stdlib `argparse` + `input()` loop. No rich, click, textual, or
prompt_toolkit.

**Why**: Zero additional dependencies. MVP is single-session CLI. A rich TUI
or web frontend adds value only after the core pipeline is validated.

**Revisit when**: someone requests persistent session history, progress bars
for each stage, or a web-based report viewer.

---

---

## D16 — Subprocess encoding tolerance via `errors="replace"`

**Date**: post-MVP | **Scope**: [src/sandbox/executor.py](src/sandbox/executor.py)

LLM-generated scripts run on Windows may output GBK-encoded Chinese text via
`print()`. The original `subprocess.run(encoding="utf-8")` would crash the reader
thread with `UnicodeDecodeError`, leading to `stdout=None` → `.strip()` →
`AttributeError` → entire pipeline FATAL.

**Fix**: `errors="replace"` replaces undecodable bytes with `�` instead of
crashing. Additionally, `or ""` guards on all stdout/stderr values prevent
`NoneType` from reaching `.strip()`.

**Trade-off**: Garbled characters (`�`) in error messages are better than a
dead pipeline. The LLM can still diagnose the error from the English traceback
portion.

---

## D17 — Prompt-driven performance constraints

**Date**: post-MVP | **Scope**: [src/agent/nodes/execution.py](src/agent/nodes/execution.py)

The code-gen prompt now explicitly bans `.iterrows()` and nested Python for loops
on datasets >10,000 rows, requiring vectorized pandas operations instead. The
ReAct prompt includes a "Timeout (120s)" case telling the LLM to switch to
vectorized ops or sample to 30K rows.

**Why**: On the 122K-row games.csv, the LLM generated `.iterrows()` loops that
either OOM'd or exceeded the 120s timeout. Vectorized operations complete in
seconds on the same data.

**Risk**: Prompt constraint is advisory — the LLM can still generate `.iterrows()`.
It's a nudge, not enforcement.

**Revisit when**: we add a static-analysis check for banned patterns before
allowing a generated script to run.

---

## D18 — Chart persistence via `--save-intermediates`

**Date**: post-MVP | **Scope**: [src/__main__.py](src/__main__.py)

Generated chart `.png` files reside in a `tempfile.mkdtemp()` directory inside
the sandbox. Without `--save-intermediates`, these images are lost when the OS
cleans up temp files.

**Fix**: `_save_intermediates()` now copies all `.png` files from the sandbox
output directory into `<output>_intermediates/charts/`.

**Trade-off**: Charts are duplicated (temp + intermediates). The temp copy still
gets cleaned by the OS. This is acceptable for CLI use; a server deployment
would want a configurable output directory instead of temp.

---

## D19 — Pre-installed dependency policy (scikit-learn, scipy)

**Date**: post-MVP | **Scope**: [pyproject.toml](pyproject.toml)

scikit-learn and scipy were added as hard dependencies rather than letting the
LLM discover their absence at runtime.

**Why**: The original approach was "let the LLM import whatever it needs, and
ReAct will fix ImportError." But ReAct only gets 3 attempts — wasting one on
a missing package reduces debugging budget for real problems. Pre-installing
the most likely ML/statistics packages reduces ImportError frequency.

**Trade-off**: Larger install footprint. scipy is ~30MB. Acceptable for a
desktop CLI tool; would be different for a serverless function.

---

## D20 — `.env` file for persistent LLM configuration

**Date**: post-MVP | **Scope**: [src/agent/llm.py](src/agent/llm.py)

LLM credentials (model, API key, base URL) are read from a `.env` file in the
project root, with environment variables taking precedence when both exist.

**Why**: On Windows CMD, `set` only lasts for the current terminal session.
Users had to re-enter credentials every time they opened a new terminal. The
`.env` file is IDE-editable and survives reboots.

**Implementation**: `_load_dotenv()` is a minimal parser (~15 lines) that reads
`KEY=VALUE` lines, strips quotes, and only sets keys not already in `os.environ`.
No python-dotenv dependency needed.

**Security**: `.env` is git-ignored. `.env.example` is checked in as a template.
`_check_prerequisites()` gives clear "no .env found" / ".env exists but missing
X" error messages.

---

## D21 — V2: Pydantic replaces TypedDict for AgentState

**Date**: V2 | **Scope**: [src/agent/state.py](src/agent/state.py)

AgentState moves from `typing.TypedDict` to `pydantic.BaseModel` for runtime
type validation. D1 (TypedDict choice) was correct for MVP but led to multiple
bugs where nodes wrote incorrect field types that mypy couldn't catch at runtime.

**Trade-off**: Pydantic adds a dependency (already pulled in by langchain).
`model_copy(update={...})` replaces `{**state, "k": v}` syntax.

**Migration strategy**: Phase 0 — change the container only, keep existing fields.
SubModels (DataProfile, AnalysisIntent, ExecutionPlan) added in subsequent phases.

---

## D22 — V2: Data Track output split into DataProfile + cleaning_insights

**Date**: V2 | **Scope**: [src/agent/nodes/data_track.py](src/agent/nodes/data_track.py)

The inspection JSON is now parsed into a structured `DataProfile` Pydantic model
(no LLM involvement). The LLM only produces `cleaning_insights` — a concise
cleaning/preprocessing recommendation — instead of a verbose 5-section audit report.

**Why**: The original audit report was a human-readable translation of structured
data the machine already had. Other nodes need the structured form, not prose.

---

## D23 — V2: Business Track narrowed to intent understanding

**Date**: V2 | **Scope**: [src/agent/nodes/business_track.py](src/agent/nodes/business_track.py)

Business Track is re-scoped from "business analysis blueprint" (5 sections of free-form
Chinese text) to an intent parser that outputs structured `AnalysisIntent` JSON.

**Why**: Without data visibility, the original Business Track frequently proposed
metrics that were impossible to compute, confusing downstream nodes. Narrowing it
to intent extraction reduces hallucination surface.

---

## D24 — V2: Decision Match upgraded to Planner (with model selection)

**Date**: V2 | **Scope**: [src/agent/nodes/decision_match.py](src/agent/nodes/decision_match.py)

Decision Match is redesigned as a Planner that:
- Maps every business metric to available data columns with feasibility tags
- Selects analysis models/methods with explicit reasoning chains
- Produces structured `ExecutionPlan` with separate preprocessing_steps and analysis_steps
- Maintains mandatory alignment_notes

**Why**: MVP Decision Match was essentially a summarizer of two reports. The Planner
is the intelligence layer — it makes the hard trade-off decisions that define the
quality of downstream execution.

---

## D25 — V2: Execution split into preprocessing + analysis

**Date**: V2 | **Scope**: [src/agent/nodes/preprocessing.py](src/agent/nodes/preprocessing.py), [src/agent/nodes/analysis.py](src/agent/nodes/analysis.py)

The single execution node is split into two graph nodes:
1. **preprocessing** — data cleaning (type conversion, null handling, encoding)
2. **analysis** — EDA, modeling, chart generation

Each has its own ReAct retry loop (max 3). Preprocessing success is checkpointed
so analysis retries don't re-run cleaning.

**Why**: Single-script generation had low success rate (LLM must write correct
cleaning + analysis + charting in one shot). Splitting reduces per-prompt
complexity and prevents re-running expensive cleaning on analysis failures.

---

## D26 — V2: True parallel dual-track (Send API)

**Date**: V2 | **Scope**: [src/agent/graph.py](src/agent/graph.py)

D11 documented the sequential simplification. V2 upgrades to true parallelism:
`START → data_track` and `START → business_track` run concurrently, both fanning
into decision_match. LangGraph waits for both before invoking decision_match.

**Why**: The two tracks are genuinely independent (data track reads the file,
business track reads only the user requirement). Parallelism saves wall-clock
time proportional to the slower of the two LLM calls.

---

*Last updated: V2 Phase 4 complete. D21-D32 decisions documented.*
*Audit fix (2026-07-02): D33-D38 added.*

---

## D33 — Static guard: AST + regex dual-layer scanning

**Date**: 2026-07-02 | **Scope**: [src/sandbox/static_guard.py](src/sandbox/static_guard.py)

D2 accepted subprocess sandbox with no isolation. D17 added prompt-level constraints
but they're advisory only. D33 is the enforcement layer: every LLM-generated script
is scanned before it reaches `subprocess.run()`.

**Layer 1 — AST import scan**: `_ImportScanner(ast.NodeVisitor)` walks `Import`/`ImportFrom`
nodes, checks against `_BANNED_IMPORTS` (25 modules: network, subprocess, os, shutil,
pickle, ctypes, code, etc.). Also catches dotted imports (`urllib.request` → top-level
`urllib` is banned).

**Layer 2 — Regex pattern scan**: `_BANNED_PATTERNS` (regex list) catches dynamic calls
that AST can't see: `eval()`, `exec()`, `__import__()`, `os.system()`, `.unlink()`,
`shutil.rmtree`, `requests.post()`, etc.

**Why two layers**: AST alone can't catch `eval("os.system('rm -rf /')")` — there's
no import to block, the code is inside a string. Regex catches the pattern regardless
of how it materializes at runtime. But regex alone has false positives (comments,
strings). AST validates intent at the structural level. Together they're defense-in-depth.

**Integration**: Rejection triggers ReAct retry (max 3). The error message tells the
LLM exactly what was banned, giving it a chance to fix the code. Not a hard pipeline
failure.

---

## D34 — Input sanitization as outer defense layer

**Date**: 2026-07-02 | **Scope**: [src/__main__.py](src/__main__.py)

Before D34, user input (requirement + feedback) flowed raw into LLM prompts. An
adversarial prompt like `### SYSTEM: ignore previous instructions` would reach
code-gen prompts unchanged.

**Pipeline**: `_sanitize_user_input(text, max_len)` strips:
1. Prompt injection delimiters (markdown fences, `### SYSTEM/USER/ASSISTANT`,
   `<|im_start|>/<|im_end|>`, `[INST]`, etc.)
2. ASCII control chars below 0x20 (except `\n`, `\t`)
3. Collapses multiple whitespace to single space
4. Truncates to `max_len` (2000 for requirement, 1000 for feedback)

**Defense-in-depth**: D34 sanitizes user input at the entry point. D33 scans generated
code at the exit point. These are independent layers — bypassing one doesn't bypass
the other.

---

## D35 — Path validation: extension whitelist + traversal rejection

**Date**: 2026-07-02 | **Scope**: [src/__main__.py](src/__main__.py)

`_validate_file_path()` enforces three constraints before the file path reaches any
node: (1) extension must be `.csv`, `.xlsx`, or `.xls`; (2) file must exist;
(3) resolved path must be within CWD (`path.relative_to(cwd)` rejects `../../etc/passwd`).

**Why CWD-relative, not project-root**: The tool is a CLI — users may analyze files
in subdirectories, not just the project root. Restricting to CWD subtree is the
narrowest constraint that still allows reasonable use.

---

## D36 — `python-dotenv` replaces bespoke `.env` parser (revises D20)

**Date**: 2026-07-02 | **Scope**: [src/agent/llm.py](src/agent/llm.py)

D20 chose a ~15-line manual `.env` parser to avoid a dependency. The audit (H3) found
it had edge-case bugs: no support for multi-line values, escaped characters, or inline
comments. These bugs were silently swallowed by `except OSError: pass`.

**Decision**: Add `python-dotenv>=1.0.0` as a hard dependency. `_load_dotenv()` becomes
a thin wrapper: `load_dotenv(override=False)`. Same semantics (env vars win), zero
behavior change for users, but handles edge cases correctly.

**Why**: `python-dotenv` is pure Python, widely available, and effectively zero-cost
as a dependency. The manual parser was a premature optimization.

---

## D37 — atexit-based temp cleanup (supersedes D13)

**Date**: 2026-07-02 | **Scope**: [src/agent/utils.py](src/agent/utils.py)

D13 intentionally kept LLM-generated temp scripts for debugging. D37 reverses that:
all temp files and directories created by `preprocessing` and `analysis` nodes are
registered via `register_temp_path()` and cleaned up at process exit via `atexit`.

**Why the reversal**: Accumulation was worse than anticipated — every run creates
2+ temp dirs and 1+ scripts per attempt. `--save-intermediates` already preserves
artifacts for debugging (scripts, charts, stdout), so the temp originals are redundant
once the run completes.

**What gets cleaned**: `tempfile.mkdtemp()` output directories (chart/cleaned-data
output) and `tempfile.mkstemp()` script files. Only paths created by the current
process are registered — existing paths from state reuse are not re-registered.

**Trade-off**: If the process hard-crashes (`kill -9`), `atexit` won't fire.
OS-level temp cleanup handles this eventually.

---

## D38 — Shared utility module for cross-node helpers

**Date**: 2026-07-02 | **Scope**: [src/agent/utils.py](src/agent/utils.py)

`_extract_code_block` was defined identically in `preprocessing.py` and `analysis.py`
(H9). `register_temp_path`/`_cleanup_temp_paths` is needed by both nodes (H5).

**Decision**: Create `src/agent/utils.py` as the single home for shared node helpers.
Two functions currently: `_extract_code_block` and `register_temp_path`. Module also
holds the atexit-registered `_cleanup_temp_paths` and the `_TEMP_PATHS` list.

**Scope rule**: Only functions used by 2+ nodes belong here. Node-specific helpers
stay in their respective files. This is NOT a "dump everything" module.

---

## D27 — V2: Unified `make_execution_plan` factory over per-test helpers

**Date**: V2 Phase 4 | **Scope**: tests/conftest.py, tests/test_*.py

Phase 3-4 中三个测试文件各自定义了 `_make_plan()` helper，签名和行为不一致：
`test_preprocessing.py` 使用 `[] or [default]` 模式（空列表是 falsy，默认值始终生效），
`test_execution.py` 和 `test_graph.py` 使用硬编码 `[]`。这种分歧直接导致了 L1 bug。

**决策**：在 `tests/conftest.py` 中提供 `make_execution_plan(**overrides)` fixture，
使用 `is not None` 模式处理所有 Optional 集合字段。各测试文件中的独立 `_make_plan()`
全部替换。

**Why**: 统一工厂消除签名歧义，确保所有测试使用相同的默认值语义。
`is not None` 是 Python `Optional[list]` 字段唯一正确的默认值模式。

**Implementation**: Phase 5a 完成。

---

## D28 — V2: Deprecate global `_EXECUTION_PLAN_JSON`

**Date**: V2 Phase 4 | **Scope**: tests/test_graph.py

`tests/test_graph.py` 中的 `_EXECUTION_PLAN_JSON` 是模块级常量，7 个集成测试共享。
当 preprocessing_steps 为空时，4 个测试的 mock 断言与 skip 路径不匹配（L3）。
修改字段会级联影响所有共享该常量的测试。

**决策**：删除 `_EXECUTION_PLAN_JSON` 和 `_REVISED_PLAN_JSON` 全局常量。
每个集成测试通过 `make_execution_plan(preprocessing_steps=[...], analysis_steps=[...])`
显式声明所需 plan。

**Why**: 显式构造使每个测试的意图可见且独立。一个测试的 plan 修改不会影响其他测试。
测试可以精确控制是否触发 skip 路径。

**Trade-off**: 测试代码会略长（每个测试显式传参）。收益远大于成本。

**Implementation**: Phase 5a 完成。

---

## D29 — V2: Mandatory `set_llm_env` on all node tests

**Date**: V2 Phase 4 | **Scope**: all tests/test_*.py

L1+L2 的组合故障暴露了一个防御缺口：`test_preprocessing_node_no_steps_skips`
未声明 `set_llm_env`。L1 bug 导致 LLM 路径被意外触发，OpenAI SDK 直接报 401。
双重叠加使排查多绕了一圈。

**决策**：所有函数名包含 `_node_` 且带 `set_llm_env` fixture 的测试函数，
**必须**声明 `set_llm_env` 参数，无例外。即使当前代码路径理论上不会调 LLM。

**Why**: 前置防御成本极低（一个 fixture 参数），收益是防止真实 API key 消耗
和 401 噪音。skip 分支可能因未来的 bug 或代码变更而不触发——不能依赖"LLM 不会被调"
的假设作为安全网。

**Enforcement**: Phase 5a 审查所有测试，添加遗漏的 fixture 声明。

---

## D30 — V2: Smoke test for real sandbox execution

**Date**: V2 Phase 4 | **Scope**: tests/test_smoke.py (new)

当前所有测试都 mock 了 `run_script`，沙箱执行路径零覆盖。pandas 版本差异、
编码问题、依赖缺失都只会在生产端到端运行时暴露。

**决策**：新增 `tests/test_smoke.py`，mock LLM（返回固定的清洗/分析脚本），
但**不 mock `run_script`**。验证 LLM 生成的代码可在真实 Python subprocess 中运行。

**Why**: Mock 沙箱意味着"我们信任 LLM 生成正确代码且环境兼容"。
这个假设已经被 history 打破（122K 行数据上的 `.iterrows()` 导致超时）。
真实 subprocess 测试是唯一的防线。

**Scope**: Smoke test 不需要跑完整的 LLM pipeline — LLM 输出是 mock 的。
只验证 subprocess 执行路径：进程启动、编码检测、超时机制、JSON 输出解析。

**Implementation**: Phase 5a 完成骨架，5b+6 扩展覆盖。

---

## D31 — V2: Remove `contextlib.suppress(NotImplementedError)` from graph tests

**Date**: V2 Phase 4 | **Scope**: tests/test_graph.py

`test_graph_data_track_integration` 使用 `contextlib.suppress(NotImplementedError)`
吞掉 graph.invoke 中未 mock 节点的错误。这是 D6（占位 stub 抛 NotImplementedError
做 fail-fast）的遗留产物。

**决策**：Phase 5a 中移除该 suppress。graph.invoke 集成测试必须 mock 链上所有节点
的 LLM 和 sandbox，确保每个节点都被显式验证。

**Why**: 如果新插入节点未正确 mock，测试应该失败——而不是被 suppress 悄悄吞掉。
这正是 Phase 4 初期 mock_pre 未生效但没被发现的原因。

**How**: mock report_gen 节点的 LLM（简单返回 `"# Report\n\nTest."`），
移除 `contextlib.suppress`。

---

## D32 — V2: Phase 5a (debt repayment) before Phase 5b (analysis node)

**Date**: V2 Phase 4 | **Scope**: scheduling / implementation order

L1 和 L3 在 Phase 5 会完全重现：`analysis_steps=[]` 导致 analysis 节点 skip，
mock 断言再次不匹配，`set_llm_env` 可能再次缺失。

**决策**：Phase 5 分为两个子阶段：
- Phase 5a — D27-D31 的债务清偿 + conftest 重构，测试数 78 → ~82
- Phase 5b — analysis 节点开发，测试数 ~82 → ~92

Phase 5a 必须在 5b 之前完成并全绿。

**Why**: 避免同样的错误模式反复出现。先清偿债务，再在新功能上验证防御措施有效。
这是"先修地基，再盖楼"——而不是在脆弱的基础上加高楼层。

**Risk**: 如果 Phase 5a 范围膨胀，可能 delay 5b。Mitigation: 5a scope 严格限定
为 D27-D31，不涉及任何 src/ 逻辑变更。
