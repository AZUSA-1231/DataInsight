# DataInsight — Session Summary

**Date**: 2026-06-29 | **State**: Post-MVP hardening | **Tests**: 52/52 passing

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

## Architecture (simplified)

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
| [src/__main__.py](src/__main__.py) | CLI entry: argparse, streaming progress, feedback loop, `_save_intermediates` |
| [src/agent/graph.py](src/agent/graph.py) | StateGraph construction, 2 conditional edge functions |
| [src/agent/state.py](src/agent/state.py) | AgentState TypedDict (9 fields, immutable) |
| [src/agent/llm.py](src/agent/llm.py) | `get_llm()` factory; `_load_dotenv()` reads `.env` |
| [src/agent/nodes/data_track.py](src/agent/nodes/data_track.py) | Stage 1a: sandbox inspection + LLM audit (Chinese prompt, 5 sections) |
| [src/agent/nodes/business_track.py](src/agent/nodes/business_track.py) | Stage 1b: pure LLM business reasoning (must NOT see data) |
| [src/agent/nodes/decision_match.py](src/agent/nodes/decision_match.py) | Stage 2: alignment + feedback-based revision |
| [src/agent/nodes/execution.py](src/agent/nodes/execution.py) | Stage 3: code gen + sandbox + ReAct (most complex node) |
| [src/agent/nodes/report_gen.py](src/agent/nodes/report_gen.py) | Stage 4: full or partial Markdown report |
| [src/sandbox/inspection_script.py](src/sandbox/inspection_script.py) | Deterministic data inspection (NEVER LLM-generated) |
| [src/sandbox/executor.py](src/sandbox/executor.py) | subprocess sandbox with 120s timeout, UTF-8 + replace errors |
| [.env.example](.env.example) | Template for LLM configuration |
| [pyproject.toml](pyproject.toml) | Dependencies, scripts, tool config |
| [CLAUDE.md](CLAUDE.md) | Full developer reference |
| [.claude/decisions.md](.claude/decisions.md) | 20 architecture decisions (D1-D20) |

## What Works

- Full 4-stage pipeline with streaming progress display
- OpenAI-compatible LLM backends (DeepSeek, Qwen, etc.) via `.env` config
- ReAct self-correction on execution errors (max 3 retries)
- In-session feedback iteration (user types feedback → report regenerated)
- `--save-intermediates` saves all artifacts including chart images
- `--verbose` / `-v` for debug logging
- UTF-8/GBK encoding tolerance on Windows

## Known Fragilities

1. **LLM code quality varies per run** — some runs generate all 3 chart types, others
   only 1. The prompt bans `.iterrows()` but it's advisory, not enforced.
2. **122K-row datasets push the 120s timeout** — if LLM ignores vectorization hints
   and generates Python loops, execution times out.
3. **No chart deduplication** — charts are copied to both temp dir and intermediates.
4. **No node-level response caching** — feedback iteration re-invokes LLM for every node.
5. **Single LLM provider** — only OpenAI-compatible APIs (no Anthropic/Gemini).

## Validation Commands

```bash
ruff check .          # lint (must pass: 0 issues)
mypy src/             # type check (must pass: strict clean)
pytest -v             # 52 tests (must pass: all green)
pytest -v -m unit     # unit only
pytest -v -m integration  # integration only
```

## Where to Go Next

**Immediate improvements** (low risk, high value):
- Add a static check that rejects generated scripts containing `.iterrows()` before
  execution (enforce D17 programmatically, not just via prompt nudge)
- Increase timeout for large datasets, or make it configurable (`--timeout`)
- Add `chardet` for automatic encoding detection

**Medium-term**:
- True parallel dual-track (Send API) — see D11
- Progress bars or richer streaming output
- Persistent session history across CLI invocations

**Long-term**:
- Web frontend for report viewing
- Multi-provider LLM support (Anthropic, Gemini)
- Docker sandbox for real isolation
