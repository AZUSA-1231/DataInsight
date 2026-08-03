# Cycle 5 PRD: Column-First Lineage and Multi-Table Foundation

## Product Outcome

DataInsight users can upload multiple tabular sources and build a reviewable
Plan that derives columns, filters rows into named Snapshots, joins Snapshots,
and produces terminal analysis artifacts. The workspace remains column-first:
users manipulate columns while the backend records where each column came from
and which physical checkpoint currently carries it.

## Problem

The Cycle 4 executor can move one wide table through Transform, Filter, and
Terminal units, but its runtime identity is implicit. It selects inputs through
`input_from`, in-memory branch levels, and checkpoint filename scans. Column
availability is inferred from Plan declarations rather than recorded from
successful execution.

This prevents reliable multi-table analysis and makes it difficult to answer
basic provenance questions:

- Which source table and source column contributed to this output column?
- Which filter or derivation produced the current values?
- Which exact checkpoint did a unit read or produce?
- What changed after a unit rerun?

## Product Principles

- `Plan` remains the shared editing surface for the user and the agent.
- Columns remain the primary objects presented in the frontend.
- Plans use readable qualified references such as `orders.revenue`.
- Snapshot, checkpoint, and column-node identifiers remain backend metadata.
- The system records analytical risks but does not decide whether a user's
  analysis is meaningful.
- Mechanical errors stop execution; analytical risks produce warnings and
  continue whenever the requested operation can be executed faithfully.
- Successful checkpoints are immutable and retained for lineage and reruns.

## In Scope

1. Multi-source CSV and Excel ingestion within one Session.
2. Source normalization to Parquet with a hidden stable row identifier.
3. Snapshot, checkpoint, and Column Graph persistence.
4. A Plan v2 contract for `derive_column`, `filter`, `join`, and `terminal`.
5. Deterministic Plan validation and explicit checkpoint input resolution.
6. Deterministic joins with structured cardinality and alignment warnings.
7. Unit rerun against explicit upstream checkpoints with retained history.
8. A column-first browser workflow for all supported operations.

## Out of Scope

- Business Track and Planner consolidation into a unified Copilot.
- Aggregate, Window, Pivot, Union, Measure, and first-class Model operations.
- A visual lineage graph or checkpoint browser.
- Automatic checkpoint cleanup.
- Cycle 4 Session migration.
- Cross-Session data sharing, database connections, and hosted multi-user use.

## End-to-End Acceptance Scenario

The cycle is complete when a user can:

```text
upload orders + customers
-> derive orders.revenue
-> filter orders into east_orders
-> join east_orders with customers
-> run terminal analysis
-> restart the application
-> inspect the same Plan and results
-> rerun one unit without losing prior checkpoints or column provenance
```

The resulting lineage must identify the source of every selected Join output,
the Filter inheritance path, and the direct parents of the derived revenue
column.

## Success Criteria

- Two uploaded files coexist as independently named source Snapshots.
- Every physical data-producing result has a unique retained checkpoint.
- Every visible column resolves to a persisted Column Graph node.
- Derive preserves row identity and adds exactly one declared column.
- Filter produces a named Snapshot containing an indexed row subset.
- Join supports the declared join modes and produces explicit selected output
  columns.
- Many-to-many and row-expanding joins execute with structured warnings.
- Missing Snapshots, missing columns, duplicate aliases, and invalid DAG
  references fail before a checkpoint is registered.
- Full execution, process restart, and single-unit rerun preserve consistent
  Plan, registry, warning, and result state.
- The repository passes its Python, type, lint, frontend syntax, and browser
  workflow validation gates.

## Compatibility Decision

Persisted Session state uses schema version 2. Cycle 4 Session files are not
migrated or converted. Loading one must return an explicit incompatible-schema
response without deleting its files.
