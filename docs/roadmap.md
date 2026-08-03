# Roadmap

## Current State

Cycle 5 is closed. The repository now supports the complete local multi-table
workflow: multi-source ingestion, qualified column references, explicit
Snapshot and Checkpoint identity, Column Graph lineage, operation-specific
Plan v2 validation, deterministic Derive/Filter/Join/Terminal execution,
structured Join warnings, retained rerun history, and a usable browser
workspace.

## Closed Cycle

**Cycle 5: Column-First Lineage and Multi-Table Foundation**

- [Cycle summary](cycles/cycle-5-column-lineage/summary.md)
- [Development issues](cycles/cycle-5-column-lineage/development-issues.md)
- [PRD, assessment, and milestone plans](cycles/cycle-5-column-lineage/archive/README.md)

The cycle delivered the approved end-to-end scope. Detailed PRDs and milestone
plans are historical artifacts under the cycle's `archive/` directory.

The acceptance path is:

```text
upload orders + customers
-> derive revenue
-> filter into east_orders
-> join customers
-> run terminal analysis
-> restart and reload the Session
-> rerun a unit while retaining prior checkpoints and lineage
```

## Deferred Candidates

These are candidates for a future PRD and are not committed scope:

1. Unified Copilot behavior across Business Track and Planner.
2. A visual lineage graph and checkpoint browser.
3. Bounded worker isolation for generated functions and resource limits.
4. Explicit, reviewable data-quality cleaning decisions.
5. Aggregate, Window, Pivot, Union, Measure, and first-class Model operations.
6. Checkpoint cleanup, cross-Session sources, database connections, and hosted
   multi-user support.
7. An evaluation harness for success rate, retries, report faithfulness, and
   latency on a stable corpus.

## Selection Rule

Choose one outcome, validate its user problem, and write one PRD representing a
fully usable cycle. Do not combine unrelated architectural upgrades simply
because they touch adjacent modules.
