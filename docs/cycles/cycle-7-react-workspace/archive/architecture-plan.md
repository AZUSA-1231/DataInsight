# Cycle 7 Architecture Plan: React Project Workspace

## Status

Archived after Cycle 7 implementation. This document records the architecture
used to deliver the product PRD; current runtime behavior is maintained in
docs/architecture/current.md.

Terms in this document follow [the project glossary](../../../glossary.md). In
particular, Plan Canvas is the Plan editor and Workspace layout is presentation
state; neither term means the deferred Result Canvas / Board.

## Architectural Outcome

The existing FastAPI application remains the local product backend. A Vite
application becomes the browser client. Project state remains session-scoped
and durable through SessionStore; Cycle 7 extends that single durable state
with small Project metadata, Agent conversation threads, and presentation-only
Workspace layout.

~~~text
Development

Vite dev server (React + TypeScript) -- API proxy --> FastAPI --> SessionStore
                                                          |
                                                          +--> session JSON state
                                                          +--> project output directory

Production

FastAPI -- serves Vite build --> browser
        -- serves the same API contracts --> SessionStore
~~~

The browser does not obtain Parquet paths, live DataFrames, internal checkpoint
IDs, Column Graph node IDs, or hidden row IDs. It consumes the existing public
projections and the new small Project, Agent, and layout projections.

## Frontend Build Boundary

Create a maintained source application at:

~~~text
frontend/
  index.html
  package.json
  vite.config.ts
  tsconfig.json
  src/
    app/
    api/
    domain/
    features/
      projects/
      explorer/
      workspace/
      agent/
      output/
    styles/
~~~

Use React, TypeScript, Vite, and the React Flow implementation from the
xyflow project for the graph viewport, pan and zoom, controls, minimap, node
drag, and connection gestures. Keep application state modest:

- Server-backed resources use one typed API client and a query and mutation
  boundary.
- Local selection, open panes, and temporary drag state stay in React state.
- No client-side copy of Plan is authoritative over API responses.
- No generic plugin or action framework is introduced.

Vite development proxies API requests to the local FastAPI server. For this
cycle, `frontend/vite.config.ts` writes the production build to the existing
`static/` mount (`build.outDir = "../static"`, with the legacy image asset moved
to `frontend/public` first). The generated files replace the old zero-build
HTML/CSS/JS; maintained UI source lives only under `frontend/`. FastAPI keeps
the `static` mount so API-only tests do not require Node, while production and
browser checks run `npm run build` before serving.

The build migration also changes frontend validation from node syntax checking
to project scripts such as typecheck, lint, and build. The README and workspace
guidance must be updated in the implementation change so documented validation
matches the supported frontend.

## Durable State Model

Continue to use one Project state file and one SessionStore. The user-facing
Project ID remains the existing session ID and keeps its output and upload
scope. No second Copilot database, cross-project store, or live-data
persistence is introduced.

Add typed defaults to AgentState. These names are implementation targets:

~~~python
class AgentChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    created_at: str

