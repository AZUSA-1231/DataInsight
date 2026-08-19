# M3: Plan Canvas Mapping and Workspace Layout

## Status

Implemented. The server-confirmed Plan v2 mapper, Project-scoped Workspace
layout API, React Flow canvas, layout persistence, and dependency edge gestures
are available in the React workspace. Operation-specific field editing and
column drag targets remain M4 scope.

## Objective

Build the Plan Canvas as a reliable visual editor for the existing Plan v2
DAG. The milestone defines and tests the one-to-one mapping between canonical
Plan semantics and React Flow presentation, adds durable Workspace layout, and
implements pan, zoom, move, collapse, fit-view, and dependency gestures. It
does not add new operations or infer data routing from graph geometry.

## Dependencies and Boundary

- Depends on: M1's `WorkspaceLayout` state/API boundary and M2's center shell.
- Enables: M4 operation cards and explicit drag targets, and M6 execution
  evidence attached to stable Unit IDs.
- Does not implement: Explorer data loading, operation-specific form behavior,
  Copilot proposal application, Result Canvas / Board, or visual lineage.
- React Flow is a rendering and gesture library, not a second workflow model.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `frontend/src/domain/plan.ts` | Public Plan/Unit discriminated types and operation-specific mutation intents |
| `frontend/src/features/workspace/canvas/planMapper.ts` | Pure `toPlanCanvas(plan, layout, facts)` mapping and deterministic placement |
| `frontend/src/features/workspace/canvas/planMapper.test.ts` | Invariant and reconciliation tests independent of React Flow |
| `frontend/src/features/workspace/canvas/PlanCanvas.tsx` | React Flow viewport, node/edge rendering, gesture handlers, and rollback |
| `frontend/src/features/workspace/canvas/OperationNode.tsx` | Stable Unit card shell and semantic drop-slot/connection handles |
| `frontend/src/features/workspace/canvas/CanvasToolbar.tsx` | Fit view, zoom controls, collapse/expand affordances, and save status |
| `frontend/src/features/workspace/layoutApi.ts` | GET/PUT layout client, debounce, cancellation, and validation errors |
| `src/api/schemas.py` and `src/api/routes/workspace_layout.py` | Typed layout projection and Project-scoped validation/persistence |
| `tests/api/test_workspace_layout.py` | Layout validation, restart, and unknown Unit behavior |

### Canonical mapping

The mapper is pure and takes the latest server-confirmed Plan plus the latest
layout:

```text
Plan.units[n]
  -> node id unit:<unit_id>
  -> node type derived from operation
  -> node data derived from the current complete Unit

Plan.units[target].depends_on contains source
  -> edge id unit:<source>->unit:<target>
  -> source unit:<source>, target unit:<target>

WorkspaceLayout.nodes[unit_id]
  -> position, collapsed state, and other presentation-only values
```

The following must be executable assertions, not just comments:

1. Every current Unit produces exactly one node, and every node points to one
   current Unit ID.
2. Node operation type and editable values come from the Plan response, never
   from a serialized React Flow node copy in layout.
3. Every edge comes from one `depends_on` relation; no edge list is persisted.
4. Layout cannot create a node, edge, source, column, or execution route.
5. A semantic mutation is sent to the existing `/workspace` or
   `/workspace/units/{unit_id}` API, and the response replaces the local Plan.
6. A move, viewport change, or collapse writes only layout and never marks a
   Plan result stale.
7. Unknown layout records are ignored during rendering and removed on the next
   successful save. The API rejects a submitted ghost Unit ID with a
   structured error so clients cannot persist accidental semantic references.

### Layout contract

Persist a versioned object with finite coordinates and bounded zoom:

```text
{
  "version": 1,
  "viewport": {"x": number, "y": number, "zoom": number},
  "nodes": [
    {"unit_id": positive integer, "x": number, "y": number,
     "collapsed": boolean}
  ]
}
```

Node IDs are unique. Coordinates and viewport values are finite. The server
checks that each saved `unit_id` belongs to the current Plan and rejects
duplicates or out-of-range values. The mapper assigns deterministic positions
for missing Units using topological level and Unit ID, so a valid Plan always
renders before a layout write completes.

### Mutation semantics

| User gesture | Server operation | Local behavior on failure |
|---|---|---|
| Drag a Unit card | Debounced layout PUT | Restore last server-confirmed layout |
| Pan or zoom | Debounced layout PUT | Restore previous viewport if rejected |
| Collapse a card | Layout PUT | Reopen to prior state if rejected |
| Connect A to B | Update B with `depends_on + A` | Rebuild from prior Plan; show validation issue |
| Remove A -> B | Update B with `depends_on - A` | Rebuild from prior Plan; show validation issue |
| Edit a field | Operation-specific Unit update | Rebuild from prior Plan; preserve no optimistic copy |
| Delete a Unit | Existing delete endpoint, explicit cascade choice | Keep node and show dependent IDs |

Serialize semantic Plan mutations per active Project. Layout writes may be
debounced separately, but are cancelled or keyed by Project ID when switching
Projects. Do not apply a late response to a different active Project.

## Execution Tasks

### 1. Establish public Plan and layout types

- Model the existing `derive_column`, `filter`, `join`, and `terminal` Unit
  shapes as a discriminated TypeScript union. Keep unknown/legacy Units
  renderable as a read-only error card rather than dropping them silently.
