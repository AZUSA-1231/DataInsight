# M6: Output Dock Integration and Cycle Closure

## Objective

Connect the existing execution, rerun, chart, and report APIs to a collapsible
Output Dock at the bottom of the center workspace, add an intentionally blank
Dashboard placeholder, run the full Cycle 7 acceptance workflow, and retire
the old zero-build frontend as the supported browser surface. This is the
integration and evidence milestone, not a place to redesign execution or
Dashboard semantics.

## Dependencies and Boundary

- Depends on: M2 shell, M3 canonical Plan Canvas, M4 operation editing and
  data projections, and M5 Project/thread lifecycle.
- Reuses: existing execution, rerun, chart-serving, report, and compatibility
  dashboard routes from Cycle 5/6.
- Does not implement: Result Canvas / Board, Dashboard pinning/product work,
  Copilot Accept/Reject, new execution operations, authentication, or final
  visual polish.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `frontend/src/features/output/OutputDock.tsx` | Collapsible bottom dock, tab selection, busy/error state, and Project lifecycle |
| `frontend/src/features/output/ResultsTab.tsx` | Execution status, Unit results, warnings, stale state, charts, and rerun actions |
| `frontend/src/features/output/ReportTab.tsx` | Generate, load, and read the Markdown report |
| `frontend/src/features/output/DashboardPlaceholder.tsx` | Clear empty placeholder; no pinning interaction |
| `frontend/src/api/executionApi.ts`, `frontend/src/api/reportApi.ts` | Typed polling, rerun, chart URL, and report clients |
| `src/api/app.py` and build configuration | Serve the Vite build and remove the legacy browser entry after verification |
| `docs/README.md`, `README.md`, `docs/architecture/current.md`, `docs/roadmap.md` | Record the supported frontend, validation commands, and deferred Dashboard work |
| `docs/cycles/cycle-7-react-workspace/summary.md` | Cycle closure evidence and decisions |
| `frontend/e2e/` or `tests/browser/` | Playwright/browser acceptance workflow |

### Output Dock contract

The dock is presentation only and is scoped to the active Project. Its tabs
are:

```text
Results
  status -> per-Unit result -> warnings/stale -> charts -> rerun
Report
  generate -> retained Markdown report
Dashboard
  explicit empty placeholder (no API pin/read/write)
```

Results use the existing public fields: execution status, Unit status/stdout/
stderr, insights, warning codes, stale flags, row-count metadata, chart
references, run IDs, and checkpoint labels where already exposed. Internal
checkpoint IDs remain non-editable metadata. Chart URLs are constructed only
from the session-scoped `/execution/charts/{path}` contract; the browser never
builds an arbitrary filesystem URL.

Execution polling is active only for the current Project and stops when the
status is terminal, the dock unmounts, or the Project changes. After a run or
rerun, refresh the Plan/data/result projections from the server because
Snapshot heads, visible columns, and stale state may change.

Dashboard is a route/view placeholder with concise copy that says the feature
is deferred. Do not call the existing dashboard pin endpoints from the
finished React app, and do not label the placeholder a Result Canvas / Board.

## Execution Tasks

### 1. Add typed execution and report clients

- Implement methods for `/execution/run`, `/execution/status`,
  `/execution/results`, `/execution/units/{unit_id}/rerun`, chart references,
  `/report`, and `/report/generate`.
- Decode status and Unit result payloads at the API boundary, preserving
  warning dictionaries and stale flags without inventing frontend semantics.
- Normalize HTTP 409/422/404 errors and show the server message in the active
  Project context.
- Add polling with an abort signal and a bounded interval/backoff. Never keep a
  timer alive for an inactive Project.

### 2. Build Results and Report tabs

- Add a collapsed/expanded dock toggle and tabs that do not resize or reorder
  the Plan Canvas unexpectedly. Persist collapse only if the final UX test
  demonstrates value; otherwise keep it session-local presentation state.
- Results tab shows idle, running, completed, partial, failed, and stale
  states distinctly. Group Unit rows by stable Unit ID and link each row to
  the corresponding Plan Canvas card.
- Render structured Join warnings (`JOIN_MANY_TO_MANY`,
  `JOIN_ROW_EXPANSION`, `JOIN_KEY_DTYPE_MISMATCH`, `JOIN_UNMATCHED_KEYS`) as
  warnings, not confirmation gates or mechanical failures.
