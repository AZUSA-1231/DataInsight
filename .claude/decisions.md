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

*Last updated: M4 complete. DataInsight MVP is feature-complete.*
