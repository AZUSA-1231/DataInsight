# Cycle 5 Master Plan: Column-First Lineage and Multi-Table Foundation

## Summary

Preserve the existing product model:

- `Plan` remains the shared editing surface for users and agents.
- The frontend continues to expose columns as the primary data objects.
- The backend adds Snapshot, Checkpoint, and Column Graph tracking.
- Analytical risks produce warnings instead of blocking execution.
- Only mechanical failures, such as missing columns or invalid references,
  stop execution.

The cycle must deliver this complete workflow:

```text
Upload orders + customers
-> derive revenue
-> filter into east_orders
-> join customers
-> generate terminal analysis
-> preserve column lineage across restart and rerun
```

## Detailed Execution Plans

The work is split into dependency-ordered plans. Each plan has its own test
evidence and exit criteria; later plans must not reintroduce a fallback to the
single-file Cycle 4 model.

- [Current-state assessment](assessment.md)
- [M1: State, ingestion, and initial lineage](plans/m1-state-ingestion-lineage.md)
- [M2: Plan v2 and deterministic validation](plans/m2-plan-v2-validation.md)
- [M3: Explicit checkpoints and rerun history](plans/m3-explicit-checkpoints-rerun.md)
- [M4: Data operations and warning semantics](plans/m4-data-operations-warnings.md)
- [M5: API, frontend, and cycle closure](plans/m5-api-frontend-closure.md)

Recommended order:

```text
M1 -> M2 -> M3 -> M4 -> M5
```

M1 freezes the persisted identity model. M2 freezes Plan semantics. M3 makes
checkpoint IDs authoritative. M4 adds deterministic Join behavior. M5 exposes
the complete workflow and records closure evidence.

## Core Contracts

### AgentState

Upgrade persisted state to schema version 2. Cycle 4 Sessions are intentionally
incompatible.

```json
{
  "schema_version": 2,
  "data_sources": [],
  "snapshot_registry": {},
  "checkpoint_registry": {},
  "column_graph": {"nodes": {}},
  "plan": null,
  "analysis_result": null
}
```

Replace the single-file fields `file_path`, `data_profile`, and
`unified_columns` with:

- `data_sources`: uploaded files, profiles, and source Snapshots.
- `snapshot_registry`: logical Snapshots and their current checkpoints.
- `checkpoint_registry`: every retained physical checkpoint and its columns.
- `column_graph.nodes`: concrete column versions and their immediate parents.

### Column Graph

Plans use readable qualified references such as `orders.price`. During
execution, each reference resolves to an internal `column_node_id` in the
selected checkpoint.

```json
{
  "node_id": "coln_run01_u1_revenue",
  "ref": "orders.revenue",
  "name": "revenue",
  "snapshot": "orders",
  "dtype": "float64",
  "row_count": 1000,
  "source_table": null,
  "source_column": null,
  "origin_columns": ["orders.price", "orders.quantity"],
  "created_by_unit_id": 1,
  "derived_from_node_ids": ["coln_orders_price", "coln_orders_quantity"]
}
```

Raw columns populate `source_table` and `source_column`. Derived columns record
both direct parents and all root origins. A rerun may create a new node for the
same qualified reference; old nodes and checkpoints remain available.

### Snapshot and Checkpoint

```json
{
  "snapshot": {
    "snapshot_id": "snap_orders",
    "name": "orders",
    "display_name": "orders.csv",
    "current_checkpoint_id": "cp_run01_u1",
    "created_by_unit_id": null,
    "parent_snapshot_ids": []
  },
  "checkpoint": {
    "checkpoint_id": "cp_run01_u1",
    "snapshot_id": "snap_orders",
    "parent_checkpoint_ids": ["cp_source_orders"],
    "producer_unit_id": 1,
    "run_id": "run01",
    "path": "checkpoints/cp_run01_u1.parquet",
    "row_count": 1000,
    "columns": {
      "orders.price": "coln_orders_price",
      "orders.quantity": "coln_orders_quantity",
      "orders.revenue": "coln_run01_u1_revenue"
    }
  }
}
```

