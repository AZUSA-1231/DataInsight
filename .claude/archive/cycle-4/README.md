# Cycle 4 Archive — DAG-Native Execution

**Period**: 2026-07-08 to 2026-07-31
**Branch**: `arch-evolution`
**Closure baseline**: 269 tests passing, Ruff clean, strict mypy clean

## Outcome

Cycle 4 replaced the provisional CSV-concatenation executor with a structured
DAG runtime. A PlanUnit now declares its unit type, execution mode, topology,
input source, and column contract. Data moves through complete Parquet
checkpoints and named snapshot branches rather than implicit column merges.

The cycle also completed the product continuity needed by the local browser
workspace: analysis state is durable across restarts and API artifacts use
stable session-scoped paths.

## Delivered Milestones

1. **M1 — PlanUnit and checkpoint engine**: Transform/Filter/Terminal types,
   template/LLM modes, Parquet branch checkpoints, and column validation.
2. **M2 — Template system**: deterministic arithmetic, regression, date filter,
   and scatter templates using the common unit result contract.
3. **M3 — LLM contracts**: unit-type-specific generation prompts and return
   contracts.
4. **M4 — Unit rerun**: checkpoint input resolution, transitive stale marking,
   and optional cascade rerun API.
5. **M5 — Contract MVP**: deterministic 4-node Filter -> Transform -> Transform
   -> Terminal integration test with rerun consistency.
6. **M6 — Unified function path and persistence**: generated Transform/Filter
   functions share template validation; Terminal retains subprocess execution;
   SessionStore persists JSON state and restores completed workspaces.

## M6 Recovery Note

The final Claude Code session approved a five-task M6 plan but implemented only
the generated-function path and part of its test migration before reporting
completion. Closure work recovered the omitted scope:

- added real generated-function, retry, and contract-failure tests;
- separated in-process return rules from old output.csv sandbox rules;
- made contract violations fail and retry rather than log and continue;
- persisted state atomically while excluding live DataFrames;
- moved API artifacts out of temporary directories;
- restored browser sessions, results, charts, and reports after restart;
- corrected Windows-only test paths and completed type checking.

## Architecture Decisions

- `decisions-early.md`: D51-D53, the first clean-slate/DAG design pass.
- `decisions.md`: D54-D61, final checkpoint, rerun, generated-function,
  persistence, and artifact-path decisions.

D55 supersedes the CSV data-passing portion of D53. D59 records the accepted
trusted-local boundary of in-process Transform/Filter execution.

## Artifact Map

- `prds/cycle-4-dag-executor.prd.md` — final product requirements and M1-M6 status
- `plans/cycle-4-dag-executor.plan.md` — M1 implementation plan
- `plans/cycle-4-dag-executor-m2.plan.md` through `-m5.plan.md` — M2-M5
- `plans/cycle-4-m6-inprocess-llm.plan.md` — recovered and completed M6 plan
- `plans/m1-clean-slate.plan.md` through `m4-test-and-validate.plan.md` — early
  architectural exploration, superseded by the final DAG-native plans
- `audits/code-review-cycle-3-remediation.plan.md` — pre-cycle remediation input

## Deferred Work

The following were deliberately not pulled into closure:

- frontend DAG canvas and edge editor;
- hosted/untrusted execution isolation;
- multi-table joins and field provenance;
- explicit data-cleaning workflow;
- database-backed multi-user persistence.

These are candidates for a new product cycle, not unfinished Cycle 4 tasks.

## Documentation Transition

Cycle 1-4 implementation artifacts remain under `.claude/archive/`. Current,
tool-neutral documentation moved to `docs/`, and Codex repository guidance is
in `AGENTS.md`. No active PRD or implementation plan remains after closure.
