# Cycle 4 — DAG-Native Executor & Structured Unit Contract

## Problem

DataInsight's current DAG execution layer (`dag.py`) passes data between units via CSV
concatenation (`merge_upstream_outputs`). Each unit is a standalone Python script running in
a subprocess. This mechanism has structural flaws:

- **Unreliable data handoff**: Upstream units dump results to `output.csv`; downstream units
  read them back with blind `pd.concat(axis=1)`. If two upstream units produce different row
  counts, the merge breaks silently or noisily — there is no contract enforcing alignment.
- **Tension between unit isolation and code continuity**: To enable independent rerun, each
  unit must be a separate process. But analysis logic is inherently sequential (compute column
  A, then use A to compute column B, then plot both). Splitting into independent scripts forces
  each one to repeat boilerplate (read CSV, import libraries, parse args, write CSV), and the
  LLM loses context across unit boundaries.
- **The star-to-DAG migration exposes the old data-passing model**: Under the star-shaped
  workspace (Cycle 3), units had few or no inter-dependencies — CSV concat was good enough.
  Under a DAG with branching filters, layered transforms, and snapshot forks, the implicit
  CSV-passing contract is no longer sufficient.

## Evidence

- Architectural analysis: the DAG engine (`topological_levels`, `merge_upstream_outputs`,
  `execute_dag`) was added late in Cycle 3 as a quick enablement layer. Its CSV-passing
  model was designed for simple linear chains, not for branching snapshots or selective rerun.
