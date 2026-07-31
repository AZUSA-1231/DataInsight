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
  -> data_track       deterministic profile and unified columns
  -> business_track   workspace-aware business instruction
  -> planner          validated Plan with DAG units
  -> analysis         topological unit execution and checkpoints
  -> report_gen       Markdown report and alignment notes
  -> END

feedback -> business_track -> planner -> analysis -> report_gen
```

Analysis units use one of three contracts:

| Unit | Contract | Execution |
|---|---|---|
| Transform | add declared columns, preserve row identity | template or restricted generated function |
| Filter | return a named subset snapshot, preserve columns | template or restricted generated function |
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

Open `http://127.0.0.1:8000`. The zero-build frontend supports upload, field
selection, workspace editing, dialogue, execution, dashboard pins, and report
generation. The active session is restored after a server or browser restart.

## CLI

```bash
pip install -e ".[dev]"
python -m src sales.csv "Why did Q2 sales drop?"
```

Useful options:

| Flag | Purpose |
|---|---|
| `-o`, `--output` | Markdown output path |
| `-s`, `--save-intermediates` | Save prompts, scripts, and charts |
| `-v`, `--verbose` | Enable debug logging |

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

The Cycle 4 closure baseline is 269 passing tests, clean Ruff output, and clean
strict mypy output.

## Repository Map

```text
src/agent/              state, graph, planner, DAG, templates, execution nodes
src/api/                FastAPI session-scoped workspace API
src/sandbox/            deterministic inspection and terminal subprocess runner
static/                 zero-build browser workspace
tests/                  unit, integration, and API tests
docs/                   current product, architecture, and roadmap documents
.claude/archive/        historical Cycle 1-4 development artifacts
```

## Security Boundary

DataInsight is currently designed for a trusted, local, single-user workflow.
Transform and Filter code is statically checked and executed with restricted
builtins, but it is not an operating-system sandbox. Terminal code retains a
subprocess timeout. Do not expose the current API directly to untrusted users.
