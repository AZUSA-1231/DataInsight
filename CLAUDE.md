# CLAUDE.md — DataInsight

DataInsight is an LLM-driven data analysis agent that enforces a mandatory
four-stage LangGraph state machine: Data Track → Business Track → Decision
Match → Sandbox Execution → Report Generation.

## Stack

- Python 3.12+
- LangGraph 1.0+ (StateGraph with CompiledStateGraph)
- LangChain / langchain-openai (LLM abstraction)
- Pandas, NumPy, Matplotlib (data processing & visualization)

## Build & Test Commands

- Install: `pip install -e ".[dev]"`
- Run: `python -m src <file_path> "<requirement>"`
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
├── __main__.py              ← CLI (argparse, feedback loop)
├── agent/
│   ├── state.py             ← AgentState TypedDict (immutable)
│   ├── graph.py             ← 5-node StateGraph + 2 conditional edges
│   ├── llm.py               ← get_llm() factory (env-var driven)
│   └── nodes/
│       ├── data_track.py    ← Sandbox inspection + LLM audit
│       ├── business_track.py← Pure LLM business reasoning
│       ├── decision_match.py← LLM alignment + feedback handling
│       ├── execution.py     ← LLM code gen + sandbox + ReAct retry
│       └── report_gen.py    ← LLM report assembly (full/partial)
├── sandbox/
│   ├── inspection_script.py ← Deterministic (never LLM-generated)
│   └── executor.py          ← subprocess.run with 120s timeout
tests/                       ← 52 tests, mirrors src/
```

## Key Conventions

- **Immutability**: nodes return `{**state, "key": value}`, never mutate
- **Error signaling**: `state["error"]` string, never raise from nodes
- **LLM calls**: `get_llm(temperature=0)` → `.invoke(prompt)` → `.content`
- **Prompts**: Chinese f-strings in `_build_*_prompt()` helpers
- **Logging**: `logger.info()` on entry/exit, `logger.error()` on failure
- **TypedDict**: `AgentState` uses `NotRequired` for optional fields
- **ReAct retry**: conditional edge back to execution (max 3, counter in state)
- **Feedback**: conditional edge from report_gen to decision_match (consumed on use)
