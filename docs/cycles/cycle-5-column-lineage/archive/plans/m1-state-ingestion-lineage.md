# M1 Plan: State, Multi-Source Ingestion, and Initial Lineage

## Objective

Deliver the durable v2 session foundation. A session can accept multiple CSV or
Excel sources, normalize each source to a Parquet checkpoint with a hidden
stable row ID, and persist raw Columns, Snapshots, and Checkpoints without
changing the Plan or executor yet.

## Dependencies and Boundary

- Depends on: Cycle 4 closure baseline only.
- Enables: all later Cycle 5 work.
- Does not implement: Plan v2 operations, Join, rerun, or the new browser
  workflow.
- Cycle 4 sessions are explicitly incompatible; no migration code is added.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/agent/state.py` | `AgentState` v2 and persisted references; retain dialogue, feedback, pins, plan, results, and report fields |
| `src/agent/lineage.py` | `DataSource`, `Snapshot`, `Checkpoint`, `ColumnNode`, registry helpers, path validation, and typed registry errors |
| `src/agent/ingestion.py` | Read CSV/Excel, deterministic profile, source-name allocation, `__di_row_id` injection, and atomic source checkpoint creation |
| `src/agent/nodes/data_track.py` | Per-source inspection adapter; no single `file_path` assumption |
| `src/api/session.py` | v2 creation, atomic persistence, typed incompatible-state handling |
| `src/api/routes/data.py` | Append upload behavior and source/Snapshot/Column query endpoints |
| `src/api/schemas.py` | v2 data and session response models |
| `src/api/app.py` | Explicit incompatible-session response for session access |
| `tests/test_lineage.py`, `tests/test_ingestion.py` | Pure model, registry, and normalization coverage |
| `tests/api/test_data.py`, `tests/api/test_sessions.py` | Upload, response, restart, and incompatibility coverage |

## Execution Tasks

### 1. Define persisted v2 objects

- Add `schema_version: Literal[2]` to `AgentState`.
- Replace `file_path`, `data_profile`, and `unified_columns` as state sources of
  truth with `data_sources`, `snapshot_registry`, `checkpoint_registry`, and
  `column_graph`.
- Keep `user_requirement`, dialogue, Planner instruction, Plan, results, pins,
  report, error, and timestamps in the v2 state.
- Use `Field(default_factory=...)` for mutable collections.
- Store paths as durable strings or relative references only. DataFrames never
  enter the state model.

### 2. Implement source and lineage registry behavior

- Allocate an ASCII Snapshot ID from the filename stem. Resolve collisions as
  `_2`, `_3`, and so on; preserve the original filename as `display_name`.
- Define one source Snapshot and one initial source Checkpoint per upload.
- Create raw Column Graph nodes with `source_table`, `source_column`, dtype,
  row count, and root origin metadata.
- Make registry operations return new Pydantic values or immutable-style copies;
  callers must not mutate `AgentState` in place.
- Validate that every registry path stays below the session output root.

### 3. Normalize and profile sources

- Reuse deterministic CSV/Excel loading and profiling behavior.
- Inject `__di_row_id` once at normalization time. IDs must be stable after a
  restart and unique across source Snapshots; exclude the hidden column from
  profile, Planner context, and browser responses.
- Write the normalized Parquet atomically and register it only after the file
  can be read back with the expected row count and columns.
- Preserve original column names and dtype metadata.

### 4. Add schema-gated persistence

- Make new sessions write `schema_version: 2` immediately.
- Make `load()` distinguish missing, malformed, and incompatible state files.
- Add a typed `IncompatibleSessionError` rather than converting it to `None`.
- Return a distinct API error, such as HTTP 409 with a stable error code, for
  old or unsupported state files. Never delete or rewrite those files.
- Use isolated temporary session directories in tests so existing local data is
  not modified.

### 5. Convert upload and data APIs to append semantics

- Persist each upload under its session without replacing prior sources.
- Return the new source, Snapshot, row count, and visible qualified columns.
- Add read endpoints for all sources, Snapshots, and qualified columns. Keep a
  temporary compatibility response only where it does not make v1 state the
  source of truth.
- Reject duplicate or invalid source references deterministically.

### 6. Adapt non-execution consumers enough to boot on v2

- Update application session status to derive `has_data` from `data_sources`.
- Update CLI construction to create a v2 source/session context for its single
  input file; do not retain `file_path` in persisted state.
- Update data-track and basic Business Track context construction to consume
  source profiles and qualified columns. Full Plan v2 prompt work belongs to
  M2.

## Tests and Evidence

- Two CSV uploads create two independent Snapshots and two source checkpoints.
- Reusing the same filename produces a deterministic Snapshot collision suffix.
- CSV and Excel sources normalize to readable Parquet with stable hidden row IDs.
- Raw Column Graph nodes point to the correct source table and source column.
- A second `SessionStore` restores the complete v2 registry.
- A handcrafted Cycle 4 state file returns the explicit incompatibility result;
  its file remains unchanged.
- `pytest -q tests/test_lineage.py tests/test_ingestion.py tests/api/test_data.py tests/api/test_sessions.py`
- `ruff check .` and `mypy src/`

## Exit Criteria

- No v2 code needs `state.file_path` to locate source data.
- A session can list every uploaded source, current Snapshot head, and visible
  qualified column without scanning the filesystem.
- Initial source checkpoint registration is atomic and restart-safe.
- All remaining Cycle 4 tests have either been migrated to v2 fixtures or are
  intentionally removed because they assert incompatible behavior.

## Risks and Mitigations

- **Path ambiguity**: use session-relative registry paths and one resolver;
  never let API input select an arbitrary Parquet file.
- **Row identity drift**: verify `__di_row_id` uniqueness and round-trip values
  immediately after normalization.
- **Partial upload**: do not update state until source file, profile, and source
  checkpoint all succeed; remove only the newly created temporary file on a
  failed transaction.
