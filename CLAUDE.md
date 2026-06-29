# CLAUDE.md — DataInsight

DataInsight is an LLM-driven data analysis agent that enforces a mandatory
four-stage LangGraph state machine: Data Track → Business Track → Decision
Match → Sandbox Execution → Report Generation.

## Stack

- Python 3.12+
- LangGraph 1.0+ (StateGraph with CompiledStateGraph)
- LangChain / langchain-openai (LLM abstraction, OpenAI-compatible API)
- Pandas, NumPy, Matplotlib, scikit-learn, scipy (data processing & viz)

## Quick Start

- Install: `pip install -e ".[dev]"`
- Configure: `copy .env.example .env` then edit `.env` with your LLM credentials
  - Required: `DATAINSIGHT_LLM_MODEL`, `DATAINSIGHT_LLM_API_KEY`, `DATAINSIGHT_LLM_BASE_URL`
  - Optional: `DATAINSIGHT_LLM_TEMPERATURE` (default 0)
  - `.env` file is git-ignored; env vars override `.env` values
- Run: `python -m src <file_path> "<requirement>"`
  - `--output` / `-o` : output Markdown path (default: `<input>_analysis_report.md`)
  - `--save-intermediates` / `-s` : save all intermediate artifacts + chart images
  - `--verbose` / `-v` : debug logging
- Test: `pytest -v`
- Single test: `pytest -v -k "test_name"`
- Unit only: `pytest -v -m unit`
- Integration only: `pytest -v -m integration`
- Lint: `ruff check .`
- Format: `ruff format .`
- Type check: `mypy src/`

## Architecture

```
src/
├── __main__.py              ← CLI (argparse, streaming progress, feedback loop)
├── agent/
│   ├── state.py             ← AgentState TypedDict (immutable, 9 fields)
│   ├── graph.py             ← 5-node StateGraph + 2 conditional edges
│   ├── llm.py               ← get_llm() factory (.env-driven, OpenAI-compatible)
│   └── nodes/
│       ├── data_track.py    ← Deterministic sandbox inspection + LLM audit
│       ├── business_track.py← Pure LLM business reasoning
│       ├── decision_match.py← LLM data-business alignment + feedback handling
│       ├── execution.py     ← LLM code gen + subprocess sandbox + ReAct retry (max 3)
│       └── report_gen.py    ← LLM report assembly (full or partial on error)
├── sandbox/
│   ├── inspection_script.py ← Deterministic (never LLM-generated), encoding-tolerant
│   └── executor.py          ← subprocess.run with 120s timeout, UTF-8 + replace errors
tests/                       ← 52 tests (all passing), mirrors src/
```

## Pipeline Flow

```
START → data_track → business_track → decision_match → execution → report_gen → END
                                            ↑              ↑   ↓ (error)    ↑
                                            │              └── ReAct retry ──┘
                                            └── feedback iteration ──────────┘
```

## Key Conventions

- **Immutability**: nodes return `{**state, "key": value}`, never mutate
- **Error signaling**: `state["error"]` string, never raise from nodes
- **LLM calls**: `get_llm(temperature=0)` → `.invoke(prompt)` → `.content`
- **Prompts**: Chinese f-strings in `_build_*_prompt()` helpers
- **Logging**: `logger.info()` on entry/exit, `logger.error()` on failure
- **TypedDict**: `AgentState` uses `NotRequired` for optional fields
- **ReAct retry**: conditional edge back to execution (max 3, retry_count in state)
- **Feedback**: conditional edge from report_gen to decision_match (consumed on use)
- **Subprocess**: `errors="replace"` on UTF-8 decode (Windows GBK tolerance)

## Post-MVP Hardening (already applied)

- **UTF-8/GBK encoding**: subprocess uses `errors="replace"`, `or ""` guards prevent
  `'NoneType' has no attribute 'strip'` pipeline crash on Windows
- **Code-gen prompt constraints**: banned `.iterrows()` / nested for loops for >10K
  rows; require vectorized pandas (groupby, pivot_table, .explode())
- **ReAct timeout case**: prompt explicitly tells LLM to switch to vectorized ops or
  sample to 30K rows on timeout
- **Chart persistence**: `--save-intermediates` copies generated .png files from
  temp sandbox dir into `<output>_intermediates/charts/`
- **Dependency policy**: scikit-learn and scipy are pre-installed (not left for LLM
  to discover at runtime)

## Known Fragile Points

- LLM-generated code quality varies significantly across runs — some runs produce
  all 3 chart types, others only 1 (regression survives because it's vectorized)
- 122K-row datasets push the 120s timeout when LLM generates Python loops
- `final_script.py` saved by `--save-intermediates` is from the LAST successful run;
  intermediate failed attempts are in `script_attempt_N.py`
- Feedback iteration re-runs from decision_match (skipping data/business tracks),
  but there is no per-node response caching — every iteration re-invokes the LLM
