# Roadmap

## Current State

Cycle 4 is closed. The repository has a field-driven workspace, structured DAG
units, Parquet checkpoints, template and generated execution paths, unit rerun,
session persistence, a local API, and a functional browser workspace.

There is intentionally no active implementation plan. The next cycle should be
chosen by product outcome, not by continuing leftover engineering tasks.

## Candidate Outcomes

These are candidates for a future PRD, not committed scope:

1. **Visual DAG intervention** — expose unit type, dependencies, snapshots,
   execution mode, stale state, and rerun controls in the browser workspace.
2. **Execution isolation** — move generated functions to a bounded worker with
   timeout and resource controls while preserving the unified function contract.
3. **Data quality workflow** — add explicit, reviewable cleaning decisions
   without reintroducing a hidden preprocessing stage.
4. **Multi-table analysis** — define ingestion-level joins and field provenance
   before expanding the executor beyond one wide table.
5. **Evaluation harness** — measure first-run success, retry rate, report
   faithfulness, and latency on a stable corpus of real analysis questions.

## Selection Rule

Choose one outcome, validate its user problem, and write one PRD representing a
fully usable cycle. Do not combine unrelated architectural upgrades simply
because they touch adjacent modules.