Every uploaded source is normalized to Parquet and receives a hidden
`__di_row_id`. This column is excluded from the frontend and LLM context but is
used to validate Derive and Filter row identity.

### Plan v2

Change `Plan.units` into a Pydantic discriminated union using `operation` as
the discriminator. Integer `unit_id` values remain stable and are never
renumbered. New units use `max(unit_id) + 1`.

Supported operations:

- `derive_column`
- `filter`
- `join`
- `terminal`, preserving current chart, statistics, model, and report behavior

```json
{
  "units": [
    {
      "unit_id": 1,
      "operation": "derive_column",
      "execution_mode": "template",
      "purpose": "Calculate order revenue",
      "cautious": "",
      "depends_on": [],
      "input_snapshot": "orders",
      "input_columns": ["orders.price", "orders.quantity"],
      "output_columns": ["orders.revenue"],
      "template_name": "column_arithmetic",
      "params": {"operator": "*", "new_column": "revenue"}
    },
    {
      "unit_id": 2,
      "operation": "filter",
      "execution_mode": "llm",
      "purpose": "Select East-region orders",
      "cautious": "",
      "depends_on": [1],
      "input_snapshot": "orders",
      "input_columns": ["orders.region"],
      "output_snapshot": "east_orders",
      "params": {"condition": "region == 'East'"}
    },
    {
      "unit_id": 3,
      "operation": "join",
      "execution_mode": "template",
      "purpose": "Add customer segments",
      "cautious": "",
      "depends_on": [2],
      "inputs": [
        {"role": "left", "snapshot": "east_orders"},
        {"role": "right", "snapshot": "customers"}
      ],
      "output_snapshot": "east_orders_with_segment",
      "join": {
        "how": "left",
        "keys": [{
          "left": "east_orders.customer_id",
          "right": "customers.customer_id"
        }],
        "select": [
          {"from": "east_orders.order_id", "as": "order_id"},
          {"from": "east_orders.revenue", "as": "revenue"},
          {"from": "customers.segment", "as": "segment"}
        ]
      }
    }
  ],
  "alignment_notes": ""
}
```

`related_fields`, `input_from`, and the old `unit_type` cease to be sources of
truth. Frontend field chips are derived directly from operation inputs.

## Implementation Milestones

### M1: Multi-Source Ingestion and Initial Lineage

- Change upload behavior from replacing one file to appending data sources to
  a Session.
- Generate an ASCII Snapshot identifier from each filename stem. Resolve
  collisions with `_2`, `_3`, and so on while preserving the original filename
  as the display name.
- Normalize CSV and Excel inputs to Parquet with `__di_row_id`.
- Create an initial Snapshot, checkpoint, and raw Column Nodes for each source.
- Add APIs for querying sources, Snapshots, and qualified columns.
- Return an explicit incompatible-schema response for old Sessions without
  deleting their files.

### M2: Plan v2 and Deterministic Validation

- Implement operation-specific discriminated models and parse Planner output
  through `Plan.model_validate`.
- Remove the partial custom parser that currently drops operation, template,
  and routing fields.
- Provide Business Track, Planner, and `inspect_column` with multi-Snapshot
  qualified column context.
- Validate Snapshot references, column references, output names, and DAG
  dependencies whenever a Plan is saved.
- Require Derive writers targeting the same Snapshot to form one explicit
  dependency chain. This is a checkpoint consistency rule, not an analytical
  restriction.
- Require Filter and Join units to create unused Snapshot names.
- Never renumber units after deletion. Reject deletion with downstream
  dependents unless cascade deletion is explicitly requested.
- Mark an edited Unit and all transitive dependents stale.

### M3: Explicit Checkpoint Execution

- Replace `main_level`, `snapshot_levels`, `input_from`, and directory scanning
  with Snapshot-to-checkpoint resolution.
- Assign a `run_id` to every execution and a unique checkpoint ID to every
  successful data-producing Unit.
- Write checkpoints atomically and update registries only after contract
  validation succeeds.
