# Cycle 7 PRD: React Project Workspace

## Status

Delivered and closed after the audited completion of Cycle 6.

The canonical vocabulary for this PRD is [the project glossary](../../../glossary.md),
especially the distinction between Project, Agent conversation, Plan Canvas,
Workspace layout, and Result Canvas / Board.

## Outcome

DataInsight has a usable local project workspace built with React, TypeScript,
and Vite. The old zero-build browser UI is retired. A user can create, rename,
list, reopen, and switch durable analysis projects; work with multiple
independent Agent conversations inside each project; inspect data sources and
qualified columns; assemble the existing Plan v2 in a zoomable Plan Canvas;
run and rerun the existing execution DAG; and review results and reports from
a collapsible output area.

The outcome is an IDE-style shell, not a generic chat-to-code product. The
existing product path remains visible:

~~~text
inspect data -> edit a visible Plan -> execute the DAG -> retain evidence
~~~

## Problem

The current browser is a single zero-build page. It already exposes much of the
Cycle 5 and Cycle 6 backend, but mixes sources, operation forms, results,
dashboard, report, and chat into one fixed layout. It remembers only one
session ID in browser storage. Durable sessions and Copilot history exist on
disk, but there is no project-history UI or API, no way to view an earlier
conversation, and no distinction between an analysis project and an Agent
conversation.

The central workspace must become visual without splitting meaning across two
incompatible models. A Plan is an executable, validated DAG. The Plan Canvas
is a presentation and interaction layer. If both independently store operation
configuration or dependency state, they will eventually disagree and make the
analysis untrustworthy.

## Product Vocabulary

Cycle 7 uses these terms consistently in the UI and APIs:

| Term | Meaning | Durable boundary |
|---|---|---|
| Project | One existing Session: sources, Snapshots, Plan, results, report, visual layout, and Agent conversations. | One existing session state and output scope |
| Agent conversation | One named, ordered conversation within one Project. It shares that Project's workspace facts but never receives messages from another conversation. | A thread collection inside the Project state |
| Plan | The existing validated Plan v2 and its units/dependencies. It is the semantic source of truth for the execution DAG. | Existing AgentState Plan field |
| Workspace layout | Positions, viewport, and other presentation-only state for Plan Canvas Units. It never contains an independent operation or dependency definition. | A separate presentation field in Project state |

The backend may retain session_id naming for compatibility. The user-facing
label is Project.

## Principles

- The frontend makes the existing inspect, plan, execute, and evidence stages
  easier to see and control; it does not replace them with free-form code chat.
- A Project and an Agent conversation are different scopes. Project workspace
  state is shared by its conversations; conversation messages are isolated.
- Plan semantics have exactly one durable authority. Plan Canvas nodes and edges
  are derived views of that authority, while Workspace layout has an explicitly
  limited presentation role.
- Every Plan Canvas gesture has one documented semantic meaning. A drag must target
  a specific Plan field or open an explicit choice; it must never guess an
  operation from an ambiguous drop.
- Existing Plan validation, stale propagation, execution, rerun, lineage, and
  report semantics remain authoritative.
- This is a trusted, local, single-user product. The header may show a fixed
  Local user identity; Cycle 7 does not introduce authentication or accounts.
- The first visual pass is intentionally light and functional rather than a
  final visual-design system.

## User Experience

### Header and Project History

The header contains the DataInsight logo, active Project title, a Project
history control, a New Project action, and a fixed local-user affordance.

The Project history control lists persisted Project summaries, newest first.
Each entry shows a user-editable project title, recent activity time, source
count, unit count, and high-level output state. Selecting an entry changes the
active project without creating a new one. The active project is also encoded
in the browser URL and remembered as the last active project for convenience;
the server-side Project list is the authority for history.

Project title editing is explicit and immediately persisted. A new project
starts as Untitled project. Deleting Projects is not part of the Cycle 7 UI:
the existing backend deletion route does not yet define cleanup of uploads and
artifacts, so surfacing it would imply a lifecycle guarantee that does not
exist.

### Left Explorer

The left Explorer contains:

1. An upload entry point for the existing CSV and Excel ingestion flow.
2. A tree of Sources, logical Snapshots, and visible qualified columns.
3. Source and Snapshot facts already available from profiles: row count, column
   type, null information, and sample/profile details on selection.
4. An Operations palette containing the existing Derive, Filter, Join, and
   Terminal unit types.

Qualified columns are draggable. Operation types are draggable. Hidden row IDs,
checkpoint IDs, Column Graph node IDs, and live data remain absent from the
browser model.

### Center Plan Canvas

