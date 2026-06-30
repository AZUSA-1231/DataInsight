# DataInsight — Session Summary

**Date**: 2026-06-30 | **State**: V2 Phase 0 (Pydantic Migration) | **Tests**: 52/52 passing

## What This Project Is

DataInsight is an LLM-driven data analysis agent that enforces a mandatory
four-stage LangGraph state machine. Given a CSV/Excel file and a natural-language
requirement, it produces a Markdown analysis report with charts.

## Quick Start (next session)

```bash
cd d:/Projects/Agents
conda activate datainsight

# 1. Create .env from template (one-time setup)
copy .env.example .env
# Edit .env: set MODEL, API_KEY, BASE_URL

# 2. Run
python -m src data.csv "analysis question" -s -v

# 3. Find output
# - Report: data_analysis_report.md
# - All artifacts + charts: data_analysis_report_intermediates/
```

## Current State

**V2 First Major Update in progress** — See [.claude/plans/data-insight-agent-v2.plan.md](.claude/plans/data-insight-agent-v2.plan.md)

### V2 Phases

| # | Phase | Status |
|---|-------|--------|
| 0 | Pydantic Migration (TypedDict → BaseModel) | **in-progress** |
| 1 | Parallel Track + Data Track Simplification | pending |
| 2 | Business Track → Intent Parser | pending |
| 3 | Decision Match → Planner (model selection) | pending |
| 4 | Execution Split — Preprocessing node | pending |
| 5 | Execution Split — Analysis node | pending |
| 6 | Report Gen Redesign | pending |

### V2 Key Design Decisions

See [.claude/decisions.md](.claude/decisions.md) entries D21-D26.

## Architecture (MVP, pre-V2)

```
CLI (__main__.py)
  └─ 5-node LangGraph pipeline:
       1. data_track      — deterministic CSV inspection (subprocess) + LLM audit
       2. business_track  — pure LLM business reasoning (no data access)
       3. decision_match  — LLM aligns data reality with business intent
       4. execution       — LLM writes Python → subprocess sandbox → ReAct retry (max 3)
       5. report_gen      — LLM assembles Markdown report (full or partial on error)
     + 2 conditional edges:
       - ReAct: execution → execution (on error, retry < 3) or report_gen
       - Feedback: report_gen → decision_match (if user provides feedback in CLI)
```

## Key Files

| File | Purpose |
|------|---------|
| [src/__main__.py](src/__main__.py) | CLI entry: argparse, streaming progress, feedback loop |
| [src/agent/graph.py](src/agent/graph.py) | StateGraph construction, conditional edge functions |
| [src/agent/state.py](src/agent/state.py) | AgentState (TypedDict → being migrated to Pydantic) |
| [src/agent/llm.py](src/agent/llm.py) | `get_llm()` factory; `_load_dotenv()` reads `.env` |
| [src/agent/nodes/data_track.py](src/agent/nodes/data_track.py) | Stage 1a: sandbox inspection + LLM audit |
| [src/agent/nodes/business_track.py](src/agent/nodes/business_track.py) | Stage 1b: pure LLM business reasoning |
| [src/agent/nodes/decision_match.py](src/agent/nodes/decision_match.py) | Stage 2: alignment + feedback-based revision |
| [src/agent/nodes/execution.py](src/agent/nodes/execution.py) | Stage 3: code gen + sandbox + ReAct (being split) |
| [src/agent/nodes/report_gen.py](src/agent/nodes/report_gen.py) | Stage 4: full or partial Markdown report |
| [src/sandbox/inspection_script.py](src/sandbox/inspection_script.py) | Deterministic data inspection (NEVER LLM-generated) |
| [src/sandbox/executor.py](src/sandbox/executor.py) | subprocess sandbox with 120s timeout |
| [.claude/plans/data-insight-agent-v2.plan.md](.claude/plans/data-insight-agent-v2.plan.md) | V2 implementation plan |
| [.claude/decisions.md](.claude/decisions.md) | 26 architecture decisions (D1-D26) |

## Validation Commands

```bash
ruff check .          # lint (must pass: 0 issues)
mypy src/             # type check (must pass: strict clean)
pytest -v             # tests (must pass: all green)
pytest -v -m unit     # unit only
pytest -v -m integration  # integration only
```

## Git Commits (V2)

None yet — work about to begin.