- Show row-count before/after/delta, input/output checkpoint labels, insights,
  stdout/stderr in a compact disclosure, and chart thumbnails or links using
  the safe API URL.
- Add unit rerun and cascade-rerun actions with explicit busy state. After the
  response, refresh results and show which dependent Units became stale.
- Report tab loads retained Markdown, offers Generate, and displays report
  errors without discarding the previous report.

### 3. Add the Dashboard placeholder

- Add a clearly empty Dashboard view in the Output Dock or center route with
  no pin controls, chart-management affordances, or misleading sample data.
- Keep existing backend dashboard endpoints for compatibility tests, but do
  not migrate their state into the frontend model.
- Add a test that opening Dashboard performs no dashboard mutation request.

### 4. Verify the full Project lifecycle

- On Project switch, stop polling, cancel chart/report/execution requests,
  clear selected Unit/result expansion, and reload public projections for the
  new Project.
- On browser reload and server restart, restore Project title, Sources,
  Plan/Workspace layout, Agent Thread list/history, results, and report from
  server state.
- Make an execution error or incompatible Project recoverable without
  returning the user to the legacy page.

### 5. Retire and document the frontend migration

- Build the Vite production output into the existing FastAPI `static/` mount.
  Remove the old `static/app.js`/HTML/CSS from the supported runtime after
  browser evidence is captured; keep only assets explicitly migrated to the
  new build.
- Update README, `docs/README.md`, `docs/architecture/current.md`, and
  `docs/roadmap.md` from observed implementation behavior. Replace the old
  `node --check static/app.js` gate with frontend typecheck/lint/build and
  browser evidence.
- Add `docs/cycles/cycle-7-react-workspace/summary.md` and, at formal cycle
  closure, move detailed plans under the cycle archive according to the
  documentation workflow. Do not archive them before the implementation is
  actually validated.

### 6. Run and record the acceptance workflow

Use deterministic fixtures named `orders.csv` and `customers.csv`:

```text
create Project and rename it
-> upload both sources
-> inspect qualified columns and public profiles
-> create Derive, Filter, Join, and Terminal Units
-> move/zoom Plan Canvas and reload
-> create two Agent Threads and verify isolation
-> execute the Plan and review warnings/charts in Results
-> rerun one Unit and optionally cascade its dependents
-> generate and reload the report
-> switch Project and return; verify full isolation and persistence
```

Capture API assertions plus browser screenshots or Playwright traces at a
desktop and narrow desktop width. Include at least one duplicate/unmatched
Join-key case so warning display is evidence-backed rather than a static mock.

## Tests and Evidence

- Frontend unit/component tests cover result status mapping, stale markers,
  chart URL construction, report load/generate, polling cancellation, and the
  Dashboard no-request placeholder.
- Backend regression suite remains green for data, workspace, execution,
  dashboard compatibility, report, Copilot, and session routes.
- Browser acceptance proves Project history/rename, thread isolation, upload,
  all four operations, Plan Canvas layout persistence, execution polling,
  warnings, unit/cascade rerun, report generation, and restart recovery.
- Run:

  ```text
  npm run typecheck
  npm run lint
  npm run build
  pytest -q
  ruff check .
  mypy src/
  git diff --check
  ```

- Record the exact local server/build commands, fixture names, browser viewport,
  and any deferred failures in the Cycle 7 summary.

## Exit Criteria

- The React/Vite workspace is the supported browser surface and the old
  zero-build application is no longer required at runtime.
- The Output Dock provides usable Results and Report views, including run,
  polling, warnings, charts, stale state, rerun, and report generation.
- Dashboard is visibly and honestly deferred as a blank placeholder.
- The complete acceptance workflow works after browser reload and server
  restart, with no cross-Project or cross-Thread leakage.
- Full repository and frontend validation evidence is recorded, and docs state
  what Cycle 7 delivered versus what remains for Cycle 8+.

## Risks and Mitigations

- **Polling leaks across Projects:** bind timers and abort controllers to the
  active Project ID and stop them on every navigation transition.
- **Output Dock obscures the Plan Canvas:** use a stable collapsible track and
  test expanded/collapsed states at both validation widths.
- **Dashboard looks partially implemented:** render only a deliberate empty
  placeholder and keep pin APIs out of the React client.
- **Build migration breaks API serving:** run API-only tests with the existing
  mount, then run a production build and browser smoke check before deleting
  the legacy entry files.
- **Documentation claims exceed evidence:** write the cycle summary from the
  captured acceptance run and list every deferred or skipped scenario.
