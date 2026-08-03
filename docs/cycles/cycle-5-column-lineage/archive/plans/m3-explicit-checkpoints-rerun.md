# M3 Plan: Explicit Checkpoint Execution and Rerun History

## Objective

Make Snapshot heads and Checkpoint records the only execution input source.
Every successful data-producing unit creates a unique retained checkpoint and
updates registry metadata only after contract validation succeeds. Unit rerun
creates new history, advances the affected Snapshot head, and marks dependent
units stale.

## Dependencies and Boundary

- Depends on M1 persistence and M2 Plan/validation contracts.
- Delivers Derive, Filter, and Terminal execution through explicit IDs.
- Join behavior and warning classification remain in M4.
- No fallback to the original uploaded file is allowed for a v2 Plan.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/agent/dag.py` or `src/agent/executor.py` | topological scheduling and explicit input resolution |
| `src/agent/checkpoints.py` | atomic Parquet write/read and checkpoint metadata |
| `src/agent/nodes/analysis.py` | adapt template/generated/terminal paths to resolved frames |
| `src/agent/templates.py` | v2 Derive/Filter return contracts |
| `src/api/routes/execution.py` | run, status, results, rerun, and stale responses |
| `src/api/schemas.py` | durable unit result metadata and warning schemas |
| `tests/test_execution_v2.py`, `tests/test_checkpoints.py` | pure executor coverage |
| `tests/api/test_execution.py` | API run, rerun, and restart coverage |

## Execution Tasks

### 1. Introduce an execution context

- Create a per-run `run_id` and an in-memory execution context backed by the
  persisted registries.
- Resolve each unit's input from `input_checkpoint_ids` or the current Snapshot
  head recorded in the registry. Do not derive paths from `input_from`, levels,
  glob scans, or filename ordering.
- Resolve qualified refs to local DataFrame columns through the checkpoint's
  column map. Never infer availability from Plan declarations alone.
- Keep registry mutations out of worker threads. Workers return a validated
  result plus a candidate checkpoint; the coordinator commits in deterministic
  order.

### 2. Replace level-based checkpoint naming with immutable IDs

- Generate unique IDs for every successful data-producing unit, including
  initial source checkpoints from M1 and rerun outputs.
- Record `parent_checkpoint_ids`, `producer_unit_id`, `run_id`, relative path,
  row count, and qualified-column-to-node mapping.
- Write Parquet to a temporary file in the same directory, read it back for
  contract checks, atomically replace the final path, then update the registry.
- Keep prior checkpoints and Column Graph nodes. Snapshot `current_checkpoint_id`
  moves only after successful commit.

### 3. Enforce v2 unit contracts

- Derive: preserve `__di_row_id`, order, row count, and all existing columns;
  add exactly one declared output column.
- Filter: preserve all columns and a subset of input row IDs; the Plan's
  `output_snapshot` determines the resulting Snapshot name.
- Terminal: read one resolved Snapshot and produce artifacts only; never create
  a data checkpoint.
- Contract failure is a mechanical failure. No checkpoint or registry entry is
  registered, and dependents are skipped or marked blocked with an explicit
  reason.

### 4. Persist durable unit result metadata

Every result must be safe to serialize and include, where applicable:

- `input_checkpoint_ids`;
- `output_checkpoint_id` for Derive/Filter;
- `status`, `error`, `retry_count`, and model/execution metadata;
- `row_count_before`, `row_count_after`, and row-count delta;
- structured `warnings` (empty until M4);
- artifact references and `stale` state.

Live DataFrames, temporary function objects, and other executor-only values keep
the `_` prefix and are removed before session persistence.

### 5. Rebuild rerun and cascade behavior

- Resolve a single unit's input from the explicit upstream checkpoint recorded
  for that unit, not the highest file in a branch directory.
- Rerun with a new `run_id` and output checkpoint ID; retain the previous result
  history or a durable history list rather than overwriting the only audit
  record.
- Advance only the affected Snapshot head after successful commit.
- Mark all transitive dependents stale for non-cascade rerun.
- For cascade rerun, topologically execute dependents using the newly committed
  checkpoint IDs and clear stale state only after each dependent succeeds.
- Return explicit stale unit IDs and checkpoint metadata through the API.

### 6. Control parallelism

- Keep parallel execution for independent units with disjoint output Snapshots.
- Reject or serialize same-Snapshot writers according to M2's dependency rule.
- Ensure a failed unit cannot cause a dependent to read an old head silently.

## Tests and Evidence

- A valid Derive -> Filter -> Terminal run registers source, derive, and filter
  checkpoints with correct parent IDs and Snapshot heads.
- No registry entry is created when a contract check fails or an input
  checkpoint is missing.
- A missing checkpoint returns a mechanical error; it never reads the upload.
- All generated and template Derive/Filter paths preserve hidden row IDs.
- Process restart restores the registries and allows a terminal to read the same
  checkpoint.
- Single-unit rerun creates a new checkpoint, keeps the old one, advances the
  head, and marks downstream units stale.
- Cascade rerun consumes the new checkpoint at every dependent step.
- `pytest -q tests/test_execution_v2.py tests/test_checkpoints.py tests/api/test_execution.py`
- `ruff check .` and `mypy src/`

## Exit Criteria

- `execute_dag` has no `main_level`, `snapshot_levels`, directory scan, or
  original-file fallback in the v2 path.
- Every successful data-producing result points to a retained checkpoint.
- Rerun behavior is deterministic across process restart and does not destroy
  prior checkpoint provenance.
- The M3 integration scenario is complete without Join.

## Risks and Mitigations

- **Registry/file split-brain**: commit file and registry in a controlled order,
  and test failures at every boundary.
- **Rerun result growth**: define a bounded API response view while keeping
  durable history; do not discard provenance to keep the response small.
- **Terminal artifact references**: keep session-relative chart references and
  revalidate them at the API boundary as Cycle 4 does.
