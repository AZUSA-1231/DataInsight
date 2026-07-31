# Current Architecture

## Pipeline

LangGraph orchestrates five state transitions:

```text
data_track -> business_track -> planner -> analysis -> report_gen
                 ^                                  |
                 +------------- feedback -----------+
```

- `data_track` deterministically profiles one CSV or Excel file.
- `business_track` converts dialogue plus the current workspace into a
  `PlannerInstruction`.
- `planner` is the only producer of the executable `Plan`.
- `analysis` executes PlanUnits in topological levels, with parallel units
  inside one level.
- `report_gen` turns persisted results into a Markdown report with mandatory
  data-business alignment notes.

## Unit Contracts

`PlanUnit` has three types and two execution modes.

| Type | Durable effect | Hard invariant |
|---|---|---|
| Transform | adds declared columns to a checkpoint | same row count and index |
| Filter | creates a named snapshot branch | same columns; indexed row subset |
| Terminal | creates artifact files | no columns or snapshots |

Template and generated Transform/Filter functions share the same return
contract. Contract validation happens before a checkpoint is accepted.

## Execution Boundaries

- Template units run as trusted in-process functions.
- Generated Transform/Filter units are statically checked, compiled with a
  restricted namespace, and retried up to three times on compilation,
  execution, or contract failure.
- Generated Terminal units run as standalone subprocess scripts with a timeout.

The in-process path is a trusted-local optimization, not an OS security
sandbox. The API must not be exposed to untrusted users without a stronger
worker isolation design.

## Data Flow

The executor does not concatenate unit CSV files. Each branch advances through
complete Parquet checkpoints:

```text
checkpoints/wide_l0.parquet
checkpoints/wide_l1.parquet
checkpoints/snapshots/recent_l0.parquet
checkpoints/snapshots/recent_l1.parquet
```

Terminal artifacts live in their unit output directory. Single-unit reruns
resolve their input checkpoint from disk and either mark transitive dependents
stale or rerun them as a cascade.

## Persistence

`SessionStore` keeps an in-memory cache backed by
`data/sessions/{session_id}/state.json`. Creates and updates are saved
atomically. A new process lazily loads a session on first access.

Executor-only result keys beginning with `_`, including live DataFrames, are
removed before JSON serialization. Durable source code, model names, insights,
chart references, plans, pins, and reports remain in the state file.

API execution output is stable under `data/output/{session_id}/analysis/`.
Chart responses expose only paths relative to the session output root.

## Interfaces

- CLI: full graph execution plus interactive feedback.
- FastAPI: session-scoped node and workspace endpoints.
- Browser workspace: zero-build HTML/CSS/JS served by FastAPI.

The browser restores a session from the URL or local storage. A new session
does not delete prior persisted work; an old session can be reopened with
`/?session={session_id}`.
