# M4 Plan: Derive, Filter, Join, and Warning Semantics

## Objective

Complete the supported Cycle 5 data operations. Derive and Filter use the v2
row-identity contracts, Join executes deterministically with explicit selected
outputs and aliases, and analytical risks are persisted as structured warnings
without blocking executable requests.

## Dependencies and Boundary

- Depends on M1-M3.
- Join is deterministic pandas code; it is not an LLM-generated function.
- Aggregate, Window, Pivot, Union, Measure, first-class Model, and cleaning
  workflows remain out of scope.

## Proposed Modules and Contracts

| Location | Responsibility |
|---|---|
| `src/agent/operations.py` | v2 Derive, Filter, and Join frame adapters |
| `src/agent/join_executor.py` | join modes, key matching, selected output aliases |
| `src/agent/lineage.py` | inherited, derived, and Join output Column Graph nodes |
| `src/agent/templates.py` | adapt existing templates to Plan-owned output names |
| `src/agent/dag.py` or `src/agent/executor.py` | invoke operations and commit metadata |
| `src/api/schemas.py` | warning and row-count response models |
| `tests/test_operations.py`, `tests/test_join_executor.py` | operation semantics |
| `tests/test_lineage.py`, `tests/test_execution_v2.py` | provenance and integration |

## Execution Tasks

### 1. Adapt Derive and Filter

- Resolve qualified Plan refs to local frame names before invoking the existing
  template or generated-function path.
- Derive must reject overwriting an existing local column and must produce one
  new column exactly matching the declared output.
- Filter output Snapshot names come only from the Plan. A generated function
  returns the filtered frame and optional metrics, not an arbitrary Snapshot
  that changes the graph.
- Validate hidden row ID uniqueness, row subset membership, unchanged column
  set for Filter, and row conservation for Derive.
- Create new Column Graph nodes for output columns. Filter nodes inherit each
  input column through a direct parent and preserve root origins. Derive nodes
  record direct parents plus the transitive root origin refs.

### 2. Implement deterministic Join execution

- Resolve left and right current Checkpoints explicitly.
- Support `inner`, `left`, `right`, `outer`, `cross`, `semi`, and `anti`.
- Require key pairs for every non-cross mode. Cross has no key pairs.
- Apply selected outputs in declared order. Materialize each alias once in the
  output Snapshot and reject duplicates before execution.
- Generate a fresh unique `__di_row_id` for every Join output row. Do not reuse
  a left or right ID because one input row can produce multiple output rows.
- Define semi/anti as left-row selection operations; their output selection must
  not pretend that right-side values exist.
- Keep source column names local to each input frame and use aliases to resolve
  output collisions.

### 3. Record Column Graph provenance

- For every selected Join output, record the direct parent Column Graph node
  from the declared side.
- For derived and inherited nodes, preserve both direct parent IDs and all root
  `origin_columns`.
- A rerun creates new output node IDs for the new checkpoint while old nodes
  remain addressable.
- Ensure every column advertised by a current Snapshot resolves to exactly one
  persisted node.

### 4. Compute structured Join warnings

Add a stable warning object with at least `code`, `severity`, `message`, and
machine-readable details. Emit the following when observed:

- `JOIN_MANY_TO_MANY`: duplicate keys on both inputs;
- `JOIN_ROW_EXPANSION`: output row count expands beyond the relevant input
  baseline;
- `JOIN_KEY_DTYPE_MISMATCH`: paired key dtypes differ;
- `JOIN_UNMATCHED_KEYS`: keys on one side have no counterpart.

Warnings are stored in `unit_results` and included in API results and report
context. A warning does not block execution if pandas can complete the declared
operation. A pandas exception, missing input, or contract failure remains a
mechanical error.

### 5. Validate all mode-specific edge cases

- Empty inputs and empty filter results still create valid indexed Snapshots.
- Null join keys follow pandas semantics and are reported consistently.
- Duplicate aliases, missing key columns, incompatible output selection, and
  unknown join modes fail before checkpoint registration.
- Test row counts, selected columns, aliases, row IDs, and warning details for
  every mode rather than only checking that a DataFrame was returned.

## Tests and Evidence

- Derive preserves row IDs and adds exactly one column.
- Filter produces an indexed subset with inherited column lineage.
- Join tests cover all seven modes, selected output order, aliases, duplicate
  keys, unmatched keys, dtype mismatch, empty sides, and row expansion.
- A many-to-many Join completes with warnings and a committed checkpoint.
- A complete `derive -> filter -> derive -> join -> terminal` DAG produces
  artifacts and a report-ready result payload.
- Restart and rerun tests confirm new Join checkpoints/nodes coexist with old
  history.
- `pytest -q tests/test_operations.py tests/test_join_executor.py tests/test_lineage.py tests/test_execution_v2.py`
- `ruff check .` and `mypy src/`

## Exit Criteria

- Join never receives arbitrary generated code.
- Every supported operation has an explicit input/output contract and lineage
  result.
- Warning-bearing joins are visible as successful results with durable warning
  metadata.
- The backend can execute the complete PRD acceptance DAG without UI support.

## Risks and Mitigations

- **Join semantics drift**: document and parameterize each mode; compare test
  results against pandas reference frames.
- **Row ID multiplication**: always generate output IDs after materialization;
  test duplicate-key expansion explicitly.
- **Warning noise**: keep warning codes and details stable, and avoid inventing
  a business-level judgment about whether a join is meaningful.
