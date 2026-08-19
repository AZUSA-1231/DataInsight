# Current Architecture

DataInsight is a local, single-user analysis workspace. Data inspection,
business reasoning, planning, execution, and reporting remain separate stages;
the browser is not a generic chat-to-code surface.

## Runtime Flow

The durable workspace workflow remains planner-driven:

```text
data_track -> business_track -> planner -> analysis -> report_gen
                 ^                                  |
                 +------------- feedback -----------+
```

The browser also exposes deterministic workspace operations directly:

```text
upload source
  -> profile + normalize to Parquet
  -> register Source, Snapshot, Checkpoint, and raw Column Nodes
  -> edit and validate a Plan v2
  -> execute or rerun the DAG
  -> inspect results, warnings, lineage, and report
```

Business Track and Planner receive the current source profiles and qualified
columns grouped by Snapshot. Planner output is parsed through the same
operation-specific Pydantic contract used by the workspace API.

The active browser chat is an overlay on that workflow:

```text
Project-local Thread list/detail
  -> POST /copilot with explicit thread_id
  -> fresh workspace projection + recent selected-Thread history
  -> bounded Copilot model/tool exchange
  -> final response and one user/assistant pair appended to that Thread
```

The Copilot can inspect workspace facts and propose a complete Plan edit, but
it does not commit Plan, execution, or report state. Thread messages are
Project-local and never become a global browser history. The former
`/dialogue` route remains only as a compatibility entry point for existing
clients; the browser no longer uses its Business Track loop.

## Durable State

`AgentState.schema_version` is `2`. The v2 state keeps these registries:

| Record | Responsibility |
|---|---|
| `DataSource` | Uploaded file, display name, profile, and source Snapshot/checkpoint references |
| `SnapshotRecord` | Logical view, parent Snapshots, and current checkpoint head |
| `CheckpointRecord` | Immutable Parquet result, parent checkpoints, row count, and qualified-column map |
| `ColumnNode` | Concrete column version, source origin, direct parents, and creating unit |
| `AgentChatThread` | Named ordered user/assistant messages owned by one Project |

Source ingestion accepts CSV and Excel files, creates an ASCII Snapshot name,
adds hidden `__di_row_id` values, and writes a normalized source Parquet file
below `data/output/{session_id}/sources/`. The hidden row ID is excluded from
profiles, Planner context, and the browser.

Checkpoint paths are relative to the session output root. Writes use a temporary
file, read-back verification, and atomic replacement before the registry is
updated. A missing or corrupt registered checkpoint is a mechanical execution
error; the executor does not scan directories or fall back to the uploaded
original file.

## Plan v2

`Plan.units` is a Pydantic discriminated union with `operation` as the
discriminator:

- `derive_column` adds one declared column to an existing Snapshot.
- `filter` creates a named Snapshot containing a row subset.
- `join` combines two Snapshots through the deterministic pandas executor.
- `terminal` reads one Snapshot and produces analysis artifacts without a data
  checkpoint.

Units have stable positive integer IDs, explicit dependencies, and qualified
column references such as `orders.price`. Validation is registry-aware and
checks Snapshot/column references, output names, Join aliases and keys,
dependency cycles, same-Snapshot writer chains, and the Terminal-leaf rule.
Edits mark the changed unit and transitive dependents stale. Deletion never
renumbers v2 units and requires explicit cascade deletion when dependents exist.

## Execution Contracts

The DAG scheduler executes independent topological levels in parallel while
preserving explicit dependencies. A full run starts source Snapshots from
their immutable source heads. Every successful Derive, Filter, or Join receives
a new `run_id` and unique checkpoint ID, then advances the relevant Snapshot
head and appends Column Graph nodes.

Derive preserves row count, row order, and `__di_row_id`, and adds exactly one
column. Filter preserves all columns and returns a subset of input row IDs.
Join creates new row IDs and records one direct lineage parent for each selected
output alias. Join execution is deterministic pandas code and never receives
LLM-generated Join code. It supports `inner`, `left`, `right`, `outer`, `cross`,
`semi`, and `anti` modes.

Join cardinality, key dtype, and unmatched-key risks are structured warnings,
not confirmation gates. The current warning codes are
`JOIN_MANY_TO_MANY`, `JOIN_ROW_EXPANSION`, `JOIN_KEY_DTYPE_MISMATCH`, and
`JOIN_UNMATCHED_KEYS`; warnings and row-count/statistics metadata are retained
with the unit result.

