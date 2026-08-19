# Cycle 7 Summary: React Project Workspace

## Status

Implemented and closed. Cycle 7 replaces the supported zero-build browser
surface with the React, TypeScript, and Vite Project workspace. The post-M6
M7 follow-up is also implemented and closes the interaction and layout issues
found during workspace review. The restricted M8 supplement is implemented
and closes the remaining Plan-time Explorer and node-drag persistence gaps.

## Delivered

- M1 added durable Project summaries, Project naming, Project-owned Agent
  Threads, explicit Thread-scoped Copilot requests, and schema-safe session
  persistence.
- M2 added the Vite shell, Project history, create/switch/rename behavior, and
  stable Explorer, Plan Canvas, Agent, and Output Dock regions.
- M3 mapped the server Plan v2 DAG to React Flow nodes and edges and persisted
  presentation-only positions, viewport, and collapsed state.
- M4 connected public Source/Snapshot/profile projections, upload, typed
  Derive/Filter/Join/Terminal editing, qualified column drag payloads, and
  server-confirmed delete conflicts.
- M5 added isolated Project-local Thread list/detail/history behavior and the
  bounded Copilot composer with cancellation and late-response protection.
- M6 connected execution polling, Results, warnings, charts, stale markers,
  unit and cascade reruns, retained Markdown reports, and an explicit blank
  Dashboard placeholder. Execution and report changes refresh the active
  Project, Explorer, and Plan projections from the server.
- M7 simplified operation creation to click-to-create plus explicit column
  slots, removed the empty-Canvas chooser, anchored the Unit Inspector beside
  its node, contained panel scrolling inside the viewport, and made layout
  writes local-during-drag with one validated save at gesture end.
- M8 added the coherent read-only workspace data projection, overlays the
  server-confirmed Plan schema into Explorer before execution, keeps unknown
  execution facts nullable, refreshes only Explorer after accepted Plan
  mutations, and makes node/collapse persistence revision-safe without saving
  viewport movement.

## Architecture Decisions

- The Plan remains the only semantic authority. Output Dock state is a
  Project-scoped view of execution and report APIs; it is not a second Plan or
  result runtime.
- Polling and every output request are bound to the active Project and are
  aborted on unmount or Project change. Late responses are ignored by the
  component lifecycle.
- Chart references are constructed only from session-relative API paths. The
  browser never receives or builds a filesystem URL.
- Dashboard compatibility routes remain available to existing clients, but
  the React Dashboard view performs no read or mutation request. Dashboard
  product behavior is deferred.
- `frontend/` is the maintained browser source. `npm run build` writes the
  supported production bundle to `static/`; the old `static/app.js` and
  `static/styles.css` are retired.
- Plan-time Explorer schema is derived from the same evaluator used by Plan
  validation. It never creates registry records or checkpoint files, and a
  stale prior result is projected as planned until a successful non-stale
  result and current registry record agree.

## Validation Evidence

Commands run from `D:\Projects\Agents`:

```text
pytest -q                         281 passed
ruff check .                      All checks passed
mypy src/                         Success: no issues found
git diff --check                  passed
```

Commands run from `frontend/`:

```text
npm.cmd run typecheck             passed
npm.cmd run lint                  passed
npm.cmd run test                  41 tests passed
npm.cmd run build                 passed; Vite bundle written to static/
```

The frontend tests cover typed execution/report boundaries, safe chart URL
construction, warning rendering, retained report loading, Dashboard no-request
behavior, stale markers, request cancellation, and Project-scoped Output Dock
rendering. M7 adds layout timing, latest-write, invalid-coordinate, and
column-drop interaction coverage. M8 adds nullable projection decoding,
planned-schema rendering, planned-column downstream schema coverage, and
response-safe consecutive-drag tests. The existing backend Cycle 5/6 closure
tests remain part of the 281-test suite.

Production HTTP smoke used FastAPI on `127.0.0.1:8000` after the Vite build:
the root and direct Project URL returned the Vite bundle; a new Project
returned `execution.status=idle`, `results.status=idle`, `report=null`, and an
empty compatibility Dashboard pin list. The temporary server was stopped
after the check.

No Playwright/Puppeteer package or browser binary was available in this
workspace, so desktop/narrow-viewport screenshots and browser traces were not
captured. This is a validation-environment gap, not an implemented runtime
contract; the focused jsdom tests and HTTP smoke are the recorded fallback.

## Deferred Work

- Copilot Plan proposal Accept/Reject.
- Result Canvas / Board and Dashboard pinning/product semantics.
- New analysis operations, hosted multi-user behavior, authentication, and
  stronger worker isolation for generated code.
- A browser automation harness with desktop and narrow-viewport screenshots.
