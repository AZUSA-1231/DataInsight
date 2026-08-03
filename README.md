# DataInsight

DataInsight is a local, single-user data analysis workspace for turning CSV or
Excel data and a business question into an inspectable analysis plan, a
re-runnable execution DAG, charts, and a Markdown report.

The project deliberately separates business intent from execution. The LLM
does not jump directly from a question to a report: data is inspected first,
the workspace plan is reviewed, and every execution unit follows a structured
data contract.

## Current Architecture

```text
START
  -> data_track       deterministic inspection for the graph launcher
  -> business_track   Snapshot-aware business instruction
  -> planner          validated operation-specific Plan v2
  -> analysis         Snapshot/Checkpoint DAG execution
  -> report_gen       Markdown report with lineage and warnings
  -> END

feedback -> business_track -> planner -> analysis -> report_gen
```

The API and browser workflow additionally normalize each uploaded source to
Parquet and register its Source, Snapshot, Checkpoint, and Column Graph nodes.
Analysis units use one of four v2 contracts:

| Unit | Contract | Execution |
|---|---|---|
| Derive | add one declared column, preserve row identity | template or restricted generated function |
| Filter | return a named subset Snapshot, preserve columns | template or restricted generated function |
| Join | select aliased columns from two Snapshots | deterministic pandas executor |
| Terminal | produce charts or other artifacts | template or subprocess sandbox |

Data moves between units through Parquet checkpoints. Runtime session state is
stored in `data/sessions/{session_id}/state.json`; checkpoints and artifacts are
stored below `data/output/{session_id}/`.

## Web Workspace

Install the API dependencies and start the local server:

```bash
pip install -e ".[dev,web]"
uvicorn src.api.app:app --reload
```

Open `http://127.0.0.1:8000`. The zero-build frontend supports multi-file
upload, source/Snapshot grouping, qualified-column selection,
operation-specific workspace editing, dialogue, execution, warning and
stale-state display, rerun, dashboard pins, and report generation. The active
session is restored after a server or browser restart.

The web workspace is the supported application surface. The former one-file
CLI was retired because it could not provide the same Snapshot, Checkpoint,
and column-first editing model as the browser.

## LLM Configuration

Copy `.env.example` to `.env` and provide an OpenAI-compatible endpoint:

```dotenv
DATAINSIGHT_LLM_MODEL=your-default-model
DATAINSIGHT_LLM_API_KEY=your-key
DATAINSIGHT_LLM_BASE_URL=https://example.com/v1
```

Optional stage overrides include `DATAINSIGHT_LLM_MODEL_PLANNER`,
`DATAINSIGHT_LLM_MODEL_ANALYSIS_TRANSFORM`, and
`DATAINSIGHT_LLM_MODEL_ANALYSIS_TERMINAL`.

## Validation

```bash
pytest -q
ruff check .
mypy src/
```

Cycle 5 validation evidence is recorded in
`docs/cycles/cycle-5-column-lineage/summary.md`.

## Repository Map

```text
src/agent/              state, graph, planner, DAG, templates, execution nodes
src/api/                FastAPI session-scoped workspace API
src/sandbox/            deterministic inspection and terminal subprocess runner
static/                 zero-build browser workspace
tests/                  unit, integration, and API tests
docs/                   current product, architecture, and roadmap documents
docs/cycles/            cycle summaries and archived PRDs/plans
.claude/archive/        historical Cycle 1-4 Claude Code artifacts
```

## Security Boundary

DataInsight is currently designed for a trusted, local, single-user workflow.
Transform and Filter code is statically checked and executed with restricted
builtins, but it is not an operating-system sandbox. Terminal code retains a
subprocess timeout. Do not expose the current API directly to untrusted users.
