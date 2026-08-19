# M8: Plan-Time Explorer Projection and Node Drag Persistence

## Status

Implemented Cycle 7 post-closure supplement. This remains intentionally limited
to the two unfinished workspace behaviors below; it is not a new product cycle
and does not reopen the broader Cycle 7 scope.

## Outcome

Users can compose a valid Plan before execution: a declared Derive output,
Filter output Snapshot, or Join output Snapshot appears in Explorer as a
planned item and can be used as a downstream Unit input. Node dragging remains
local and smooth while an older layout write is in flight; only final node
positions and collapse changes are persisted.

## Problem Evidence

### Explorer only exposes materialized registry state

`frontend/src/api/dataApi.ts#getDataCatalog` currently composes four `/data/*`
requests: sources, snapshots, columns, and lineage. Those routes in
`src/api/routes/data.py` project only `snapshot_registry`,
`checkpoint_registry`, and `column_graph`. A Derive/Filter/Join has no such
records until successful execution, so `SourceTree` cannot offer its output
for a downstream drag.

The missing behavior is already modeled on the server. During full Plan
validation, `src/agent/plan_validation.py` creates `_SnapshotView` objects in
topological order:

- Derive adds its declared output ref to the input Snapshot view.
- Filter creates an output Snapshot view by renaming every input ref.
- Join creates an output Snapshot view from its declared select aliases.

That simulation is exactly the semantic source needed by Explorer. It must be
extracted into a reusable, public projection helper instead of duplicated in
TypeScript or by ad hoc route logic.

### Layout acknowledgements can overwrite active local movement

`PlanCanvas.tsx` updates local positions during `onNodesChange`, then writes a
layout after `onNodeDragStop`. While a PUT is in flight, a new drag changes
`layoutRef` without populating `layoutWriteQueue` until that later drag stops.
When the older PUT resolves, `flushLayoutWrite` sees an empty queue and assigns
the old server layout back into React state. This can pull a node back during
the second drag. The corresponding failure path can restore the same old
layout. The existing queue test covers two completed drags, not an active
second drag while the first response resolves.

`onMoveEnd` also writes viewport updates. Persisting viewport movement is not
needed for the requested behavior and increases the number of independent
layout writers.

## Scope

1. Add one read-only, plan-aware Explorer data projection endpoint.
2. Render planned Snapshot and column facts in Explorer, including drag payloads
   for downstream Unit slots.
3. Refresh only Explorer data after a server-confirmed Plan mutation.
4. Make node-position and collapse persistence revision-safe.
5. Stop persisting pan and zoom changes.

## Explicit Non-Goals

- Do not change when Plan validation occurs. Workspace writes remain
  server-validated, and execution continues to validate before running.
- Do not support invalid or partially saved draft Plans.
- Do not create `SnapshotRecord`, `CheckpointRecord`, `ColumnNode`, files, or
  execution results before a successful execution.
- Do not change DAG scheduling, rerun behavior, stale-result semantics, Plan
  editing contracts, or layout API persistence schema.
- Do not change Output Dock behavior, canvas header copy, panel sizing, or add
  a new visual lineage product.
- Do not replace React Flow, introduce automatic-only layout, or persist
  viewport movement through a new mechanism.

## Product Contract

### Planned data is schema, not materialized evidence

Explorer represents two distinct facts:

| Item | Materialized | Planned |
|---|---|---|
| Can be selected or dragged into a downstream Unit | Yes | Yes |
| Row count, null rate, sample, and source profile | Existing public registry facts only | Unknown and not displayed as a value |
| Checkpoint / Column Graph record | Exists | Does not exist |
| Persistence | Durable registry | Derived from the current server-confirmed Plan |

For a source Snapshot with a planned Derive, the Snapshot remains materialized
but the added column is marked planned. Filter and Join outputs are planned
Snapshots until their producing Unit has a successful, non-stale result and a
matching current registry record. A stale prior result must be shown as planned
schema rather than as fresh data.

The projection must never invent numeric facts. Planned `row_count`,
`null_count`, and `null_pct` are `null`; a planned output dtype is either
inherited deterministically from an existing input column or `null` when the
Plan does not declare it. Planned Snapshot inspection states that profile and
sample facts are available after execution.

### Endpoint contract

Add `GET /api/sessions/{session_id}/data/workspace-projection` in
`src/api/routes/data.py`. Keep existing `/data/sources`, `/data/snapshots`,
`/data/columns`, and `/data/lineage` unchanged for compatibility.

Return one coherent catalog rather than making four independently timed
requests. Use dedicated response models rather than weakening the existing
materialized `SnapshotResponse` or `ColumnInfoResponse` contracts.

