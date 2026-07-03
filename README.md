# DataInsight — Progressive Data Analysis AI Agent

DataInsight is an LLM-driven data analysis agent that enforces a mandatory
**6-stage LangGraph state machine** before producing any report. It never
"blindly executes" — every analysis walks through inspect → reason → plan →
clean → analyze → report.

## Philosophy

Most AI data tools skip straight to code generation. DataInsight forces the
LLM to understand the data, derive business requirements, reconcile gaps, and
only then execute — producing reports that acknowledge what the data *can't*
answer as honestly as what it can.

## Architecture

```
START
  │
  ├─ Stage 1a: Data Track        ← deterministic inspection + LLM cleaning audit
  ├─ Stage 1b: Business Track    ← LLM derives structured AnalysisIntent
  ├─ Stage 2:  Planner           ← LLM aligns business intent with data reality
  ├─ Stage 3:  Preprocessing     ← LLM code gen → sandbox clean → ReAct retry
  ├─ Stage 4:  Analysis          ← N parallel units, each with ReAct retry (max 3)
  └─ Stage 5:  Report Gen        ← LLM assembles full/partial Markdown report
  │
  END
  │
  └─ Feedback loop: user feedback → Planner → Preprocessing → Analysis → Report
```

Every report includes a mandatory **Data & Business Alignment Notes** chapter
that explicitly calls out gaps between what the user asked and what the data
can actually answer.

## Quick Start

### 1. Install

```bash
pip install -e ".[dev]"
```

### 2. Configure LLM

Copy `.env.example` to `.env` and fill in your credentials:

```bash
DATAINSIGHT_LLM_MODEL=deepseek-v4-flash
DATAINSIGHT_LLM_API_KEY=sk-your-key-here
DATAINSIGHT_LLM_BASE_URL=https://api.deepseek.com/v1
DATAINSIGHT_LLM_TEMPERATURE=0
```

Per-node model overrides (optional):

```bash
DATAINSIGHT_LLM_MODEL_PLANNER=deepseek-v4-pro   # planner gets a stronger model
DATAINSIGHT_LLM_MODEL_ANALYSIS=deepseek-v4-flash
```

### 3. Run

```bash
python -m src sales.csv "Why did Q2 sales drop by 15%?"
```

Options:

| Flag | Description |
|------|-------------|
| `-o`, `--output` | Output Markdown path (default: `<input>_analysis_report.md`) |
| `-s`, `--save-intermediates` | Save all intermediate artifacts + chart images |
| `-v`, `--verbose` | Debug logging |

Output: `sales_analysis_report.md` with charts embedded inline.

### 4. Iterate

After seeing the report, type feedback:

```
Feedback (Enter to exit): The chart should use monthly data, not quarterly.
```

The agent re-plans from the Planner stage (reusing Data/Business Track results)
and generates a revised report.

## Supported File Formats

- `.csv` — with automatic encoding detection (utf-8, gbk, latin-1, etc.)
- `.xlsx` / `.xls` — first sheet

## Commands

```bash
# Run all tests (114 tests)
pytest -v

# Run specific test file
pytest -v tests/test_analysis.py

# Run tests by marker
pytest -v -m unit
pytest -v -m integration

# Lint & format & type check
ruff check .
ruff format .
mypy src/
```

## Project Structure

```
src/
├── __main__.py              ← CLI entry point (argparse, feedback loop)
├── agent/
│   ├── state.py             ← AgentState (Pydantic BaseModel, immutable)
│   ├── graph.py             ← LangGraph StateGraph (6 nodes + conditional edges)
│   ├── llm.py               ← LLM factory (env-var driven, per-node model override)
│   └── nodes/
│       ├── data_track.py    ← Stage 1a: deterministic inspection + LLM audit
│       ├── business_track.py← Stage 1b: pure business reasoning → AnalysisIntent
│       ├── planner.py       ← Stage 2:  data-business alignment → ExecutionPlan
│       ├── preprocessing.py ← Stage 3:  code gen + sandbox clean + ReAct retry
│       ├── analysis.py      ← Stage 4:  N parallel units, each ReAct retry (max 3)
│       └── report_gen.py    ← Stage 5:  Markdown report with embedded charts
├── sandbox/
│   ├── inspection_script.py ← Trusted deterministic script (never LLM-generated)
│   ├── static_guard.py      ← Static code safety checker (banned imports/patterns)
│   └── executor.py          ← subprocess.run sandbox (configurable timeout)
tests/                       ← 114 tests mirroring src/
```

## Requirements

- Python 3.12+
- LLM API key (OpenAI-compatible)

## License

MIT
