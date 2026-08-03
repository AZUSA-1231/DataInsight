# Cycle 5 Development Issues

## Purpose

This document tracks concrete implementation defects, contract inconsistencies,
and unresolved migration risks found during Cycle 5 development. It is not a
general task log.

Add an entry only when a milestone exposes a problem or a meaningful
inconsistency. Keep resolved entries for historical context, and carry open
entries into the milestone that owns the fix. A milestone that completes
without a new issue does not need an entry.

Last updated: 2026-08-03

## Status Summary

| ID | Status | Milestone | Area |
|---|---|---|---|
| DEV-001 | Resolved | M2-M3 | Strict Plan discriminator versus Cycle 4 fixtures |
| DEV-002 | Resolved | M2 | Runtime import regression in registry validation |
| DEV-003 | Resolved | M3 | Legacy checkpoint execution and rerun projection |
| DEV-004 | Accepted by decision | M3-M5 | Legacy Plan adapter boundary |
| DEV-005 | Resolved | M5 / cycle closure | Current architecture documentation drift |
| DEV-006 | Resolved | M4 | Join dispatcher boundary |
| DEV-007 | Resolved | M5 | Filter predicate contract |
| DEV-008 | Accepted by decision | M5 retrospective | Closure scope and browser artifact hygiene |

## Resolved Issues

### DEV-001: Plan discriminator conflicted with legacy fixtures

- **Found in:** M2 Plan v2 parsing.
- **Symptom:** A v2 Plan uses `operation` as a strict discriminator, so
  ordinary unit JSON without `operation` is rejected. Existing Cycle 4 tests
  and CLI paths still construct the old `PlanUnit` shape.
- **Impact:** Removing the old shape immediately would break the existing
  compatibility surface; accepting missing `operation` would make v1 data
  silently look like v2 data and weaken the persisted contract.
- **Resolution:** Keep strict v2 parsing and retain `PlanUnit` only as an
  explicit legacy adapter. Planner output, workspace API writes, and persisted
  v2 Plans use operation-specific models and do not treat `unit_type`,
  `input_from`, or `related_fields` as v2 sources of truth.
- **Follow-up:** The adapter is temporary. Its boundary is tracked as DEV-004.
- **M3 policy decision:** This is a personal, continuously evolving demo. Git
  history is the compatibility mechanism, so old fixtures and old execution
  semantics may be deleted or rewritten instead of being supported.

### DEV-002: Registry validation had a runtime-only import regression

- **Found in:** M2 registry-aware validation.
- **Symptom:** A type used by a runtime validation path was available only under
  `TYPE_CHECKING`, causing a `NameError` when the path executed.
- **Resolution:** Move the required runtime import to the normal import block
  and leave only type-only registry annotations under `TYPE_CHECKING`.

### DEV-003: The v2 executor still had a legacy checkpoint projection

- **Found in:** M2 boundary review.
- **Resolution in M3:** Replaced level/branch path resolution with Snapshot
  head and explicit CheckpointRecord resolution. Missing or corrupt checkpoints
  now fail mechanically; the executor has no original-file fallback or
  directory scan. Successful data units write a unique Parquet checkpoint
  atomically, then advance the Snapshot head and registry.
- **Rerun evidence:** Reruns create new run and checkpoint IDs, preserve prior
  results in history, mark downstream units stale for a non-cascade rerun, and
  pass the newly committed head through cascade execution.

### DEV-005: Current architecture documentation described the pre-Cycle 5 runtime

- **Found in:** M1-M2 documentation review.
- **Risk:** Stale documentation described a single-file Cycle 4 runtime and old
  checkpoint assumptions while the implementation had multi-source registries
  and operation-specific models.
- **Resolution:** Rewrote `docs/architecture/current.md` around the v2
  Source/Snapshot/Checkpoint/Column Graph model, explicit operation contracts,
  warning semantics, rerun behavior, API projections, and the compatibility
  boundary. Closed Cycle 5 in `docs/roadmap.md` and updated documentation
  entry points.
- **Evidence:** The architecture, roadmap, README, cycle summary, and issue
  tracker now describe the same v2 runtime.

### DEV-006: Join had a single-input generated-code escape path

- **Found in:** M4 deterministic Join integration.
- **Symptom:** The shared `_execute_unit` entry could classify Join through its
  compatibility transform projection when called outside the DAG dispatcher.
- **Impact:** A direct caller could send a Join without a right checkpoint,
  violating the deterministic two-input boundary.
- **Resolution:** Route Join exclusively through the pandas dispatcher in
  `src/agent/dag.py` and guard `_execute_unit` against single-input Join calls.
  The guard does not create a checkpoint or invoke an LLM.

### DEV-007: Frontend Filter predicates were narrower than the Plan contract

- **Found in:** M5 browser acceptance review.
- **Symptom:** The v2 workspace emits a general Filter predicate such as
  `region == 'East'`, but the existing `filter_by_date` template only accepted
  `start` and `end` date parameters.
- **Impact:** A valid operation-specific Plan could reach execution without a
  deterministic implementation for the predicate shown in the UI.
- **Resolution:** Added a condition branch to `filter_by_date` using pandas
  `query(engine="python")`, preserving the existing Filter result contract
  and output Snapshot handling.
- **Evidence:** The M5 workflow fixture uses the East-region predicate, and a
  focused template regression test covers a non-date condition.

### DEV-008: M5 closure scope was too broad for one execution batch

- **Found in:** M5 retrospective.
- **Symptom:** M5 combined API contracts, frontend workflow implementation,
  report and CLI consumers, browser acceptance, and cycle documentation. The
  browser acceptance then required several CDP viewport and interaction runs,
  which created multiple temporary profiles and screenshots.
- **Impact:** The implementation remained correct, but progress reporting was
  less granular and cleanup became part of the milestone closeout. This made
  the milestone feel substantially longer than M1-M4.
- **Decision:** Keep the completed M5 plan unchanged. For future cycles, split
  similar closure work into backend/API, frontend workflow, browser acceptance,
  and documentation sub-milestones. Use one temporary browser profile per
  validation pass and remove profiles/screenshots immediately after evidence is
  captured.
- **Evidence:** Final validation passed with 246 tests; all known CDP profiles,
  screenshots, and the local test server were cleaned after verification.

## Accepted Decisions

### DEV-004: Legacy Plan compatibility is intentionally not a product constraint

- **Decision:** Do not spend milestone capacity preserving Cycle 4 fixtures,
  PlanUnit execution, or old checkpoint semantics. M3 execution accepts only
  operation-specific Plan v2 units; obsolete tests were rewritten around the
  v2 contract.
- **Residual cleanup:** Remaining adapter fields may be removed in a later
  focused cleanup, but they do not constrain the v2 runtime or acceptance path.

## Open Issues and Follow-up Risks

No blocking implementation issues remain for Cycle 5. DEV-004 records the
intentional legacy-adapter boundary; removing unused adapter fields is optional
future cleanup rather than a v2 correctness requirement.

## Review Rule for Later Milestones

At the end of each milestone, review this document against the milestone exit
criteria. Close an open item only after its stated evidence is available. If a
milestone completes cleanly, record no new issue and report that fact in the
milestone handoff.

## M3 Handoff

M3 completed without a new blocking issue. The execution boundary is now
v2-only and the checkpoint/rerun acceptance path is covered by the validated
v2 execution suite, clean Ruff and mypy output, and a successful frontend
syntax check.
