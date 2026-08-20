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
upload/profile -> workspace Plan v2 -> execution DAG -> report

chat -> bounded Copilot turn -> inspect/propose -> chat response
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

For frontend development, run the Vite workspace in a second terminal:

```bash
cd frontend
npm ci
npm run dev
```

Open `http://127.0.0.1:5173`. The M2 React shell provides server-backed
Project history, Project creation, switching, durable rename, and stable
Explorer, Plan Canvas, Agent, and Output Dock mounting regions. M3 connects
Plan Canvas to the canonical Plan v2 DAG with durable presentation layout and
server-confirmed dependency edge edits. M4 connects the Explorer to public
Sources/Snapshots/profile projections and typed operation editing. Vite proxies
`/api` requests to FastAPI. To build the production frontend into FastAPI's
existing `static/` mount, run `npm run build` from `frontend/`, then open
`http://127.0.0.1:8000`.

The React/Vite workspace is the supported browser surface. The Agent panel is
Project-local and Thread-isolated. The Output Dock connects execution polling,
unit results, warnings, charts, unit/cascade reruns, and retained Markdown
reports. Its Dashboard tab is an explicit deferred placeholder; the React
client does not call the compatibility dashboard pin routes. The production
build is served from FastAPI's `static/` mount, and the former zero-build
`static/app.js` and `static/styles.css` entry are retired.
The former one-file CLI was retired because it could not provide the same
Snapshot, Checkpoint, and column-first editing model as the browser.

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
cd frontend
npm ci
npm run typecheck
npm run lint
npm run test
npm run build
cd ..
git diff --check
```

GitHub Actions runs the same backend and frontend checks on Python 3.12 and
3.13, with the web extra installed, Ruff pinned to `0.16.3`, and the frontend
dependencies resolved from `frontend/package-lock.json`.

Cycle 5 validation evidence is recorded in
`docs/cycles/cycle-5-column-lineage/summary.md`.

## Repository Map

```text
src/agent/              state, graph, planner, DAG, templates, execution nodes
src/api/                FastAPI session-scoped workspace API
src/sandbox/            deterministic inspection and terminal subprocess runner
frontend/               React, TypeScript, and Vite workspace source
static/                 generated Vite production frontend served by FastAPI
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