The center workspace is a pan-and-zoom grid with controls to fit the graph and
recover a usable view. It presents one operation card for each Plan unit and
visual dependency edges between cards. A small minimap is appropriate when the
graph is larger than the viewport.

Operation cards use the already supported operation-specific contracts:

- Derive: input Snapshot, input columns, exactly one declared output column,
  execution mode and template settings.
- Filter: input Snapshot, predicate columns, output Snapshot, predicate and
  template settings.
- Join: left/right Snapshots, explicit key pairs, selected output aliases,
  join type, and output Snapshot.
- Terminal: input Snapshot, selected columns, and artifact settings.

Cards offer visible, operation-specific column drop slots. For example, a
column dropped into Derive input columns means exactly that. Join exposes
separate slots for left/right keys and selected outputs. A generic card-body
drop is not allowed where it would be ambiguous.

Dragging an operation from the palette onto free Plan Canvas space creates one valid
operation Unit and records its placement. Dropping a column on empty Plan Canvas
opens a small explicit action chooser, such as Derive, Filter, or Terminal,
then creates the selected operation with the column attached to the chosen
field. It never leaves an orphan column node behind.

Selecting a card opens a center-pane inspector or expanded card content for
the full operation form. This retains all current operation capabilities
without turning every graph card into a large fixed form.

Users may create and delete dependency connections on the Plan Canvas. A connection
means only that the target Unit depends on the source Unit. It maps to
depends_on; it does not silently guess a Snapshot, input column, Join key, or
data transformation. Existing server validation rejects cycles and invalid
Plan shapes, and the Plan Canvas returns to the server-confirmed state on failure.

### Plan Canvas and Workspace Layout Contract

This is the central Cycle 7 product constraint.

~~~text
Plan unit #17                         Plan Canvas operation node
------------------                    -----------------------------
unit_id: 17                 <----->   id: unit:17
operation: filter                      type: filter
depends_on: [12]                       edge id: unit:12->unit:17
all operation fields                  rendered from the same Plan unit

Workspace layout:
position / viewport / collapsed state only
~~~

The following invariants are required:

1. Every current Plan unit renders as exactly one operation node. A Plan Canvas
   operation node always identifies exactly one existing unit ID.
2. A node's operation type and editable fields are derived from its Plan unit,
   never persisted as a second copy inside the layout.
3. Every Plan Canvas edge is derived from exactly one depends_on relation. Edges are
   not saved separately.
4. A layout record may store only presentation data keyed by unit ID. It cannot
   create an operation, source, column, edge, or hidden data route.
5. A Plan update rebuilds the Plan Canvas from canonical server state. A semantic
   Plan Canvas action writes through the existing Plan API, then reconciles from its
   response. A visual move writes only layout state.
6. Unknown or deleted unit IDs are pruned from layout. Missing positions
   receive deterministic placement, so a valid Plan can always be displayed.

This is bidirectional interaction, not two semantic sources of truth:

~~~text
Plan change -> derive cards and edges -> Plan Canvas
Plan Canvas field or edge action -> explicit Plan mutation -> validated Plan
Plan Canvas move or viewport action -> Workspace layout mutation only -> Plan Canvas
~~~

### Right Agent Panel

The right panel is the Copilot entry point, styled as an IDE Agent panel. It
contains a list of Agent conversations belonging to the active Project, a New
Agent Chat action, historical messages for the selected conversation, and a
message composer.

Creating a new Agent chat starts an empty conversation in the current Project.
It has access to that Project's sources, Plan, execution state, and report, but
not to messages from previous chats or from any other Project. Switching
Projects also switches the available Agent conversation list. Existing
conversation messages must be reloadable after browser or server restart.

Cycle 6's bounded Copilot remains the only active chat runtime. Cycle 7 keeps
its normal and slash-skill behavior, including its read-only Plan proposal
boundary. The UI may show that a tool was used, but it must not imply that a
Copilot Plan proposal has been applied.

### Output Dock

A collapsible dock at the bottom of the center pane keeps the primary workspace
focused while retaining execution evidence:

- Results: execution status, per-unit results, warnings, stale state, row
  metadata, charts, rerun, and cascade rerun.
- Report: generate and read the existing report.
- Dashboard: an intentionally blank placeholder page in this cycle.

Dashboard pinning and presentation are not migrated into the new UI. The
existing backend endpoints remain compatible but are not treated as a finished
product surface.

## In Scope

1. A new React, TypeScript, and Vite frontend that replaces the old zero-build
   browser application.
2. A functional light-theme IDE layout: Header, Explorer, Plan Canvas, Agent
   panel, and collapsible Output Dock.
