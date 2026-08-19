# M4: Explorer, Operation Editor, and Drag and Drop

## Objective

Connect the Explorer to the existing data projections and make all four Plan
v2 operation types composable through explicit, typed interactions. A user can
upload CSV/Excel sources, inspect Sources/Snapshots/qualified columns, drag a
column to a named field slot, drag an operation type to the Plan Canvas, and
edit or delete a Unit while preserving server validation and stale semantics.

## Dependencies and Boundary

- Depends on: M1 public Project/data contracts, M2 shell, and M3 Plan Canvas
  mapping plus stable Unit node extension points.
- Enables: the complete inspect -> edit Plan portion of the Cycle 7 path.
- Does not implement: new analytical operations, visual lineage, arbitrary
  code nodes, free-floating column nodes, Copilot proposal application,
  Dashboard pins, or Result Canvas / Board behavior.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `frontend/src/features/explorer/Explorer.tsx` | Upload entry, Source/Snapshot tree, selection state, and operation palette |
| `frontend/src/features/explorer/SourceTree.tsx` | Public source facts and qualified-column grouping |
| `frontend/src/features/explorer/ProfilePanel.tsx` | Profile, sample, null/type facts, and public lineage detail |
| `frontend/src/features/explorer/OperationPalette.tsx` | Draggable Derive, Filter, Join, and Terminal intents |
| `frontend/src/features/workspace/operations/operationSchemas.ts` | Typed create/update payloads and operation prerequisites |
| `frontend/src/features/workspace/operations/OperationInspector.tsx` | Full operation-specific form for the selected Unit |
| `frontend/src/features/workspace/operations/dropIntents.ts` | Pure qualified-column and operation drag intent resolution |
| `frontend/src/features/workspace/operations/dropIntents.test.ts` | Named-slot mapping and no-orphan guarantees |
| `frontend/src/api/dataApi.ts`, `frontend/src/api/workspaceApi.ts` | Upload, source/profile/lineage, Plan, Unit, and delete clients |
| `src/api/routes/data.py`, `src/api/routes/workspace.py` | Small public projection or validation fixes discovered by typed client integration |
| `tests/api/test_data.py`, `tests/api/test_workspace_v2.py` | API regression and operation composition fixtures |

### Explorer projection contract

The browser consumes only existing safe projections:

```text
SourcesResponse       -> source cards and Snapshot tree
SnapshotsResponse     -> current head, row count, visible column refs
ColumnsResponse       -> qualified column drag payloads
LineageResponse       -> optional public origin/derived facts
profile response      -> selected Source/Snapshot detail
```

The drag payload is a qualified reference such as `orders.revenue` plus its
origin Snapshot. It never contains a filesystem path, checkpoint ID, Column
Graph node ID, hidden `__di_row_id`, live DataFrame, or arbitrary code.

### Operation contracts and slots

The UI must expose the fields already validated by the Pydantic Plan v2
models. A generic card-body drop is invalid wherever it could have more than
one interpretation.

| Operation | Explicit fields and drop slots |
|---|---|
| Derive | Input Snapshot; input-column list; exactly one manually named output column; execution mode/template parameters |
| Filter | Input Snapshot; predicate-column list; output Snapshot name; predicate/template parameters |
| Join | Left/right Snapshot selectors; separate left/right key slots; selected-output slots with editable aliases; join mode and output Snapshot |
| Terminal | Input Snapshot; terminal input-column list; artifact/template settings; no output Snapshot |

Dropping a column onto empty Plan Canvas space does not create a column node.
It opens an explicit chooser (Derive, Filter, or Terminal, with only valid
options for the current data) and applies the column to the documented field
after the user chooses. Dropping an operation palette item creates a valid
initial Unit only when the available Sources/Snapshots satisfy its minimum
prerequisites; otherwise the UI explains what is missing.

### Mutation contract

- Create uses `POST /api/sessions/{project_id}/workspace/units` with a typed,
  operation-specific initial payload.
- Field edits use `PUT /workspace/units/{unit_id}` and include a complete
  replacement payload when changing the discriminated operation.
- Dependency edits remain M3 connection mutations; column drops never alter
  `depends_on` implicitly.
- The API response replaces the local Plan and triggers the M3 mapper. A 422
  validation response keeps the previous Plan and highlights field-level
  issues. A 409 downstream-delete response exposes the dependent Unit IDs and
  requires an explicit cascade choice.
- Editing a Unit retains the existing server stale propagation. The UI may
  display stale markers but does not compute a competing stale graph.

## Execution Tasks

### 1. Build typed public data hooks

- Add Project-keyed hooks for sources, Snapshots, columns, profiles, and
  lineage. Fetch only the active Project and cancel requests on switch.
- Hide the compatibility `unified_columns` fallback when structured columns
  are available; use it only to display an actionable compatibility warning.
- Group columns by Snapshot, show dtype/null facts, and keep long qualified
  refs readable without changing their exact value.