class AgentChatThread(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    messages: list[AgentChatMessage] = Field(default_factory=list)

class WorkspaceNodeLayout(BaseModel):
    unit_id: int
    x: float
    y: float
    collapsed: bool = False

class WorkspaceViewport(BaseModel):
    x: float = 0
    y: float = 0
    zoom: float = 1

class WorkspaceLayout(BaseModel):
    version: Literal[1] = 1
    viewport: WorkspaceViewport = Field(default_factory=WorkspaceViewport)
    nodes: list[WorkspaceNodeLayout] = Field(default_factory=list)

class AgentState(BaseModel):
    project_title: str = "Untitled project"
    created_at: str | None = None
    agent_threads: list[AgentChatThread] = Field(default_factory=list)
    workspace_layout: WorkspaceLayout = Field(default_factory=WorkspaceLayout)
~~~

Exact field spelling may follow repository conventions, but the ownership
boundary must not change:

| State | Owns | Must not contain |
|---|---|---|
| Plan | unit operation fields and dependency relationships | positions, viewport, React Flow nodes or edges |
| WorkspaceLayout | Unit-keyed position, viewport, harmless display state | duplicated Unit fields, edge definitions, sources, columns, execution metadata |
| AgentChatThread | one thread's human and assistant messages and metadata | another Project's messages or workspace copy |
| existing registries and results | sources, checkpoints, lineage, execution, report | client presentation-only state |

New Project creation sets a title, creation time, and one empty default Agent
thread. Project title rename is an explicit user action. Thread titles begin
with a deterministic New chat label and may be replaced by a short first-message
excerpt; manual thread renaming is not required for Cycle 7.

### Existing Conversation Migration

Cycle 6 persists dialogue history at Project scope. A small Project
conversation service performs one lazy, atomic migration:

1. If Agent threads already exist, use them and do not read dialogue history.
2. If no threads exist and legacy history is non-empty, create one default
   thread containing those messages, clear the legacy source, and persist the
   resulting AgentState through one SessionStore update.
3. If neither exists, create the default empty thread.

After this conversion, only Agent-thread messages are read or written by the
Cycle 7 Copilot path. This prevents a global history mirror from leaking
messages across Agent chats.

The context sent to a Copilot turn takes a bounded recent window from the
selected thread only. The full selected-thread history remains available for
the UI. Fresh Project workspace context remains shared because every Agent
chat inside a Project is intentionally discussing the same analysis workspace.

## Project and Agent APIs

The existing session routes remain compatible. Add typed public projections
rather than exposing raw state files:

| Route | Purpose |
|---|---|
| GET sessions | List Project summaries, newest first |
| POST sessions | Create a Project; accept an optional title while preserving existing request fields |
| GET session by project ID | Existing state summary, augmented with safe Project metadata |
| PATCH session by project ID | Rename a Project |
| GET agent chats for project | List thread metadata for that Project |
| POST agent chats for project | Create a new Agent thread |
| GET one agent chat for project and thread | Read one thread and its messages |
| GET workspace layout for project | Read presentation-only Workspace layout |
| PUT workspace layout for project | Persist presentation-only layout |
| POST copilot for project | Existing Copilot route, extended with an explicit selected thread ID request field |

The concrete paths follow the existing session-scoped API naming convention:

~~~text
GET    /api/sessions
PATCH  /api/sessions/{project_id}
GET    /api/sessions/{project_id}/agent-chats
POST   /api/sessions/{project_id}/agent-chats
GET    /api/sessions/{project_id}/agent-chats/{thread_id}
GET    /api/sessions/{project_id}/workspace/layout
PUT    /api/sessions/{project_id}/workspace/layout
POST   /api/sessions/{project_id}/copilot
~~~

The new Project list scans only valid Session directories and reads safe JSON
summary fields. It must not load artifacts or return absolute paths,
checkpoints, raw profile samples, or full messages. It should handle
schema-incompatible or malformed old state safely: incompatible Projects may be
surfaced as unavailable summaries or skipped according to existing policy, but
they must not be silently migrated or deleted.

Project summary projection includes only:

~~~text
project_id, title, created_at, persisted_at,
source_count, unit_count, has_results, has_report,
agent_chat_count, compatibility or status marker
~~~

Thread routes verify that a thread ID belongs to the Project addressed by the
path. Copilot receives no arbitrary thread object and no cross-project ID. The
new frontend always supplies its selected thread ID; a no-thread fallback can
be retained temporarily for compatibility callers while it resolves the
Project default thread.

The legacy `/dialogue` and `/dialogue/stream` routes remain compatibility
routes only: they resolve the Project's default Agent Thread and adapt their
Cycle 6 response shapes without writing a competing global history. The React
application never calls them. The Cycle 7 UI does not bind plan generation as a
primary action because the active Copilot path does not create the required
legacy PlannerInstruction and Cycle 7 excludes proposal application. Manual
Plan construction remains the coherent primary workflow.

## Plan Canvas Data Contract

The Plan Canvas must be assembled through pure mappings. It is not a second
serialized workflow.

### Canonical Mapping

~~~text
Plan.units
  unit #N
    -> React Flow node id unit:N
    -> node type derived from unit.operation
    -> node data derived from the complete current unit and public source facts

Plan.units[*].depends_on
  source unit A in target unit B
    -> React Flow edge id unit:A->unit:B
    -> source unit:A, target unit:B

WorkspaceLayout.nodes
  unit #N presentation record
    -> node position and harmless display state only
~~~

There are no persisted source nodes, column nodes, arbitrary annotation nodes,
or separately persisted edges. Explorer columns are drag payloads, not Plan Canvas
entities. If a future visual lineage feature needs other graph types, it needs
a separate PRD and cannot weaken this Plan Canvas mapping.

### Reconciliation

Implement a pure mapper similar to:

~~~text
toPlanCanvas(plan, layout, publicWorkspaceFacts) -> nodes, edges
~~~

The mapper:

1. Creates one node per current Plan unit using the stable Unit ID.
2. Creates every edge from the target unit dependency list.
3. Applies a matching layout record when one exists.
4. Assigns deterministic positions for missing layout records, based on
   topological level then Unit ID.
5. Ignores unknown layout records in memory and schedules their removal on the
   next layout save.

The layout endpoint validates unique Unit IDs, finite coordinates, sane zoom
limits, and that every saved record belongs to the current Plan. It rejects
ghost Unit IDs. The client may initially have no position for a newly created
Unit, but the mapper still produces exactly one visible operation node; it then
persists the reconciled layout.

### Mutation Semantics

| UI intent | Canonical mutation | Not permitted |
|---|---|---|
| Drop operation palette item on Plan Canvas | Existing workspace-unit create endpoint, then layout save for returned Unit ID | Creating an untyped or free-form node |
| Edit a node field | Existing unit update endpoint, with the explicit operation field patch | Editing a serialized node copy without changing Plan |
| Drop column in a named card slot | Explicit unit update for that semantic field | Heuristic generic-drop assignment |
| Create a connection A to B | Add A to B dependency list through unit update | Inferring snapshot or column routing |
| Remove a connection A to B | Remove A from B dependency list through unit update | Deleting a Unit or data output implicitly |
| Delete a Unit | Existing deletion endpoint, with explicit cascade confirmation if required | Renumbering v2 Unit IDs |
| Drag a Unit card | Debounced layout update | Changing Plan or dependency semantics |
| Pan and zoom | Debounced layout update | Changing Plan |
| Server-confirmed Plan refresh | Rebuild nodes and edges through mapper | Retaining stale client node data |

All Plan mutations are serialized per active Project in the client. An API
response becomes the canonical Plan before the next semantic action is applied.
This is sufficient for the single-user boundary and avoids rapid gesture
responses overwriting each other. Layout writes are independently debounced but
must be cancelled or scoped when the active Project changes.

### Drag and Drop Details

An operation drag is valid only when the client can form a valid initial
operation from currently visible source and Snapshot facts. The create helper
migrates the existing default-payload behavior into typed frontend code, then
lets the server remain the validator. If prerequisites are absent, the palette
explains what data is needed rather than creating an invalid placeholder.

Column drags carry a public qualified reference and origin Snapshot. A target
declares a single action:

- Derive, Filter, and Terminal input-column slots append or select a declared
  input reference.
- Derive output is edited as a declared output-column name, not created by
  dragging an input column.
- Join key-left, key-right, and selected-output slots are distinct. A selected
  output drop produces an explicit alias that the user can edit.
- A column drop onto empty Plan Canvas invokes an explicit operation and action menu
  before any Plan mutation.

The client never derives input fields from a Plan Canvas connection. Data routing
continues to be expressed by validated Snapshot and qualified-column fields on
the Plan unit.

## React Workspace Composition

~~~text
App shell
  Header
    ProjectSwitcher / ProjectRename / NewProject / LocalUser
  Explorer
    Upload / SourceTree / SnapshotDetails / OperationPalette
  Workspace
    CanvasToolbar / PlanCanvas / NodeInspector / OperationNodes
    OutputDock
      ResultsTab / ReportTab / DashboardPlaceholder
  AgentPanel
    AgentThreadList / MessageHistory / Composer / ToolStatus
~~~

The Node Inspector remains inside the center workspace region, either as an
overlay or contextual panel. The right application column stays dedicated to
Agent interaction. The output dock is independently collapsible and does not
replace the visual Plan workspace.

The styling layer starts with light-theme CSS variables, readable contrast,
keyboard focus states, and responsive minimum-width behavior. Styling should
not block functional delivery; component boundaries are intentionally ready for
a later visual-design cycle.

## Existing API Integration

The React API client uses existing endpoints as follows:

| Existing API group | React feature |
|---|---|
| data upload, sources, snapshots, columns, profile, lineage | Explorer, detail panels, and card field options |
| workspace and workspace units | Plan Canvas reads and edits |
| copilot | Selected Agent thread composer |
| execution run, status, results, rerun, charts | Results Output Dock |
| report and report generation | Report Output Dock |
| dashboard | Not called by the finished UI; Dashboard placeholder only |

Execution polling starts only for the active Project and is stopped when the
user switches Project, closes the view, or sees a terminal execution status.
The frontend re-fetches public data projections after a successful execution
or rerun because Snapshot heads and visible columns may have changed.

## Copilot Thread Integration

Refactor the bounded turn handler history dependency behind a small
Project-thread resolver. Its sequence becomes:

~~~text
POST copilot with message and thread ID
  -> load Project
  -> resolve thread owned by that Project
  -> build fresh workspace projection
  -> use only selected thread recent messages
  -> bounded model and tool exchange
  -> atomically append user and final-assistant pair to that same thread
  -> return turn result
~~~

The existing bounded round, model, and tool limits and tool-safety restrictions
remain unchanged. Plan edit remains a proposal-only tool. The frontend can
render a neutral tool-used marker or collapsible tool summary, but it does not
acquire a Plan from the response and does not call a Plan mutation endpoint on
its behalf.

## Validation Strategy

### Backend and API

Add focused tests for:

- Project list ordering and safe summary projection;
- Project create and title rename and restart persistence;
- default Agent-thread creation;
- thread creation, read, and Project ownership checks;
- strict message isolation in stored history and Copilot context;
- legacy dialogue-history one-time migration;
- layout validation, unknown-Unit rejection, and restart persistence;
- Plan mutation and layout reconciliation behavior at the API boundary;
- continued compatibility of existing data, workspace, execution, report, and
  Copilot tests.

### Frontend

Test pure Plan Canvas mappings and intents independently of React Flow:

- one Plan Unit maps to one stable node;
- dependency lists map to exactly the expected edges;
- no layout data changes Plan semantics;
- missing layout produces deterministic placement;
- deleted Unit layout records are pruned;
- each named column drop creates only its documented field patch.

Use browser verification for the full acceptance path: project switch, renamed
Project reload, Agent-thread switch and restart, multi-source Plan composition,
Plan Canvas move and reload, execute and rerun, and report. Validate the new
frontend with package scripts for linting, TypeScript, and production build
alongside:

~~~text
pytest -q
ruff check .
mypy src/
git diff --check
~~~

## Explicitly Deferred Decisions

- Copilot Plan proposal display, durable proposal state, diff, Accept, and
  Reject.
- Whether Agent-thread titles receive a richer automatic title generator; a
  deterministic first-message fallback is sufficient here.
- Dashboard data model and polished dashboard UI.
- Full visual design system, theme variants, and responsive or mobile redesign.
- Multi-user Project ownership or collaboration.
- Any visual lineage or checkpoint browser beyond the Plan Canvas.