Template Derive/Filter units run in process. Generated Derive/Filter code is
statically checked and executed through the restricted local function path.
Generated Terminal analysis remains a timed subprocess path. These controls
are appropriate for a trusted local demo, not an OS security sandbox for
untrusted users.

Single-unit reruns resolve recorded input checkpoint IDs, retain prior
checkpoints and results in history, and create a new run. A non-cascade rerun
marks transitive dependents stale; a cascade rerun executes the selected
dependent chain using newly produced outputs.

## Interfaces

FastAPI exposes session, data, Project-owned Agent Thread, Copilot,
compatibility dialogue, workspace, execution, dashboard, and report routes.
The data surface includes
source/profile filtering, Snapshot heads, visible qualified columns, and
public `/data/lineage` projections that hide internal column-node IDs.
Execution responses expose run IDs, checkpoint references, row counts,
warnings, stale state, and rerun results.

The supported browser surface is now the React/TypeScript/Vite workspace. The
M2 shell provides server-backed Project history, Project creation, switching,
durable title rename, and stable Explorer, Plan Canvas, Agent, and Output Dock
mounting regions. M3 connects the Plan Canvas to the canonical Plan v2
projection: each Unit maps to one `unit:<unit_id>` node, each `depends_on`
relation maps to one edge, and positions, viewport, and collapsed state persist
through the presentation-only Workspace layout API. Semantic edge edits are
validated through the existing Unit API; layout changes never modify Plan or
execution state. Internal checkpoint IDs and column-node IDs are backend
metadata, not editable frontend objects. M4 connects the Explorer to the
Project-scoped public data projections, supports upload and profile inspection,
and exposes typed Derive, Filter, Join, and Terminal creation/editing through
the same server-confirmed Unit API. Operation creation is click-driven;
qualified column drags target explicit Unit slots and empty-canvas column drops
are rejected without creating a Unit or opening a chooser. The Unit Inspector
is a node-adjacent, internally scrollable editor, and column lists shown there
are read-only summaries so column changes have one primary path. Delete
conflicts remain server-authoritative through explicit cascade actions. Canvas
movement updates local presentation state and writes one finite, bounded layout
after drag stop or pan/zoom end; a latest-pending queue prevents an older write
from overtaking a newer one. Initial fallback positions are not written until a
user gesture or explicit Unit/layout change occurs.
M5 mounts the Agent panel with Project-local Thread list/create/select/reload
behavior, full selected-Thread history, and an explicit-thread bounded Copilot
composer. The panel cancels stale list, detail, and send requests on
Project/Thread changes and never applies Plan proposal output. M6 mounts the
Output Dock below the center canvas. Results polls only the active Project,
shows server status, stable Unit results, row-count metadata, warnings,
insights, logs, safe chart references, stale markers, and unit/cascade rerun
actions. Terminal execution refreshes Project, Explorer, and Plan projections
from the server. Report loads and generates retained Markdown while preserving
the previous report on errors. Dashboard is an explicit empty placeholder and
does not call the compatibility pin routes.

The Explorer also consumes one read-only `/data/workspace-projection` response.
For a valid Plan, the server reuses Plan validation's topological schema
simulation to expose planned Snapshot and column views without creating
registry records, checkpoints, files, or numeric execution facts. A planned
view uses a public UI identity derived from its producing Unit; materialized
views continue to use their durable Snapshot IDs. The frontend refreshes this
catalog after a server-confirmed Plan mutation without reloading Canvas layout
state. Canvas position and collapse writes carry a local revision; responses
only advance the confirmed-layout reference and cannot overwrite newer local
movement. Viewport movement remains presentation-local and is not persisted.

The maintained browser source lives under `frontend/`; `npm run build` writes
the production bundle to `static/`, which FastAPI serves at `/` and direct
`/projects/{project_id}` routes. The retired zero-build `static/app.js` and
`static/styles.css` are no longer runtime dependencies.

`SessionStore` caches states in memory and atomically persists JSON under
`data/sessions/{session_id}/state.json`. Executor-only result keys beginning
with `_`, including live DataFrames, are removed before serialization. A state
file without schema version 2 receives an explicit incompatible-session
response and is not migrated or deleted.

## Compatibility Boundary

`file_path`, `data_profile`, `unified_columns`, and the `PlanUnit` model remain
temporary Cycle 4 adapters for in-memory fixtures only. They are not v2
sources of truth. API ingestion, Planner output, workspace writes, and DAG
execution use the registries and operation-specific units. The former CLI is
retired; new analysis starts in the browser workspace.