- Add upload progress, file-type/size errors, partial-failure feedback, and a
  refresh after a successful upload so all registry projections converge.

### 2. Implement the Explorer and profile details

- Render a compact Source -> Snapshot -> qualified-column tree. Selecting a
  Source or Snapshot opens public profile/sample facts without exposing raw
  paths or internal IDs.
- Show current row count, column count, and lineage hints from public fields.
  Keep hidden row IDs absent even in sample views.
- Add the operation palette with clear disabled states when no data or no
  compatible Snapshot exists.
- Use native drag events or a small typed drag helper; the payload must include
  a discriminant (`qualified-column` or `operation`) and a validated reference.

### 3. Implement operation creation helpers

- Derive a deterministic initial payload from the first compatible Snapshot,
  selected columns, and a unique Unit ID assigned by the server. Never invent
  an untyped placeholder Unit when prerequisites are absent.
- Filter creates a named output Snapshot and a predicate field that can be
  edited before execution.
- Join requires exactly one left and one right Snapshot, at least one key for
  non-cross modes, and unique selected-output aliases. Make cross joins and
  semi/anti restrictions visible in the form.
- Terminal creates an artifact-only Unit with at least one input column and no
  output column control.
- Keep defaults conservative and deterministic; the server remains the final
  validator.

### 4. Implement named drop slots

- Add `dropIntents.ts` as a pure function from `(payload, targetSlot)` to a
  typed Plan field patch or an explicit chooser action.
- Derive, Filter, and Terminal input slots append only qualified refs from the
  selected/compatible Snapshot. Dropping into an output name is rejected and
  leaves the manual output editor unchanged.
- Join exposes separate left-key, right-key, selected-output, and alias slots.
  A selected-output drop creates an explicit alias that the user can edit;
  it does not silently overwrite an existing alias.
- Empty-space drops invoke the operation chooser before any API request. The
  chooser must preserve the original column payload and selected target.
- Add keyboard-accessible equivalents for adding/removing a column chip; drag
  is an accelerator, not the only path.

### 5. Implement the operation inspector/forms

- Expand the selected Unit inside the center workspace or in a contextual
  inspector. Keep the right column reserved for Agent interaction.
- Use controlled inputs with a dirty state and explicit save/blur behavior.
  Coalesce related field changes into one API update where possible, but never
  send a partially valid discriminated Unit when switching operation type.
- Render structured validation issues next to the relevant field and keep the
  last server-confirmed form values after a rejected update.
- Expose delete with a confirmation that explains downstream dependents and
  offers cascade only when the API reports them. Never renumber v2 Unit IDs.
- Show stale status and last-save status without implying execution happened.

### 6. Reconcile with the Plan Canvas

- After every successful create/edit/delete, feed the returned complete Plan
  into M3's pure mapper and reconcile layout for new/deleted Unit IDs.
- When a new Unit has no saved position, place it deterministically and persist
  only that position through the layout API.
- Keep operation card drop targets explicit even when cards are collapsed;
  collapse is presentation state, not a way to bypass field semantics.

## Tests and Evidence

- Data API tests cover multi-file upload, source/Snapshot grouping, profile
  selection, visible qualified columns, and hidden metadata exclusion.
- Pure drop-intent tests cover every operation/slot combination, duplicate
  chips, incompatible Snapshot refs, empty-canvas chooser actions, and the
  guarantee that no input yields an orphan node or semantic mutation.
- Workspace API tests compose Derive, Filter, Join, and Terminal fixtures,
  assert operation-specific validation, and verify stable non-contiguous IDs
  after deletion.
- Browser evidence uploads `orders.csv` and `customers.csv`, creates a Derive,
  Filter, Join, and Terminal through the Explorer/Plan Canvas, reloads, and
  confirms the same Plan and layout.
- Verify a rejected invalid Join, a cycle edge, a missing column, and a delete
  with downstream dependents leave the server-confirmed Plan unchanged.
- Run focused Python tests, frontend typecheck/lint, `ruff check .`,
  `mypy src/`, and `git diff --check`.

## Exit Criteria

- All four current operation types can be created and edited through typed
  React controls and pass existing server Plan validation.
- Qualified columns are draggable to explicit semantic slots, and ambiguous
  empty-space drops require an explicit operation choice.
- Explorer data remains Project-scoped and reloadable; no internal runtime
  objects leak into the browser model.
- Plan Canvas nodes and edges remain derived from the returned Plan after every
  operation mutation, and stale propagation remains server-authoritative.

## Risks and Mitigations

- **Ambiguous drag behavior:** require a named slot or chooser action and test
  each mapping as a pure intent function.
- **Invalid defaults block first use:** derive defaults from current public
  Snapshot facts, disable unsupported operations, and let the server explain
  remaining validation issues.
- **Form state races with server updates:** serialize semantic updates and
  replace local values only from the response; discard stale Project requests.
- **Internal metadata leaks through convenience fields:** centralize public
  DTO decoding and explicitly filter paths, checkpoints, node IDs, and hidden
  row IDs in tests.
