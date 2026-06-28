# DataInsight — Progressive Data Analysis AI Agent

DataInsight is an LLM-driven data analysis agent that enforces a mandatory
**4-stage LangGraph state machine** before producing any report. It never
"blindly executes" — every analysis walks through inspect → reason → align →
execute.

## Philosophy

Most AI data tools skip straight to code generation. DataInsight forces the
LLM to understand the data, derive business requirements, reconcile gaps, and
only then execute — producing reports that acknowledge what the data *can't*
answer as honestly as what it can.

## Architecture

```
START
  │
  ├─ Stage 1a: Data Track        ← deterministic script inspects CSV/Excel
  ├─ Stage 1b: Business Track    ← LLM derives ideal metrics from the question
  ├─ Stage 2:  Decision Match    ← LLM aligns business ideals with data reality
  ├─ Stage 3:  Execution         ← LLM generates Python → sandbox → ReAct retry
  └─ Stage 4:  Report Gen        ← LLM assembles full/partial Markdown report
  │
  END
  │
  └─ Feedback loop: user feedback → Stage 2 (skip 1a/1b) → Stage 3 → Stage 4
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

Set these environment variables (OpenAI-compatible API):

```bash
export DATAINSIGHT_LLM_MODEL="gpt-4o"
export DATAINSIGHT_LLM_API_KEY="sk-your-key-here"

# Optional: use a different provider
export DATAINSIGHT_LLM_BASE_URL="https://api.deepseek.com/v1"
export DATAINSIGHT_LLM_TEMPERATURE="0"
```

### 3. Run

```bash
python -m src sales.csv "Why did Q2 sales drop by 15%?"
```

The agent will:
1. **Inspect** the data (deterministic — no LLM hallucination)
2. **Analyze** your business question
3. **Align** what the data can do with what you want
4. **Execute** cleaning + EDA + charts in a sandbox
5. **Report** with a Markdown file and mandatory alignment notes

Output: `sales_analysis_report.md`

### 4. Iterate

After seeing the report, type feedback:

```
Feedback (Enter to exit): The chart should use monthly data, not quarterly.
```

The agent re-plans from Stage 2 (reusing Stage 1 results) and generates a
revised report: `sales_analysis_report_revised.md`

## Supported File Formats

- `.csv` — with automatic encoding detection (utf-8, gbk, latin-1, etc.)
- `.xlsx` / `.xls` — first sheet

## Commands

```bash
# Run all tests (52 tests)
pytest -v

# Run specific test file
pytest -v tests/test_execution.py

# Run tests by marker
pytest -v -m unit
pytest -v -m integration

# Lint & type check
ruff check .
ruff format --check .
mypy src/
```

## Project Structure

```
src/
├── __main__.py              ← CLI entry point
├── agent/
│   ├── state.py             ← Shared AgentState (TypedDict)
│   ├── graph.py             ← LangGraph state machine
│   ├── llm.py               ← LLM factory (env-var driven)
│   └── nodes/
│       ├── data_track.py    ← Stage 1a: deterministic inspection + LLM audit
│       ├── business_track.py← Stage 1b: pure business reasoning
│       ├── decision_match.py← Stage 2:  data-business alignment
│       ├── execution.py     ← Stage 3:  code gen + sandbox + ReAct retry
│       └── report_gen.py    ← Stage 4:  Markdown report assembly
├── sandbox/
│   ├── inspection_script.py ← Trusted deterministic script
│   └── executor.py          ← subprocess sandbox (120s timeout)
tests/                       ← 52 tests mirroring src/
```

## Design Decisions

See [.claude/decisions.md](.claude/decisions.md) for 15 architecture decision
records covering: TypedDict vs Pydantic, subprocess sandbox vs Docker,
sequential dual-track simplification, LLM code generation risk acceptance,
feedback loop design, and more.

## Requirements

- Python 3.12+
- LLM API key (OpenAI or compatible)

## License

TBD
