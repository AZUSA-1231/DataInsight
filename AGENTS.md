# DataInsight Agent Guide

## Purpose

DataInsight is a local, single-user analysis workspace. Preserve its central
product boundary: data inspection, business reasoning, planning, execution,
and reporting are separate stages. Do not collapse the workflow into a generic
chat-to-code path.

## Read First

1. `README.md` for commands and the current product surface.
2. `docs/product/vision.md` for product intent and non-goals.
3. `docs/architecture/current.md` for runtime contracts and persistence.
4. `docs/roadmap.md` before starting a new cycle or feature.

Historical PRDs, plans, decisions, and session summaries are under
`docs/cycles/` for Cycle 5 onward. Earlier Claude Code artifacts remain under
`.claude/archive/`. They explain why the architecture exists but are not the
source of truth for current code behavior.

## Engineering Rules

- Python 3.12+, Pydantic state, FastAPI, LangGraph, pandas.
- Nodes return partial immutable state updates; do not mutate `AgentState`.
- `Plan` describes intent. Execution metadata belongs in `analysis_result`.
- Transform units preserve row count and row index.
- Filter units preserve columns and return an indexed subset.
- Terminal units are DAG leaves and produce artifacts only.
- Persist durable JSON references, never live DataFrames. Result keys beginning
  with `_` are executor-only and must not be persisted.
- API executions write below `data/output/{session_id}/`.
- Keep the application single-user unless a future PRD explicitly changes that
  boundary.

## Validation

Run before completing any implementation milestone:

```bash
pytest -q
ruff check .
mypy src/
```

For frontend changes also run `node --check static/app.js` and verify the local
workspace in a browser.

## Documentation Workflow

Current, tool-neutral documentation lives in `docs/`. A new development cycle
starts with one product-level PRD and an implementation plan sized to a fully
usable increment. At cycle closure:

1. Record decisions that changed the architecture.
2. Write a cycle summary with validation evidence and deferred work.
3. Move detailed PRDs/plans into `docs/cycles/<cycle>/archive/` for historical
   use. Keep the cycle summary and development issues alongside that archive.
4. Update `docs/architecture/current.md` and `docs/roadmap.md`.
