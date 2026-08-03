# Cycle 5 Current-State Assessment

## Evidence

- The repository is on `arch-evolution` at the Cycle 4 closure commit.
- The working tree contains documentation changes for Cycle 5, but no Cycle 5
  implementation code.
- The current validation baseline is 269 passing tests, clean Ruff output,
  clean strict mypy output, and a successful `node --check static/app.js`.
- The current implementation is still the single-file Cycle 4 model. The
  active PRD and master plan are therefore a forward design, not a description
  of code that already exists.

## What Is Reusable

| Area | Current capability | Cycle 5 value |
|---|---|---|
| State and persistence | Pydantic state, atomic JSON writes, runtime-value stripping | Persistence pattern can be retained, state payload must be v2 |
| Inspection | Deterministic CSV and Excel profiling | Can remain the source of data facts, but must run per source |
| Execution | Typed Transform, Filter, Terminal paths, template dispatch, restricted generated functions | Contract validation and terminal isolation are reusable |
| Checkpoints | Parquet files and complete-table chaining | File format is reusable; identity and resolution are not |
| API | Session-scoped FastAPI routes and stable artifact paths | Route structure is reusable; data and plan contracts must change |
| Frontend | Working zero-build workspace, column drag/drop, execution polling | Interaction shell is reusable; single-table assumptions are pervasive |
| Tests | 269 tests cover the Cycle 4 behavior well | Fixtures and tests must move to v2 rather than preserve false compatibility |

## Main Gaps

### 1. State is still v1 and single-source

`AgentState` requires `file_path` and stores one `data_profile` plus one
`unified_columns` list. `SessionStore.create()` writes that shape and
`SessionStore.load()` accepts it without a schema gate. The upload route writes
one path and replaces the previous source. This blocks multi-source ingestion,
durable lineage, and the required explicit incompatible-session response.

### 2. Plan semantics are still implicit

`PlanUnit` uses `unit_type`, `input_from`, and broad column lists. The Planner's
custom parser currently drops operation routing, execution mode, template
metadata, and input-source metadata from JSON. Workspace deletion also
renumbers units. These behaviors conflict with the v2 discriminated union and
stable unit IDs.

### 3. Execution identity is still runtime-local

`execute_dag()` tracks `main_level` and `snapshot_levels` in local variables,
resolves branches from `input_from`, and can fall back to the original file
when a checkpoint is missing. Checkpoints are named by branch and level rather
than registered immutable records. `_save_unit_checkpoint()` logs some contract
violations and continues. This is not sufficient for explicit input
resolution, atomic registry updates, or auditably correct reruns.

### 4. Rerun does not yet satisfy the Cycle 5 contract

The API rerun path scans checkpoint filenames, falls back to `state.file_path`,
does not register a new checkpoint, and replaces the prior unit result. A
cascade rerun resolves each dependent independently instead of carrying the
newly produced checkpoint through the cascade. Cycle 5 must make checkpoint
history and snapshot heads the source of truth.

### 5. The operation layer has no Join contract

The template registry currently contains arithmetic, regression, date filter,
and scatter plot functions. There is no operation-specific Plan model, no
deterministic Join executor, no selected-column alias contract, and no
structured warning model for cardinality, dtype mismatch, or unmatched keys.

### 6. API and browser surfaces expose the old object model

The data API returns one profile and one flat column list. The browser keeps one
`App.columns` array, uploads only the first dropped file, and renders fields
from `related_fields`. Unit cards do not expose operation-specific inputs,
output Snapshots, joins, warnings, or checkpoint-backed rerun state.

### 7. Report and agent context still depend on v1 fields

Business Track, Planner, report generation, the CLI, and session status all
read `data_profile`, `unified_columns`, or `file_path` directly. They must be
adapted as part of the state and context migration; otherwise the backend can
execute v2 data while the agent and report continue describing a nonexistent
single table.

## Risk Assessment

| Risk | Severity | Reason | Control |
|---|---|---|---|
| State migration breaks every entry point | Critical | `AgentState` is constructed in CLI, API, graph, and tests | Establish v2 state and isolated schema tests first; do not silently migrate Cycle 4 files |
| Registry and Parquet diverge | Critical | A checkpoint can be visible on disk before metadata is durable | Write to a temporary path, validate, atomically replace, then persist the registry update |
| Concurrent writers corrupt a Snapshot chain | High | Current level-parallel executor can run same-branch writers in parallel | Validate same-Snapshot writers as one dependency chain and only parallelize independent outputs |
| Qualified references become ambiguous | High | Column names may repeat across sources or contain dots | Resolve refs through registry maps, not filesystem names or string guesses |
| Join behavior is analytically risky | High | Many-to-many and dtype mismatch can produce valid but surprising output | Continue executable joins with structured warnings and persist warning evidence |
| Frontend is rebuilt against unstable APIs | Medium | The current UI is tightly coupled to v1 response fields | Finish and test API contracts before wiring the browser |
| Legacy tests mask incomplete migration | Medium | Cycle 4 tests assert old behavior such as overwrite and reindexing | Replace contradictory tests and add explicit v2 rejection tests |

## Decisions To Freeze Before M1

1. **Qualified reference semantics**: user-facing refs are
   `<snapshot>.<column>`. Snapshot names are ASCII identifiers. Original column
   names remain unchanged inside a snapshot and are resolved through a
   registry, so a column containing a dot is never parsed by guessing.
2. **Physical frame semantics**: a checkpoint stores local column names plus
   hidden `__di_row_id`; the checkpoint registry maps qualified refs to Column
   Graph node IDs. Join output columns use the declared aliases in the output
   Snapshot. This keeps pandas operations simple while preserving visible
   provenance.
3. **Storage boundary**: uploaded source files remain under the session upload
   directory; normalized source Parquet files and analysis checkpoints remain
   below `data/output/{session_id}/`. Registry paths are relative to the
   session output root and are never reconstructed by directory scanning.
4. **Schema incompatibility**: a state file without `schema_version: 2`, or
   with another version, is not migrated or deleted. `SessionStore` raises a
   typed incompatible-state error and the API returns a distinct conflict
   response.
5. **Warning policy**: mechanical reference, contract, and filesystem errors
   stop the affected operation before registry commit. Join cardinality and
   alignment risks are durable warnings and do not block an otherwise
   executable pandas operation.
6. **Plan validation boundary**: Pydantic validates the Plan v2 shape. A
   deterministic registry-aware validator simulates the DAG and validates
   Snapshot, Column, alias, writer-chain, and dependency rules. The API and
   Planner use the same validator.

## Recommended Delivery Order

```text
M1 state + ingestion + initial lineage
  -> M2 Plan v2 + registry-aware validation
  -> M3 explicit checkpoints + rerun
  -> M4 Derive/Filter/Join + warning semantics
  -> M5 API/frontend/report + end-to-end closure
```

M2 must not be merged without M1's registry API. M3 must not retain a fallback
to the original file. M4 should add Join only after a complete
Derive -> Filter -> Terminal path is executable with explicit checkpoint IDs.
M5 is the product completion pass, not a place to hide unresolved backend
contracts.

## Definition Of Ready For Implementation

- The five detailed plans below are accepted as the implementation sequence.
- The field matrix for Plan v2 and the registry-aware validation rules are
  agreed before coding M2.
- Test fixtures include at least two sources with duplicate key names, a
  filter subset, a derived column, duplicate join keys, unmatched keys, and a
  restart/rerun scenario.
- No Cycle 4 state file or output directory is used as a v2 acceptance fixture.