```text
WorkspaceDataProjectionResponse
  sources: existing SourceResponse[]
  snapshots: WorkspaceSnapshotViewResponse[]
  columns: WorkspaceColumnViewResponse[]
  lineage: existing LineageColumnResponse[]
  compatibility_warning: str | null

WorkspaceSnapshotViewResponse
  view_id: str                         # UI identity, never a checkpoint id
  snapshot_id: str | null              # null for planned-only Snapshots
  name, display_name: str
  row_count: int | null
  column_refs: str[]
  source_id: str | null
  created_by_unit_id: int | null
  parent_snapshot_names: str[]
  availability: "materialized" | "planned"
  profile_available: bool

WorkspaceColumnViewResponse
  ref, name, snapshot: str
  dtype: str | null
  null_count: int | null
  null_pct: float | null
  source_column: str | null
  created_by_unit_id: int | null
  availability: "materialized" | "planned"
```

`view_id` replaces the frontend assumption that every logical Snapshot has a
durable `snapshot_id`. A planned Filter or Join can use a stable public view ID
derived from its producing Unit ID; it must not masquerade as a registry ID.
For a materialized Snapshot, `view_id` must equal its existing `snapshot_id` so
the unchanged source summary can still locate its root Snapshot. Parents are
returned by logical name because a planned parent has no durable Snapshot ID.

The response order must be deterministic: source Snapshot views in source
order, then other materialized Snapshot views by name, then planned-only views
in Plan topological order. There is one visible logical Snapshot per name and
one visible column per qualified ref. Plan-projected schema wins over stale
registry schema for an active Plan output.

## Server Design

### Reuse the validator evaluation exactly once

Refactor `src/agent/plan_validation.py`; do not copy the Derive/Filter/Join
rules into `data.py`.

1. Extract the existing topological evaluator used by `collect_plan_issues`
   into a shared internal evaluation function. It returns validation issues and
   typed Snapshot views.
2. Promote the returned view data to a narrow public projection type. A column
   view must explicitly distinguish a materialized Column Graph node reference
   from `planned_by_unit_id`; do not make the HTTP route parse the current
   internal `planned:unit_...` marker string.
3. Keep `collect_plan_issues` and `validate_plan` behavior byte-for-byte
   equivalent from their callers' perspective: they consume the same evaluator
   output and still return the same structured issues.
4. Add a read-only `project_plan_snapshot_views(plan, state)` helper for the
   data route. It must not mutate `AgentState`, registries, a DataFrame, or the
   filesystem. It may use `allow_reexecution=True` solely to render the
   current persisted Plan after its own successful prior output exists in the
   registry; this must not alter the validation policy of workspace writes.

The data route builds materialized facts from its current helpers, overlays the
shared Plan views, and maps the result into the new public schema. Determine a
materialized active Plan output only from existing durable facts:

- Derive column: a current Column Graph node created by that Unit plus a
  successful, non-stale Unit result.
- Filter or Join Snapshot: a current SnapshotRecord created by that Unit plus
  a successful, non-stale Unit result.

Anything else is planned. Do not compare Plan payloads, inspect Parquet files,
or infer materialization from a name alone. Materialized lineage remains the
existing public lineage projection; planned items expose their producer Unit ID
but do not claim concrete lineage nodes.

For an absent Plan, return the same logical catalog as the current materialized
endpoints. Preserve the legacy `unified_columns` compatibility warning rather
than attempting a Plan overlay for a non-v2 session.

## Frontend Design

### Data API and Explorer

Update `frontend/src/api/dataApi.ts` so `getDataCatalog` makes one request to
`/data/workspace-projection` and decodes nullable planned facts. Keep the
existing direct endpoint helpers only where another frontend feature still
uses them. Update `DataCatalog`, `SnapshotSummary`, and `PublicColumn` to use
the new `viewId`, availability, and nullable fact fields without silently
turning unknown values into zero.

Update `SourceTree.tsx` to use `viewId` for Snapshot selection and show a
compact planned state. Planned columns use the same qualified-column drag
payload as materialized columns, so `resolveColumnDrop` and the existing Unit
API remain authoritative. Render `Pending` rather than calling
`toLocaleString()` on a missing row count or displaying `0% null` for unknown
data.

Update `ProfilePanel.tsx` to render a planned Snapshot schema without calling
the source profile endpoint or displaying a fake shape. Show its parent names,
declared columns, and the absence of execution facts. Existing materialized
source profile behavior remains unchanged. Update the palette and initial
operation schema tests only as needed to prove that planned Snapshot and
column entries are accepted as ordinary catalog inputs.

### Refresh boundary

Do not reuse `workspaceRefreshKey` for this feature. In `App.tsx`, that key
reloads both Explorer and `PlanCanvas`; using it after every Plan mutation
would abort Canvas work and reintroduce layout instability.

Add a separate `catalogRefreshKey` owned by `App`. Pass it only to Explorer.
Add an `onPlanChanged` callback to `PlanCanvas`; call it only after a create,
update, or delete response has been accepted by the server and reconciled into
the local Plan. The callback increments `catalogRefreshKey`. Explorer's
existing abort-on-refresh behavior prevents an older catalog response from
overwriting the current Project view. Do not refresh Explorer for local drag,
pan, zoom, inspector selection, or a rejected semantic update.

## Layout Persistence Design

Keep `WorkspaceLayout` version 1 and the existing PUT endpoint. Only the
frontend write policy changes.