- Add layout types and API methods. Decode server JSON at the boundary and
  reject invalid numeric values before passing them to React Flow.
- Add a Project-scoped resource hook that fetches Plan and layout together,
  then exposes a single server-confirmed snapshot to the mapper.

### 2. Implement and test the pure mapper

- Generate stable node and edge IDs exactly as documented.
- Derive node labels, operation kind, stale marker, and public source facts
  from the Plan/data projections; do not embed mutable form state in layout.
- Compute deterministic fallback positions from a topological level map. Use a
  stable tie-breaker (`unit_id`) and keep a fixed node width/height contract so
  labels cannot shift the graph geometry.
- Return a normalized layout containing only current Unit IDs and expose a
  `layoutChanged` flag for the save hook.
- Add tests for empty Plans, disconnected roots, multiple dependencies,
  missing positions, deleted Units, duplicate layout entries, and a Plan change
  that must rebuild node data.

### 3. Mount React Flow safely

- Add a light grid background, pan/zoom controls, fit-view action, and a
  minimap only when it improves large-Plan navigation. Keep the Plan Canvas
  full-width within the center region, not inside a decorative nested card.
- Render one `OperationNode` per mapper node with stable dimensions and
  operation-specific handles. Keep edge direction source -> dependent.
- Show server save state (`saved`, `saving`, `rejected`) without blocking the
  canvas; never claim a semantic edit succeeded before the response arrives.
- Preserve selected Unit ID across a harmless layout refresh and clear it when
  the Unit is deleted or the Project changes.

### 4. Implement dependency gestures

- On connection, identify source and target Unit IDs only. Update the target's
  `depends_on` list through the existing Unit API; do not infer Snapshot,
  column, Join key, or operation fields.
- On edge removal, send the inverse explicit dependency patch.
- Rebuild the graph from the server response and surface structured cycle,
  missing-unit, terminal-leaf, or registry validation issues.
- Prevent self-edges and duplicate edges in the gesture layer while retaining
  server validation as the authority.

### 5. Implement layout persistence

- Load layout after the Plan; reconcile new/deleted Unit IDs in memory.
- Debounce drag and viewport writes, coalesce changes, and cancel pending
  writes on Project switch or unmount.
- On a rejected PUT, retain the last confirmed layout and show a recoverable
  message. Do not turn a layout error into a Plan error.
- Persist collapsed state only as presentation; reopening a card must not alter
  operation fields.

### 6. Define the M4 card extension point

- Expose explicit typed drop-slot descriptors from `OperationNode` so M4 can
  attach qualified-column payloads without adding generic drop handling.
- Keep inspector selection and expanded card content in the center workspace;
  the right application column remains reserved for Agent interaction.

## Tests and Evidence

- Pure mapper tests prove the one-to-one Unit/node and `depends_on`/edge
  mappings, deterministic fallback positions, ghost pruning, and no Plan
  mutation from layout changes.
- API tests cover valid layout round-trip, duplicate Unit IDs, non-finite or
  out-of-range values, unknown Unit rejection, and restart persistence.
- Workspace API tests prove a connection updates only the target's
  `depends_on`, cycles are rejected, and a failed mutation restores the prior
  server Plan.
- Browser evidence shows pan, zoom, fit view, card movement, reload persistence,
  edge add/remove, and a rejected cycle without a ghost edge.
- Run frontend typecheck/lint plus focused Python tests, `ruff check .`,
  `mypy src/`, and `git diff --check`.

## Exit Criteria

- Any valid Plan v2 response renders as a stable Plan Canvas, including a Plan
  with no Units and a Plan with non-contiguous Unit IDs.
- Reloading a Project restores presentation layout while leaving Plan JSON,
  dependencies, and execution state unchanged.
- Every semantic Plan Canvas action is server-confirmed and reconciled; no second
  serialized DAG, edge store, or operation configuration exists in the client.
- M4 can add operation-specific fields and column drop slots by updating Plan
  through typed intents rather than changing the mapper invariant.

## Risks and Mitigations

- **React Flow node state diverges from Plan:** treat mapped nodes as derived
  values and replace them after every semantic response; keep only selection
  and transient drag state locally.
- **Layout writes race Project switches:** include Project ID and a generation
  token in every write and abort stale requests.
- **Graph gesture implies data routing:** limit connection handlers to
  `depends_on`; make field slots the only route for columns and Snapshots.
- **Large graphs become unusable:** use deterministic placement, fit view,
  stable card dimensions, and a minimap without introducing a new graph model.

## Validation Evidence

- `tests/api/test_workspace_layout.py` covers default layout, round-trip
  persistence, restart reload, duplicate Unit IDs, ghost Unit IDs, invalid
  zoom, and bounded coordinates.
- `frontend/src/features/workspace/canvas/planMapper.test.ts` covers empty
  Plans, stable Unit/node and dependency/edge mapping, deterministic fallback
  placement, ghost pruning, and Plan data reconciliation.
- Repository validation passed with `pytest -q` (277 tests), `ruff check .`,
  `mypy src/`, frontend typecheck/lint/test/build, and a FastAPI + Edge
  browser smoke test showing two mapped Units and their dependency edge.
