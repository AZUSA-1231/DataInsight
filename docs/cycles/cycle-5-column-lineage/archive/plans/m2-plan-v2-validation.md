# M2 Plan: Plan v2 and Deterministic Registry-Aware Validation

## Objective

Replace the loose Cycle 4 `PlanUnit` model with a Pydantic discriminated union
for `derive_column`, `filter`, `join`, and `terminal`. Validate the complete Plan
against the current Snapshot and Column registries before it can be saved or
executed.

## Dependencies and Boundary

- Depends on M1's v2 state and registry APIs.
- Does not change checkpoint execution yet; M3 consumes this validated Plan.
- Does not add a visual lineage graph or a new BI operation catalog.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/agent/state.py` or `src/agent/plan_models.py` | Discriminated Plan v2 models and stable common unit fields |
| `src/agent/plan_validation.py` | Registry-aware static Plan validation and structured issues |
| `src/agent/nodes/planner.py` | Strict JSON round-trip into Plan v2; no field dropping |
| `src/agent/prompts/planner_system.txt` | Qualified-column and operation-specific output contract |
| `src/agent/nodes/business_track.py` | Multi-Snapshot context and qualified `inspect_column` usage |
| `src/agent/tools.py` | Resolve `snapshot.column` through the registry |
| `src/api/routes/workspace.py` | Validate save/edit/delete and stale propagation |
| `src/api/schemas.py` | Operation-specific request/response schemas |
| `tests/test_plan_models.py`, `tests/test_plan_validation.py` | Model and rule coverage |
| `tests/test_planner.py`, `tests/test_business_track.py`, `tests/api/test_workspace.py` | Agent/API migration coverage |

## Plan v2 Field Matrix

All units share `unit_id`, `operation`, `execution_mode`, `purpose`,
`cautious`, and `depends_on`. Integer IDs are positive, unique, and never
renumbered.

| Operation | Required inputs | Required outputs | Execution rule |
|---|---|---|---|
| `derive_column` | `input_snapshot`, qualified `input_columns` | `output_columns` with exactly one entry in the same Snapshot | template or restricted generated function |
| `filter` | `input_snapshot`, qualified predicate columns | one unused `output_snapshot` | template or restricted generated function; Plan owns output name |
| `join` | left/right input Snapshots, key pairs, selected output aliases | one unused `output_snapshot` | deterministic pandas executor; no generated Join code |
| `terminal` | one `input_snapshot`, qualified `input_columns` | artifacts only | existing template or subprocess path |

Use `operation` as the Pydantic union discriminator. Keep Join `select` entries
explicit: each has `from` and `as`; aliases must be unique. Keep `how` explicit,
require key pairs for every non-cross mode, and reject key pairs for `cross`.

## Execution Tasks

### 1. Implement typed models and structural validation

- Define one model per operation and a union using `Field(discriminator="operation")`.
- Use literal operation values and explicit nested models for Join keys/selects.
- Remove `related_fields` and `input_from` as sources of truth. If temporary
  parsing aliases are accepted, normalize them before a Plan is persisted and
  never return them as v2 fields.
- Preserve terminal fields needed by existing chart/statistics/model/report
  behavior.
- Reject unknown or missing operation fields with actionable Pydantic errors.

### 2. Build the registry-aware validator

Validate in deterministic topological order:

- unique unit IDs, valid dependency references, no self-dependency, and no DAG
  cycle;
- every input Snapshot exists and every qualified input Column exists in that
  Snapshot's current or explicitly inherited planned state;
- Derive `output_columns` contains exactly one new column and does not overwrite
  a raw or already-declared column;
- Derive writers targeting one Snapshot form one dependency chain; otherwise
  reject the plan before execution;
- Filter and Join output Snapshot names are valid and unused;
- Join keys resolve to the declared left/right Snapshots and select aliases are
  unique;
- Terminal units are DAG leaves and declare no data-producing output;
- dependent units refer to the output Snapshot/head produced by their upstream
  unit, not a guessed branch name.

Return structured issues with `code`, `unit_id`, `field`, and `message` so API
and frontend errors do not parse free-form strings.

### 3. Make save, edit, and delete semantics safe

- Validate a complete Plan on `PUT /workspace` and after every unit edit.
- Allocate new IDs with `max(existing_ids, default=0) + 1`.
- Delete without renumbering. Reject deletion with downstream dependents unless
  the request explicitly asks for cascade deletion and the cascade is valid.
- Mark an edited unit and all transitive dependents stale in `analysis_result`.
- Use `model_copy(update=...)` for state changes; do not mutate `plan.units` in
  place in API or CLI code.

### 4. Migrate agent context and Planner parsing

- Feed Business Track and Planner grouped qualified columns with snapshot names,
  dtypes, row counts, and alignment context.
- Update `inspect_column` to accept a qualified reference and look up the
  current Column Graph node/profile.
- Update Planner prompt examples and parser to preserve operation,
  execution mode, dependencies, inputs, outputs, templates, Join structure,
  and parameters through `Plan.model_validate`.
- Add a JSON round-trip test that catches field loss.

## Tests and Evidence

- Valid Derive -> Filter -> Join -> Terminal shape parses through the union.
- Missing Snapshot/Column, duplicate aliases, invalid dependency, reused output
  Snapshot, unordered same-Snapshot writers, and non-leaf Terminal all fail
  before the plan is stored.
- Deleting unit 2 from units 1, 2, 3 leaves IDs 1 and 3 unchanged.
- Editing unit 1 marks its complete downstream closure stale.
- Planner JSON round-trips without losing any v2 field.
- `pytest -q tests/test_plan_models.py tests/test_plan_validation.py tests/test_planner.py tests/test_business_track.py tests/api/test_workspace.py`
- `ruff check .` and `mypy src/`

## Exit Criteria

- The same validator is called by Planner output handling, API workspace save,
  and the execution entry point.
- No persisted Plan contains a v1 `unit_type`, `input_from`, or
  `related_fields` source-of-truth field.
- A valid Plan references only registry-resolvable qualified columns and
  Snapshots.
- M3 can assume its input Plan is structurally and registry-valid.

## Risks and Mitigations

- **Pydantic union complexity**: test model parsing independently before wiring
  API routes; keep registry validation outside the Pydantic model.
- **Planner hallucinated refs**: provide exact qualified context and reject
  unknown refs before save; do not silently drop or rename them.
- **Plan edit invalidates downstream state**: validate the proposed complete Plan
  first, then persist the plan/stale patch atomically.
