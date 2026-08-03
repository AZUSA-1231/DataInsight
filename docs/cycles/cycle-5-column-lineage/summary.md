# Cycle 5 Summary

## Outcome

Cycle 5 delivered the column-first, multi-table workflow for the local
single-user demo. Two or more CSV/Excel sources can coexist in one Session;
users can derive a column, filter into a named Snapshot, join Snapshots, and
run a Terminal analysis while retaining explicit checkpoint and column
provenance.

The completed acceptance path is:

```text
orders.csv + customers.csv
-> orders.revenue
-> east_orders
-> east_orders_with_customers
-> terminal artifact
-> restart-safe Session state
-> retained-checkpoint rerun
```

## Architectural Decisions

1. Schema version 2 is the durable Session contract. Older Session files are
   reported as incompatible and are not migrated or deleted.
2. DataSource, SnapshotRecord, CheckpointRecord, and ColumnNode registries are
   the source of truth. Qualified references are resolved through checkpoint
   maps rather than filesystem scans or guessed filenames.
3. Source and data-producing results are normalized to Parquet with hidden
   `__di_row_id` values. Derive preserves row identity, Filter preserves a row
   subset, and Join creates new row IDs with explicit selected aliases.
4. Join execution is deterministic pandas code. Cardinality, dtype, and
   unmatched-key risks are retained as warnings while executable operations
   continue.
5. Checkpoints are immutable and committed only after contract validation and
   atomic read-back. Reruns create new run/checkpoint records and retain prior
   results; non-cascade reruns mark downstream units stale.
6. The browser remains column-first. Snapshot, checkpoint, and Column Graph
   identifiers stay backend metadata, while the public lineage endpoint
   exposes readable origin and parent references.
7. Cycle 4 compatibility fields and the PlanUnit adapter remain bounded
   in-memory bridges. They are not used as v2 API, Planner, or executor truth;
   the former CLI is retired and new analysis starts in the browser workspace.

## Validation Evidence

The closure gates are:

```text
pytest -q
ruff check .
mypy src/
node --check static/app.js
git diff --check
```

The final result is `246 passed` with clean Ruff, mypy, frontend syntax, and
diff checks. The focused M5 closure suite covers multi-source profiles, public
lineage, complete v2 workspace shape, structured validation errors, and a real
Join with unmatched-key warnings. Browser checks covered desktop and narrow
mobile layouts plus a real operation edit.

## Deferred Work

The cycle intentionally leaves these for later PRDs: unified Copilot behavior,
visual lineage/checkpoint browsing, bounded worker isolation, an explicit data
quality workflow, wider BI operation types, automatic checkpoint cleanup,
database or cross-Session sources, hosted multi-user behavior, and a stable
evaluation harness.

## Closure Notes

Detailed PRDs, assessment material, and milestone execution plans are retained
in the cycle's `archive/` directory. The current architecture and roadmap are
the runtime-facing documents; `development-issues.md` retains resolved issue
history and the accepted legacy-adapter decision.