1. Remove `onMoveEnd`, its `Viewport` dependency, and all pan/zoom saves from
   `PlanCanvas` and `CanvasViewport`. Read a previously stored viewport on
   initial load for backward compatibility, but do not write a new viewport.
2. Add a monotonically increasing local layout revision. Every accepted local
   position change, final node position, collapse change, and Plan-reconcile
   fallback-position change advances it. Centralize this in one local-layout
   apply helper so `reconcileServerPlan` cannot bypass the revision.
3. Store `{ layout, revision }` in both the latest-pending slot and the active
   write record. Continue serializing PUTs so the server cannot receive later
   positions before earlier positions.
4. A successful response always updates only `confirmedLayoutRef`. It updates
   save status to `saved` only when its revision is still the latest local
   revision and no newer save is queued. It must never assign the server layout
   back into `layoutRef` or React state after initial load.
5. A failed or invalid response sets `rejected` only if it belongs to the
   latest local revision. It must leave the current local node position in
   place; a later drag is the natural retry path. It must not restore an older
   server layout during an active or newer drag.
6. An invalid position event is ignored with a visible local error while
   retaining the last valid local layout. It must not be sent and must not snap
   the node back to an unrelated confirmed layout.

This deliberately retains controlled local position updates during drag. It
does not introduce `useNodesState`, React Flow replacement, throttled network
writes, or an automatic-layout rewrite in this supplement.

## Files Expected to Change

| Area | Files | Required change |
|---|---|---|
| Shared plan projection | `src/agent/plan_validation.py` | Extract the existing evaluator and expose typed read-only Plan Snapshot views. |
| Data API | `src/api/routes/data.py`, `src/api/schemas.py` | Add the coherent projection route and dedicated nullable public response models. |
| API tests | `tests/api/test_workspace_projection.py` or a focused addition to `test_data.py` | Assert projection behavior and absence of pre-execution registry writes. |
| Frontend decoder | `frontend/src/api/dataApi.ts` and tests | Decode the new endpoint and nullable planned facts. |
| Explorer | `Explorer.tsx`, `SourceTree.tsx`, `ProfilePanel.tsx`, `OperationPalette.tsx`, `app.css` | Display and drag planned schema without false execution facts. |
| Plan-to-Explorer refresh | `App.tsx`, `PlanCanvas.tsx`, focused tests | Use a catalog-only refresh callback after accepted semantic mutations. |
| Layout race | `PlanCanvas.tsx`, `PlanCanvas.test.tsx` | Revision-safe node/collapse persistence; remove viewport writes. |

`src/api/routes/workspace.py`, `src/api/routes/workspace_layout.py`,
`src/agent/dag.py`, `src/agent/state.py`, and the persisted layout schema are
not expected to change unless an implementation discovers a concrete contract
gap. Do not make opportunistic frontend shell or Output Dock changes.

## Acceptance Tests

### Backend

1. Upload a source, save a valid Derive followed by a downstream Terminal, and
   assert the projection exposes the planned output column before execution.
   Assert registry and checkpoint counts are unchanged.
2. Save a Filter fed by a planned Derive. Assert the planned output Snapshot
   contains inherited base refs plus the planned derived ref, has no row count,
   and identifies its producing Unit.
3. Save a Join. Assert its planned output Snapshot exposes only declared select
   aliases and has no fabricated row/null facts.
4. Execute a data-producing Unit, then assert its current successful,
   non-stale output is materialized. Mark its result stale and assert the
   active Plan view falls back to planned schema rather than fresh-data facts.
5. Cover no-Plan and legacy compatibility responses without changing existing
   `/data/*` response shapes.

### Frontend

1. Decode planned Snapshot/column entries with null row and null statistics.
2. Render planned Snapshot rows and columns without runtime formatting errors.
3. Drag a planned qualified column into a downstream Unit slot and assert the
   same ref/snapshot payload reaches the existing patch path.
4. After a successful Plan mutation, assert Explorer reloads its catalog while
   PlanCanvas does not reload its workspace/layout pair.

### Layout

1. Start a first drag save, begin a second drag through `onNodesChange`, then
   resolve the first PUT. Assert the React Flow node position remains at the
   newer local position.
2. Repeat with the first PUT rejected. Assert the newer local position remains
   and the error does not enqueue or submit invalid coordinates.
3. Stop the second drag and assert exactly its final layout is sent after the
   earlier request completes.
4. Assert panning and zooming do not issue a layout PUT. Assert collapse and
   drag-stop still issue one valid PUT.

## Validation and Closure Evidence

Run after implementation:

```text
pytest -q
ruff check .
mypy src/

cd frontend
npm run typecheck
npm run lint
npm run test
npm run build

cd ..
git diff --check
```

Also run the local API and Vite workspace, create a pre-execution downstream
Plan from a planned column and Snapshot, reload the Project, and pointer-test
two quick consecutive node drags while delaying the first layout response.
Capture a browser trace or screenshot evidence if browser automation is
available; the previous Cycle 7 environment gap must not be silently reused as
closure evidence.
