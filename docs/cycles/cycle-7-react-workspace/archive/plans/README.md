# Cycle 7 Implementation Plan Index

Cycle 7 is implemented as six bounded milestones. The order below is the
default sequence; M3, M4, and M5 may overlap after M1 and M2 when their API
fixtures are stable. Each milestone must leave the previous user path usable.

| ID | Plan | Depends on | Status |
|---|---|---|---|
| M1 | [Project state, history, and Agent threads](01-project-session-and-agent-threads.md) | Cycle 6 audited baseline | Implemented |
| M2 | [Vite shell and Project history UI](02-vite-shell-and-project-history.md) | M1 | Implemented |
| M3 | [Plan Canvas mapping and Workspace layout](03-plan-canvas-mapping-and-layout.md) | M1, M2 | Implemented |
| M4 | [Explorer, operation editor, and drag and drop](04-explorer-operation-editor-and-drag-drop.md) | M1, M2, M3 | Implemented |
| M5 | [Agent panel and thread isolation](05-agent-panel-thread-isolation.md) | M1, M2 | Implemented |
| M6 | [Output Dock integration and cycle closure](06-output-dock-integration-and-cycle-closure.md) | M2, M3, M4, M5 | Implemented |

## Dependency Shape

```text
M1 Project/API foundation
       |
       +--> M2 React shell and Project switcher
                 |
                 +--> M3 Plan Canvas mapping/layout
                 |          |
                 |          +--> M4 Explorer and operation editing
                 |
                 +--> M5 Agent panel and thread context
                              |
                              +--> M6 Output Dock, browser evidence, closure
```

M3 and M5 share the M2 shell but do not share semantic state. M4 may begin
once the pure Plan Canvas mapper and operation request types are available.

## Existing API Inventory

This is the Cycle 7 connection checklist. Route names retain `session_id` for
backend compatibility; the UI labels that scope as `Project`.

| API group | Current routes | Cycle 7 destination | Status |
|---|---|---|---|
| Project/session | `POST /api/sessions`, `GET /api/sessions/{id}`, `DELETE /api/sessions/{id}` | Header history, create, active Project summary | Add list/rename; deletion remains hidden |
| Data | `POST /data/upload`, `GET /data/profile`, `/data/columns`, `/data/sources`, `/data/snapshots`, `/data/lineage` | Explorer upload, Source/Snapshot tree, profile, qualified-column drag payloads | Explorer read/upload routes implemented |
| Plan/workspace | `GET/PUT/DELETE /workspace`, `POST/PUT/DELETE /workspace/units`, `GET/PUT /workspace/layout`, `POST /plan/generate` | Plan Canvas and operation inspector | Canvas mapping/layout and M4 operation editing implemented |
| Copilot | `POST /copilot` | Agent panel for the selected Thread | Selected-thread requests; bounded runtime retained |
| Compatibility dialogue | `POST /dialogue`, `POST /dialogue/stream`, `GET /dialogue/stream` | No React caller | Preserve or delegate through the M1 compatibility decision |
| Execution | `POST /execution/run`, `GET /execution/status`, `GET /execution/results`, `POST /execution/units/{id}/rerun`, `GET /execution/charts/{path}` | Output Dock Results tab | Connect and poll only for active Project |
| Report | `POST /report/generate`, `GET /report` | Output Dock Report tab | Connect generate/read |
| Dashboard compatibility | `GET /dashboard`, `POST /dashboard/pins`, `DELETE /dashboard/pins/{id}` | Blank Dashboard placeholder | Keep backend compatibility; React makes no calls |

New Project/thread/layout routes from M1 and M3 are listed in their detailed
contracts. Any endpoint not listed as a Cycle 7 destination must not be
silently reintroduced through a generic frontend service.

## Global Invariants

- The [glossary](../../../../glossary.md) is the vocabulary authority. `Project`
  means the existing durable Session; `Agent conversation` or `Thread` is a
  named conversation inside one Project.
- A Thread can see the active Project's workspace facts, but it can never see
  another Thread's messages. Projects share neither messages nor workspace
  state. Persistence location is not used as a substitute for this isolation
  rule.
- `AgentState.plan` is the only semantic authority for the Plan DAG. Every
  current Plan unit maps to exactly one Plan Canvas node with ID `unit:<id>`;
  every edge is derived from one `depends_on` relation.
- `WorkspaceLayout` stores presentation only: Unit-keyed positions, viewport,
  and harmless collapsed state. It cannot store operation fields, columns,
  dependencies, sources, results, or hidden IDs.
- A semantic Plan Canvas gesture calls an existing validated Plan API and then
  reconciles from the server response. A move, pan, zoom, or collapse action
  writes only Workspace layout. The client never maintains a second DAG.
- Qualified column references are the only column drag payload. Checkpoint
  IDs, Column Graph node IDs, hidden row IDs, live DataFrames, and filesystem
  paths never become browser entities.
- Cycle 7 does not implement Copilot Plan proposal Accept/Reject, Dashboard
  product behavior, Result Canvas / Board, authentication, Project deletion,
  or new operation/execution semantics.
- The application remains local and single-user. The header may show a fixed
  fake local user; no account or authorization model is added.
- API updates use immutable state patches and atomic persistence. Project
  changes, active-project switches, polling, and pending layout writes are
  scoped or cancelled when the active Project changes.

## Shared Validation

Every milestone runs its focused tests plus `git diff --check`. Cycle closure
must pass the repository gates:

```text
pytest -q
ruff check .
mypy src/
```

The new frontend must also provide package scripts for `typecheck`, `lint`,
and `build`. The final milestone runs all three and a browser smoke suite
against a local FastAPI server (desktop and a narrow desktop viewport). The
old `node --check static/app.js` check is retired when the zero-build frontend
is removed; the maintained TypeScript source is validated by the Vite scripts.

## Change Discipline

Plans describe implementation boundaries, not permission to broaden scope.
Keep existing Plan validation, execution, rerun, lineage, report, and bounded
Copilot limits authoritative. When an API response is insufficient, add a
small typed projection or adapter rather than exposing durable internals or
introducing a parallel runtime.