3. Project listing, creation, switching, and durable title rename.
4. Multiple durable, isolated Agent conversations per Project, including
   conversation history viewing and new-chat creation.
5. Minimal Project-state and API additions needed for Project summaries, Agent
   threads, and presentation-only Workspace layout.
6. Visual editing of all existing Plan v2 operation types and their current
   API-supported fields.
7. Drag and drop of columns and operation types with explicit semantic targets.
8. Plan Canvas dependency edge editing mapped to depends_on.
9. Existing upload, source/profile, Snapshot, lineage, execution, rerun,
   chart, and report endpoints connected to the new frontend.
10. A blank Dashboard placeholder in the Output Dock.
11. Regression and frontend validation appropriate to the new build system.

## Out of Scope

- Copilot Plan proposal persistence, diff UI, Accept, Reject, or silent Plan
  mutation.
- New analysis operations, templates, execution semantics, checkpoints, or
  sandbox capabilities.
- A generic visual programming model, arbitrary code nodes, free-form source
  nodes, or a second DAG representation.
- Dashboard product work, dashboard pin UI, or backend dashboard redesign.
- Authentication, accounts, multi-user sharing, cloud sync, or cross-Project
  Agent-memory sharing.
- Source deletion and cleanup policy, Project deletion UI, checkpoint cleanup,
  or data-file lifecycle redesign.
- Final brand and visual-polish work beyond a coherent light functional theme.
- Restoring the legacy dialogue workflow as a primary user path.

## Existing Capability Migration

The new UI must preserve the currently useful surface rather than reduce the
product to a mock Plan Canvas:

| Existing capability | Cycle 7 destination |
|---|---|
| Multi-file CSV/Excel upload | Explorer upload entry |
| Sources, Snapshots, qualified columns, profile and lineage facts | Explorer and detail view |
| Derive, Filter, Join, Terminal creation and forms | Plan Canvas cards and inspector |
| Plan validation and stale-state behavior | Server-confirmed Plan Canvas mutations |
| Execute, polling, results, warnings, charts | Results tab in Output Dock |
| Unit and cascade rerun | Results tab |
| Report generation and retained report | Report tab |
| Bounded Copilot | Right Agent panel with per-conversation history |
| Dashboard pins | Not migrated; Dashboard is a placeholder |
| Legacy dialogue route | Not used by the React frontend |

## Compatibility and Migration

Existing schema-version-2 Project files remain valid. New optional state fields
must have defaults so the state schema is not needlessly bumped for this UI
cycle.

An existing dialogue history is converted once into a default Agent
conversation when a Project first uses Cycle 7 conversation APIs. The
conversion is persisted atomically in the same Project state. After conversion,
Agent thread messages are the only conversation source of truth; the
implementation must not maintain a competing global history and thread history.

The old static files are intentionally replaceable. Vite production output
becomes the frontend served by FastAPI. The source application, not generated
assets, is the maintained UI code.

## Acceptance Scenarios

1. A user opens the application, sees a server-backed list of prior Projects,
   renames one, switches to it, and sees its sources, Plan, output, and Agent
   conversations after restart.
2. In one Project, a user creates two Agent chats. Messages from the first do
   not appear in the second or enter its Copilot context. A second Project has
   its own separate thread list.
3. A user uploads orders and customers, drags an operation to the Plan Canvas,
   drops qualified columns into explicit fields, creates a Join and Terminal,
   and sees a Plan that passes existing server validation.
4. A user pans, zooms, and rearranges Unit cards, reloads the Project, and sees
   the same presentation layout while the Plan remains unchanged. Editing a
   card or dependency updates the Plan and produces the correct rebuilt graph.
5. A user runs the Plan, watches status in the Output Dock, reviews warnings
   and charts, reruns one Unit or its dependent chain, and generates a report.
6. A user opens Dashboard and sees a clear empty placeholder rather than a
   partially functional pinning UI.

## Success Criteria

- The React workspace is the supported browser surface and the old zero-build
  app is no longer required at runtime.
- A Project list and rename flow operate from durable server state, not only
  browser local storage.
- Agent conversations persist and are strictly Project-scoped and
  thread-scoped in both UI display and Copilot context.
- The Plan Canvas has a documented, testable one-to-one Plan-unit and node mapping
  and no duplicated semantic graph state.
- All four current operation types can be composed and edited through the new
  workspace and still pass existing Plan validation.
- Existing execution, rerun, and report evidence remains reachable from the
  new UI.
- Dashboard is visibly deferred rather than represented as complete.
- Repository validation passes with the Python suite plus the new frontend
  type, build, lint, and browser checks.
