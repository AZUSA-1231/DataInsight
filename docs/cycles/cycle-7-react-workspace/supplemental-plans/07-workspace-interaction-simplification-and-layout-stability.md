# M7: Workspace Interaction Simplification and Layout Stability

## Status

Implemented and validated 2026-08-17 after the Cycle 7 workspace review.

## Objective

Make the React workspace understandable without teaching users its internal
state model. Each user goal must have one primary interaction path. Keep the
workspace inside one viewport, move Unit editing beside the selected Unit,
and make presentation-layout persistence resilient during fast drag gestures.

## Product Contract

The existing operation units remain the semantic building blocks:

```text
choose operation -> create Unit -> drag qualified columns into explicit slots
                 -> edit non-column fields in the adjacent Inspector
                 -> connect dependencies -> execute
```

The browser will enforce these interaction boundaries:

- Clicking an operation in the Explorer creates a Unit. Operation dragging to
  the Canvas is removed as a duplicate creation path.
- A qualified column can be dropped only on an explicit slot of an existing
  Unit. Dropping on empty Canvas space does not open an operation chooser and
  does not create a Unit.
- Column selection controls duplicated inside the Inspector are removed or
  made read-only. Adding/removing columns uses the Unit slot interaction.
- Clicking a Unit opens a compact Inspector anchored beside that Unit. The
  Inspector uses an internal scroll area and never creates a bottom page
  section or changes the Canvas layout track.
- The application viewport is fixed to the browser height. Explorer, Agent
  history, Canvas/output content, and the adjacent Inspector own their scroll
  containers.
- A node drag updates local presentation state while moving and persists one
  validated layout after drag stop. A pan/zoom gesture persists on move end.

## Layout Persistence Contract

`WorkspaceLayout` remains presentation-only state. It retains Unit positions,
viewport, and collapsed state across Project reloads, but it is not a semantic
Plan update and does not trigger execution.

The frontend implementation will:

1. Apply position changes locally during `onNodesChange` without starting a
   network write.
2. Build a complete layout from the final node position in `onNodeDragStop`.
3. Reject non-finite or incomplete coordinates before JSON submission and fall
   back to the last server-confirmed layout.
4. Serialize only the versioned layout fields and current Unit IDs.
5. Queue at most the latest pending layout so an older request cannot overwrite
   a newer drag result.
6. Avoid writing auto-generated fallback positions during initial projection
   loading; persist only user gestures or explicit collapse changes.
7. Preserve structured server error details for diagnosis rather than showing
   only a generic shape error.

The backend route remains the authoritative schema validator. A backend change
is allowed only if it improves diagnostics or makes the existing presentation
contract safer; Plan v2 semantics must not move into layout state.

## Implementation Notes

- Operation palette items are click-to-create buttons. Operation drag payloads
  and the empty-Canvas column chooser were removed.
- Column fields in the Inspector are read-only summaries. Qualified columns are
  added through explicit Unit slots; Join key slots can initialize an empty key
  pair when the first side is dropped.
- `NodeToolbar` anchors the Inspector beside the selected Unit, flips to the
  left when the right edge has insufficient room, and keeps form content in an
  internal scroll region. Escape, blank Canvas clicks, and the close control
  dismiss it.
- The app root and workspace shell are constrained to `100dvh`; Explorer,
  Agent history, Output, and Inspector own their scroll containers.
- Layout writes use a latest-pending queue. Movement events update local state,
  drag stop and move end enqueue validated snapshots, and invalid coordinates
  restore the last server-confirmed projection.

## Implementation Scope

| Area | Change |
|---|---|
| Operation palette | Click-to-create only; remove operation drag payloads |
| Column drops | Remove empty-canvas chooser; keep explicit Unit slots |
| Inspector | Render as a Unit-adjacent React Flow toolbar/popover with internal scroll |
| Workspace shell | Fixed viewport and card-owned scroll containers |
| Plan Canvas | Local drag updates; one validated save after drag stop |
| Layout API | Preserve route; add finite/shape guards and latest-write protection |
| Tests | Interaction, Inspector placement, scroll containment, layout timing, and invalid-coordinate regressions |
| Docs | Record M7 decisions, validation, and any residual responsive limitations |

## Acceptance Criteria

- A user can create Derive, Filter, Join, or Terminal through one visible
  operation action.
- A column dropped on empty Canvas space never opens a chooser or creates an
  operation.
- A selected Unit exposes its Inspector beside the Unit without adding a
  bottom section or browser-level page height.
- The browser document does not scroll during normal desktop workspace use;
  long Explorer, Agent, Output, and Inspector content scrolls inside its card.
- Fast node dragging produces no `INVALID_WORKSPACE_LAYOUT` response and no
  repeated write per movement frame.
- A completed drag survives Project switch and browser reload.
- Invalid layout coordinates are rejected locally and recover to the last
  confirmed layout without corrupting Plan state.
- Existing Plan, execution, rerun, report, Agent, and backend compatibility
  tests remain green.

## Verification

```text
cd frontend
npm.cmd run typecheck
npm.cmd run lint
npm.cmd run test
npm.cmd run build

cd ..
pytest -q
ruff check .
mypy src/
git diff --check
```

The focused frontend tests must assert that movement-only events do not call
`PUT /workspace/layout`, drag stop does, stale requests cannot win, and invalid
coordinates do not reach the API. The backend layout tests must retain schema,
duplicate-ID, unknown-ID, and bounded-coordinate coverage.

## Validation Evidence

```text
frontend: npm.cmd run typecheck  passed
frontend: npm.cmd run lint       passed
frontend: npm.cmd run test       37 tests passed
frontend: npm.cmd run build      passed
backend:  pytest -q              277 passed
backend:  ruff check .           passed
backend:  mypy src/              passed
repo:     git diff --check       passed
```

The local Vite server responded on `http://127.0.0.1:5173`. A browser binary or
Playwright/Puppeteer package is not installed in this workspace, so screenshot
and pointer-trace evidence remains an environment limitation.
