# M5 Plan: API, Browser Workflow, Reporting, and Cycle Closure

## Objective

Expose the complete v2 workflow through the session API and zero-build browser:
multi-file upload, qualified-column selection, operation-specific Plan editing,
execution, warning display, restart recovery, unit rerun, and report generation.

## Dependencies and Boundary

- Depends on M1-M4 backend contracts.
- This is the product completion and validation pass, not a place to add new
  analytical operations or visual lineage graphs.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/api/routes/data.py` | sources, Snapshots, qualified columns, profiles |
| `src/api/routes/workspace.py` | v2 Plan read/write/edit/delete and validation errors |
| `src/api/routes/execution.py` | results, warnings, checkpoint metadata, rerun/stale state |
| `src/api/routes/report.py` | v2 profile/lineage/warning-aware report generation |
| `src/api/schemas.py` | public v2 response and request shapes |
| `src/agent/nodes/business_track.py` | grouped source/Snapshot agent context |
| `src/agent/nodes/planner.py` | Plan v2 generation through API and graph |
| `src/agent/nodes/report_gen.py` | report inputs from v2 state and durable results |
| `static/index.html`, `static/app.js`, `static/styles.css` | multi-source browser workspace |
| `tests/api/*.py` | endpoint contracts and restart behavior |
| `tests/browser/` or documented Playwright/manual workflow | real browser acceptance |
| `docs/architecture/current.md`, `docs/roadmap.md` | closure documentation |

## Execution Tasks

### 1. Stabilize public API response shapes

- Return source records, Snapshot heads, visible qualified columns, and profile
  metadata without exposing internal node IDs or executor-only DataFrames.
- Return operation-specific Plan JSON and structured validation issues from
  workspace endpoints.
- Return unit results with input/output checkpoint references where useful,
  row-count changes, warnings, stale state, and artifact references.
- Keep checkpoint IDs as backend metadata; the browser may display a concise
  provenance label but must not make internal IDs editable.
- Preserve path traversal protection for chart serving and session-relative
  artifact references.

### 2. Build multi-source upload and recovery UX

- Allow multiple files to be selected or dropped and append them to the active
  Session.
- Show each source Snapshot separately with display filename, row count, and
  visible columns grouped under the source/Snapshot.
- Hide `__di_row_id` and any executor-only metadata.
- On reload, fetch sources and qualified columns from the API rather than
  reconstructing them from a single profile or local arrays.
- Surface the explicit incompatible-session response with an actionable message
  while leaving the old state file untouched.

### 3. Add operation-specific Plan editing

- Keep columns as the draggable data objects, but route drops to the relevant
  operation input fields.
- Add controls for Derive output column and parameters, Filter output Snapshot
  and predicate, Join left/right Snapshots, keys, selected outputs, aliases,
  and Terminal inputs.
- Show dependencies and stale status without exposing a visual lineage graph.
- Never renumber unit cards after deletion. Confirm or reject deletion based on
  downstream dependents returned by the API.
- Ensure long qualified names wrap cleanly and controls remain usable at the
  supported desktop/mobile widths.

### 4. Display execution state and warnings

- Keep existing run polling for full execution and synchronous unit rerun where
  the API contract permits it.
- Render `JOIN_*` warnings alongside the successful unit result and distinguish
  warnings from mechanical failures.
- Add rerun controls that report newly stale units and refresh results from the
  server after completion.
- Do not claim a result is current when its upstream checkpoint is stale.

### 5. Adapt Planner, report, and CLI consumers

- Business Track and Planner prompts receive qualified columns grouped by
  Snapshot, not a flat `unified_columns` list.
- Report generation receives source profiles, alignment notes, unit warnings,
  row-count changes, lineage summaries, and session-relative chart refs.
- Preserve the mandatory data-business alignment section and explicitly
  disclose Join warnings and data limitations.
- Update CLI plan display/edit commands to operation v2 or clearly scope the
  CLI to one-source v2 sessions; do not leave it constructing old PlanUnits.

### 6. Run the real acceptance workflow

Use deterministic fixture files named `orders.csv` and `customers.csv`:

```text
upload both files
-> derive orders.revenue
-> filter orders into east_orders
-> join east_orders with customers
-> run a terminal chart/statistics unit
-> reload the process and browser
-> verify Plan, results, warnings, and lineage state
-> rerun one unit and verify retained prior checkpoint plus stale dependents
```

Capture the API responses and a browser screenshot or Playwright evidence for
the final validation record. The workflow must work without relying on an LLM
to invent a missing qualified column.

## Tests and Evidence

- API tests cover append upload, source listing, qualified columns, Plan
  validation errors, result warnings, stale/rerun responses, and restart.
- Frontend syntax check passes and the browser workflow completes at desktop
  and narrow viewport sizes without overlap or hidden controls.
- The acceptance fixture shows direct parents for the derived revenue column,
  inherited Filter lineage, and every selected Join output.
- The report contains durable warning and alignment context after restart.
- `pytest -q`
- `ruff check .`
- `mypy src/`
- `node --check static/app.js`
- Local server plus a real browser workflow against the two-source fixture.

## Exit Criteria

- The PRD end-to-end acceptance scenario works through the browser and API.
- Session restart does not lose Plan, registry, warnings, result references,
  report, or retained checkpoints.
- A single-unit rerun changes the correct Snapshot head and preserves prior
  provenance.
- `docs/architecture/current.md` describes the implemented v2 runtime, and
  `docs/roadmap.md` records Cycle 5 closure and deferred candidates.
- A cycle summary records validation evidence, architectural decisions, and
  explicitly deferred work; detailed plans move to the archive at closure.

## Risks and Mitigations

- **UI/backend drift**: freeze response schemas before final frontend work and
  test API payloads directly.
- **False end-to-end confidence**: use duplicate keys, unmatched keys, and a
  rerun in the acceptance fixture, not only a happy-path Join.
- **Documentation drift**: update architecture and roadmap only from the final
  implementation behavior and include deferred work explicitly.