- Remove fallback to the original file when a Snapshot or checkpoint is
  missing. Missing references are mechanical errors.
- Resolve rerun input from the latest successful upstream Unit outputs.
- Preserve every successful checkpoint, update the affected Snapshot head,
  and mark transitive dependents stale.
- Add `input_checkpoint_ids`, `output_checkpoint_id`, `warnings`, and row-count
  changes to Unit results.

### M4: Data Operations

- Derive continues using `_unit(df, input_columns, params)`. It must produce
  exactly one new column while preserving `__di_row_id`, order, and row count.
- Filter continues returning `filtered_df`. The Plan determines the output
  Snapshot name. It must preserve all columns and return a subset of input row
  IDs.
- Join uses a deterministic pandas executor rather than LLM-generated Join
  code.
- Support `inner`, `left`, `right`, `outer`, `cross`, `semi`, and `anti` joins.
  All non-cross joins require keys.
- Require Join `select` entries to declare output columns and aliases.
  Duplicate aliases are mechanical errors.
- Generate a new unique row ID for Join output and record direct lineage for
  every selected output column.
- Preserve the existing Terminal template and subprocess paths. Terminal reads
  one Snapshot and produces no checkpoint.

### M5: Warnings, APIs, and Frontend Completion

- Record key dtypes, duplicate keys, unmatched keys, input/output row counts,
  and observed Join cardinality.
- Emit structured `JOIN_MANY_TO_MANY`, `JOIN_ROW_EXPANSION`,
  `JOIN_KEY_DTYPE_MISMATCH`, and `JOIN_UNMATCHED_KEYS` warnings.
- Continue execution whenever pandas can perform the requested Join.
- Keep columns as the only draggable frontend data objects. Group them by
  source or Snapshot and show origin labels only when needed for
  disambiguation.
- Add operation-specific controls to Unit cards without exposing checkpoint
  IDs or internal node IDs.
- Display execution warnings without requiring confirmation.
- Update current architecture and roadmap documentation.
- Record decisions covering the Snapshot/Checkpoint/Column Graph model,
  permissive warning policy, and Session incompatibility.

## Test Plan

- Uploading two files creates two source Snapshots, normalized checkpoints,
  qualified columns, and correct raw lineage.
- Derive preserves row IDs and row count, adds exactly one column, and records
  all direct parents.
- Filter creates a new Snapshot, creates inherited column nodes, and preserves
  a subset of input row IDs.
- Join records correct lineage for selected columns and supports every declared
  Join type.
- Many-to-many joins and row expansion emit warnings but complete successfully.
- Missing columns, duplicate output aliases, invalid dependencies, and unknown
  Snapshots fail before checkpoint registration.
- A complete `derive -> filter -> derive -> join -> terminal` DAG produces
  valid artifacts and reports.
- Session restart restores registries, Plan, warnings, results, and checkpoint
  references.
- Unit rerun creates a new checkpoint, preserves the previous one, advances the
  Snapshot head, and marks downstream Units stale.
- Unordered writers targeting one Snapshot fail Plan validation; independent
  output Snapshots remain parallelizable.
- Planner JSON round-trips without losing operation, execution mode, inputs,
  outputs, templates, or parameters.
- The browser supports multi-file upload, qualified-column dragging, Unit
  editing, execution, and warning display.
- Final validation includes `pytest -q`, `ruff check .`, `mypy src/`,
  `node --check static/app.js`, and a real browser workflow.

## Assumptions and Deferred Work

- Cycle 4 Sessions are not migrated or converted. They receive an explicit
  incompatibility message.
- Business Track and Planner remain separate during Cycle 5. Unified Copilot
  work belongs to a later cycle.
- Aggregate, Window, Pivot, Union, Measure, and first-class Model operations
  are deferred.
- Lineage visualization, automatic checkpoint cleanup, cross-Session sources,
  and database connections are deferred.
- The system does not decide whether a Join is meaningful for the business
  question. It guarantees faithful execution, visible provenance, and explicit
  risk reporting; analytical responsibility remains with Agent Review and the
  user.