- No production incidents yet (DAG mode hasn't seen heavy real-world use), but the following
  failures are structurally guaranteed:
  - `merge_upstream_outputs` uses `pd.concat(axis=1)` assuming all upstream CSVs have
    identical row counts. A FilterUnit producing 200 rows and a TransformUnit on the main
    table producing 1000 rows cannot be merged.
  - There is no API endpoint for single-unit rerun — the only option is re-running the
    entire `analysis_node`.
- **Mark**: Assumption — requires validation via the MVP integration test on real data.

## Users

- **Primary**: YANdz, as the developer and sole user of DataInsight. Needs the executor
  to reliably compose discrete analysis units into a coherent DAG, with per-unit rerun
  and deterministic data flow.
- **Not for**: External users. Multi-tenancy, permissions, and collaboration are out of scope.

## Hypothesis

We believe **three structured unit types (Transform / Filter / Terminal) + a unified
data contract (row-semantic conservation) + Parquet-based checkpoint/snapshot management**
will solve the problem of unreliable data continuity between LLM-generated analysis units
executing in DAG topological order.

We'll know we're right when **a 4-node DAG (Filter → Transform → Transform → Terminal)
executes successfully on real CSV data, and re-running any single intermediate node
produces downstream results identical to a fresh full-DAG run.**

## Success Metrics

| Metric | Target | How measured |
|---|---|---|
| DAG end-to-end execution | 4-node DAG passes on real CSV | Integration test |
| Single-unit rerun consistency | Rerun any node → downstream output unchanged | Automated test: rerun → diff downstream artifacts |
| Contract uniformity | Template-mode and LLM-mode units return the same shape | Type check + test assertion |
| Regression safety | All 201 existing tests still pass | `pytest -v` |

## Scope

### MVP

**A 4-node DAG on real CSV data, exercising the full contract:**

```
Real CSV data (e.g. sales with date, region, revenue, cost, volume columns)

Unit 1 [Filter, template]:     Filter rows by date range → snapshot "recent"
Unit 2 [Transform, template]:  revenue + cost → new_col "margin", on snapshot "recent"
Unit 3 [Transform, template]:  linear regression volume ~ margin → column "predicted_volume",
                                on snapshot "recent"
Unit 4 [Terminal, template]:   Scatter plot (volume × margin × predicted_volume) → chart.png,
                                from snapshot "recent"

Any unit (1–4) can be re-run independently. Downstream results remain consistent.
```

**Deliverables:**
1. Refactored `PlanUnit` model (3 unit types + execution mode)
2. Refactored `dag.py`: remove `merge_upstream_outputs`, add Parquet checkpoint + snapshot management
3. New `templates.py`: at least one template per unit type (filter_by_date, column_arithmetic,
   linear_regression, scatter_plot)
4. Refactored LLM prompts so LLM-generated code follows the same return contract as templates
5. API sync: `POST /execution/units/{id}/rerun` + stale downstream marking
6. Integration test: 4-node MVP DAG on real data, with per-node rerun assertions

### Out of scope

- **Frontend DAG canvas / edge editor** — the visual DAG interaction is essential long-term
  but is a distraction from getting the executor contract right. The API layer stays in sync;
  `depends_on` can be set via the existing `PUT /workspace/units/{id}` endpoint.
- **Large template library** — MVP needs only 4–5 templates to prove the architecture.
  Additional templates are incremental additions post-MVP.
- **Cross-granularity joins** (`groupby.agg` producing a new table, then joining back) —
  violates row-semantic conservation. Different analytical granularity → new session.
- **Database-backed session persistence** — MVP keeps filesystem Parquet + in-memory
  `SessionStore`. SQLite migration is a follow-up.
- **Multi-table upload & wide-table integration** — `file_path: str` remains single-table
  for MVP. Multi-table joins belong in the data ingestion layer, not inside the executor.

## Design Constraints

### Three Unit Types

| Type | Contract | Data flow | Template | LLM |
|------|----------|-----------|----------|-----|
| **TransformUnit** | `df → df + [new_col_1, ...]`; row count invariant, row identity invariant | New columns appended to current working surface | KMeans, LinearRegression, StandardScaler, column_arithmetic | Feature engineering, custom calculations |
| **FilterUnit** | `df → named_snapshot.parquet`; column set invariant, row identity invariant | Produces an independent Parquet snapshot; downstream units reference it via `input_from` | filter_by_date, filter_by_value, drop_null | Complex conditional expressions |
| **TerminalUnit** | `df → artifacts[]`; no data columns or snapshots produced | Produces charts/reports/model files; always a DAG leaf node | scatter_plot, line_chart, bar_chart, histogram | Custom multi-panel visuals |

### Row-Semantic Conservation (the hard rule)

> A row must always represent the same original sample. Columns can be added or removed.
> Rows can be filtered out. But a row's *identity* must never change.

This means:
- `df['cluster'] = KMeans.fit_predict(X)` — **pass**. Row i is still sample i.
- `df = df[df['year'] == 2024]` — **pass**. Remaining rows still represent their original samples.
- `df.groupby('region').agg(...)` — **fail**. New rows represent "regions", not original samples.
- `df.corr()` — **fail**. New rows represent "variables", not original samples.

This is the single rule that determines whether an operation can be a TransformUnit or must
be a TerminalUnit. TerminalUnit is the escape hatch for anything that doesn't conserve row
semantics.

### Snapshot = Wide Table

A FilterUnit produces a snapshot. That snapshot **is** a wide table — it has the same column
structure as the original, just fewer rows. Downstream units treat it exactly like they would
treat the main wide table:

```
Main wide table (1000 × 5)
    │
    ├── Unit 1 [Filter, template]: date filter
    │       │
    │       ▼ snapshot "recent" (200 × 5)   ← this IS a wide table, just smaller
    │       │
    │       ├── Unit 2 [Transform]: margin = revenue + cost
    │       │       │
    │       │       ▼ snapshot "recent" checkpoint L1 (200 × 6)
    │       │       │
    │       │       ├── Unit 3 [Transform]: linear regression → predicted_volume
    │       │       │       │
    │       │       │       ▼ snapshot "recent" checkpoint L2 (200 × 7)
    │       │       │       │
    │       │       │       └── Unit 4 [Terminal]: scatter plot
    │       │       │
    │       │       └── (other transforms on this snapshot...)
    │       │
    │       └── (other transforms on this snapshot...)
    │
    ├── Unit 5 [Transform]: on main table, add rolling_mean_7d
    │       │
    │       ▼ main table checkpoint L1 (1000 × 6)
    │
    └── Unit 6 [Terminal]: histogram on full dataset
```

**Hard constraint**: A unit with `input_from="snapshot_X"` can ONLY read from that snapshot.
A unit with `input_from=None` reads from the main wide table. Mixing data sources within a
single unit is forbidden — the row counts won't align, and there is no implicit join.

### Data Passing: Not Code, Parquet

Units do not read each other's source code. Data flows through Parquet files:

- **Main wide table checkpoints**: `wide_l{level}.parquet` — one per transform level
- **Snapshot checkpoints**: `snapshot_{name}_l{level}.parquet` — one per transform level
  within that snapshot branch
- **Downstream reads**: `input_from=None` → main wide table; `input_from="recent"` → snapshot

### Rerun Logic

```
Rerun Unit N:
  1. Identify the Parquet file that was Unit N's input
     (main table checkpoint at the level before N, or snapshot checkpoint)
  2. Load df from that Parquet
  3. Execute ONLY Unit N
  4. Merge output:
     - Transform: append new columns to the df, save new checkpoint
     - Filter: re-save snapshot Parquet
     - Terminal: replace artifact files
  5. Mark all downstream units (those that depend on N, directly or transitively) as stale
  6. User chooses: rerun only N (leaving downstream stale), or cascade-rerun all stale units
```

### Snapshot Storage Layout

```
data/sessions/{session_id}/
├── wide_l0.parquet              # Original wide table
├── wide_l1.parquet              # After Level 1 transforms on main table
├── wide_l2.parquet              # After Level 2 transforms on main table
├── snapshots/
│   ├── recent_l0.parquet        # FilterUnit output (snapshot "recent", level 0)
│   ├── recent_l1.parquet        # After Level 1 transforms on snapshot "recent"
│   └── recent_l2.parquet        # After Level 2 transforms on snapshot "recent"
└── artifacts/
    ├── unit_4_scatter.png
    └── unit_6_histogram.png
```

Total Parquet files per session = (main table levels) + (snapshots × levels per snapshot).
For a typical session: 1–3 snapshots × 2–4 levels = 2–12 Parquet files. All cleaned up
when the session is deleted.

### PlanUnit Model

```python
class UnitType(str, Enum):
    TRANSFORM = "transform"
    FILTER = "filter"
    TERMINAL = "terminal"

class ExecutionMode(str, Enum):
    TEMPLATE = "template"
    LLM = "llm"

class PlanUnit(BaseModel):
    unit_id: int
    unit_type: UnitType
    execution_mode: ExecutionMode

    # DAG topology
    depends_on: list[int] = []
    input_from: str | None = None          # None = main wide table; "recent" = snapshot name

    # Column contract
    input_columns: list[str] = []           # Columns this unit reads
    output_columns: list[str] = []          # Transform: new column names; Filter/Terminal: []

    # Template mode
    template_name: str | None = None
    template_params: dict[str, object] | None = None

    # LLM mode
    purpose: str = ""
    model_hint: str | None = None
    cautious: str = ""
    related_fields: list[str] = []
```

### Template Function Signature (unified contract)

All template functions follow the same signature per unit type. LLM-generated code MUST
produce the same return shape:

```python
# ── TransformUnit templates ──
def transform_linear_regression(
    df: pd.DataFrame,
    input_columns: list[str],   # [X_col, Y_col]
    params: dict,               # {}
) -> dict:
    """Returns {"columns": {"predicted": pd.Series}, "artifacts": []}"""
    ...

def transform_column_arithmetic(
    df: pd.DataFrame,
    input_columns: list[str],   # [col_a, col_b]
    params: dict,               # {"operator": "+", "new_column": "margin"}
) -> dict:
    """Returns {"columns": {"margin": pd.Series}, "artifacts": []}"""
    ...

# ── FilterUnit templates ──
def filter_by_date(
    df: pd.DataFrame,
    input_columns: list[str],   # ["date"]
    params: dict,               # {"start": "2023-01-01", "end": "2024-12-31"}
) -> dict:
    """Returns {"filtered_df": pd.DataFrame, "snapshot_name": str, "artifacts": []}"""
    ...

# ── TerminalUnit templates ──
def terminal_scatter_plot(
    df: pd.DataFrame,
    input_columns: list[str],   # [x_col, y_col, (optional)pred_col]
    params: dict,               # {"title": "...", "x_label": "...", "y_label": "..."}
) -> dict:
    """Returns {"columns": {}, "artifacts": ["scatter.png"]}"""
    ...
```

### LLM Mode Contract

LLM-generated code for each unit type must produce the **exact same return dict shape** as
the corresponding template. The LLM prompt specifies the unit type and the required return
format. The executor validates the return shape before merging.

For TransformUnit (LLM mode):
```
You are writing a column transform function body.
Signature: def transform(df, input_columns, params) -> dict
Return: {"columns": {new_col_name: pd.Series, ...}, "artifacts": []}
Rules:
  - Read ONLY from input_columns
  - Produce ONLY the columns declared in output_columns
  - Row count MUST NOT change (use .transform(), not .agg())
  - Do NOT modify existing columns
  - Do NOT read or write files
```

For FilterUnit (LLM mode):
```
You are writing a row filter function body.
Signature: def filter(df, input_columns, params) -> dict
Return: {"filtered_df": pd.DataFrame, "snapshot_name": str, "artifacts": []}
Rules:
  - Return a subset of rows from df
  - Column set MUST NOT change
  - Each row must still represent its original sample
```

For TerminalUnit (LLM mode):
```
You are writing a visualization/report function body.
Signature: def terminal(df, input_columns, params) -> dict
Return: {"columns": {}, "artifacts": ["chart1.png", ...]}
Rules:
  - Read from input_columns
  - Produce artifact files (charts, reports, model files)
  - Do NOT produce data columns or snapshots
```

## Delivery Milestones

| # | Milestone | Outcome | Status | Plan |
|---|---|---|---|---|
| 1 | PlanUnit model refactor + DAG engine overhaul | New PlanUnit with 3 types + execution_mode; `execute_dag` uses Parquet checkpoints; `merge_upstream_outputs` removed | complete | `../plans/cycle-4-dag-executor.plan.md` |
| 2 | Template system + MVP templates | 4–5 templates across 3 unit types; `dispatch()` routes by execution_mode; template return contract enforced | complete | `../plans/cycle-4-dag-executor-m2.plan.md` |
| 3 | LLM prompt refactor | LLM-generated code follows the same return contract as templates; per-unit-type prompt templates | complete | `../plans/cycle-4-dag-executor-m3.plan.md` |
| 4 | Single-unit rerun API | `POST /execution/units/{id}/rerun` + stale downstream marking + cascade-rerun option | complete | `../plans/cycle-4-dag-executor-m4.plan.md` |
| 5 | MVP integration test | 4-node DAG (Filter → Transform → Transform → Terminal) on real CSV; per-node rerun assertions | complete | `../plans/cycle-4-dag-executor-m5.plan.md` |
| 6 | In-process function path + durable sessions | Transform/Filter LLM units share the template contract; completed sessions survive restarts | complete | `../plans/cycle-4-m6-inprocess-llm.plan.md` |

## Open Questions

- [x] `input_from` remains explicit and is set by the Planner/user. Dependencies define
  execution order; they do not implicitly select a data branch.
- [x] Transform/Filter LLM units use a restricted in-process generated-function path;
  Terminal LLM units retain subprocess execution. This is an accepted trusted-local
  boundary, not an OS sandbox. See D59.
- [x] Rerun conservatively marks all transitive dependents stale. Column-diff
  optimization is deferred until real usage demonstrates a need.

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Snapshot checkpoint proliferation | Medium | Too many Parquet files, complex rerun logic | MVP limit: ≤3 snapshots per session; explicit naming; cleanup on session delete |
| LLM prompt refactor degrades code quality | Low | LLM-generated code doesn't follow new contract | Template mode covers high-frequency operations; LLM only for custom logic |
| Parquet I/O bottleneck on large datasets | Low | 120s timeout exceeded | 100K-row Parquet reads/writes in <2s; large-data optimization deferred |
| Existing test breakage from PlanUnit model change | Medium | Many tests construct PlanUnit instances | Add new fields as optional first; run full test suite after each milestone |

---
*Status: COMPLETE — Cycle 4 closed with M1-M6 delivered.*
