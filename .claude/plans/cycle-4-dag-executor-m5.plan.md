# Plan: MVP Integration Test — 4-Node Template DAG

**Source PRD**: `.claude/prds/cycle-4-dag-executor.prd.md`
**Selected Milestone**: 5 — MVP integration test
**Complexity**: Small

## Summary

A single integration test that exercises the full Cycle 4 data contract end-to-end: a 4-node template-mode DAG (Filter → Transform → Transform → Terminal) on a 100+ row CSV, with per-node rerun and checkpoint assertions. No LLM or sandbox — purely template dispatch, validating that the contract holds across the chain.

## User Requirements

- Template mode only — validates the data contract and pipeline without LLM variability
- CSV with at least 100 rows and necessary columns (date, region, revenue, cost, volume)
- The 4-node DAG exactly as specified in the PRD MVP (lines 70-77)

## Patterns to Mirror

| Category | Source | Pattern |
|---|---|---|
| Test structure | `tests/test_dag.py:741-819` | `_u()` factory with `exec_mode="template"`, `_dispatch()` call in mock executor, `pd.read_csv`/`pd.read_parquet` input loading |
| Plan fixture | `tests/conftest.py:184-198` | `Plan(units=[...], alignment_notes="...")` |
| CSV fixture | `tests/conftest.py:16-27` | `tempfile.mkstemp(suffix=".csv")` + `csv.writer` + `yield path; os.unlink(path)` |
| Checkpoint assertions | `tests/test_dag.py:553-595` | `os.path.exists(cp)`, `load_checkpoint(cp)`, column/row assertions on loaded Parquet |
| Template dispatch | `tests/test_dag.py:783-806` | Real `_dispatch(unit, df, output_dir)` call, thin wrapper loads data from path |

## Files to Change

| File | Action | Why |
|---|---|---|
| `tests/test_dag.py` | UPDATE | Add the 4-node integration test |
| `tests/conftest.py` | UPDATE | Add `sample_csv_100_rows` fixture |

## Tasks

### Task 1: Add `sample_csv_100_rows` fixture to conftest.py
- **Action**: Create a temp CSV with 10+ dates across 2023-2025, 4 regions (East/West/North/South), realistic revenue (800-5000), cost (60% of revenue ± noise), volume (proportional to revenue). Use `random.seed(42)` for reproducibility. At least 100 rows.
- **Mirror**: `tests/conftest.py:16-27` (`sample_csv_path`), `tests/conftest.py:33-41` (`sample_csv_with_dates`)
- **Validate**: `pytest --co -k test_mvp_dag` lists the test

### Task 2: Add the 4-node MVP integration test to test_dag.py
- **Action**: One test `test_mvp_dag_4_node_template_chain`:

  **Setup** — Build Plan:
  ```
  Unit 1 [Filter, template, filter_by_date]:
    input_columns=[], params={"date_column": "date", "start": "2024-01-01", "snapshot_name": "recent"}
  Unit 2 [Transform, template, column_arithmetic]:
    input_columns=["revenue", "cost"], input_from="recent", deps=[1],
    params={"operator": "+", "new_column": "margin"}
  Unit 3 [Transform, template, linear_regression]:
    input_columns=["volume", "margin"], input_from="recent", deps=[2],
    params={"pred_column": "predicted_volume"}
  Unit 4 [Terminal, template, scatter_plot]:
    input_columns=["volume", "margin"], input_from="recent", deps=[3]
  ```

  **Execute** — Run `execute_dag` with template dispatch via thin `_mock_execute` wrapper (same pattern as existing `test_execute_dag_template_chain`).

  **Assertions:**
  - DAG status `"complete"`, all 4 units `"success"`
  - **Filter (Unit 1)**: checkpoint `snapshots/recent_l0.parquet` exists, row count < original CSV row count, all 5 original columns present
  - **Transform (Unit 2)**: checkpoint `snapshots/recent_l1.parquet` exists, row count == filtered row count, `margin` column present, `margin == revenue + cost`
  - **Transform (Unit 3)**: checkpoint `snapshots/recent_l2.parquet` exists, row count == previous level, `predicted_volume` column present, predictions are non-NaN
  - **Terminal (Unit 4)**: artifact `unit_4/scatter.png` exists and is a valid PNG (>0 bytes)
  - **Row-semantic conservation**: rows at each transform level equal rows after filter

  **Rerun assertions:**
  - Load the snapshot `recent_l0.parquet` directly
  - Rerun Unit 2 (arithmetic) from that checkpoint, verify `margin` values identical to first run
  - Rerun Unit 3 (regression) from the recreated `recent_l1.parquet`, verify `predicted_volume` matches

- **Mirror**: `tests/test_dag.py:741-819` (`test_execute_dag_template_chain`)
- **Validate**: `pytest -v -m unit tests/test_dag.py::test_mvp_dag_4_node_template_chain`

## Validation

```bash
pytest -v -m unit tests/test_dag.py::test_mvp_dag_4_node_template_chain
pytest -v                                               # Full suite
ruff check .
```

## Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| 100-row CSV with random data produces degenerate regression (all NaN predictions) | Low | Seed fixed at 42; revenue/cost/volume values are realistic; check predictions are non-NaN |
| Template functions import side effects slow test | Low | Templates use lazy sklearn import; already tested in isolation |
| Rerun consistency check fails due to sklearn floating-point differences | Low | Compare predictions with `np.allclose()` not exact equality |

## Acceptance

- [ ] 100+ row CSV fixture exists and is deterministic (seed 42)
- [ ] 4-node DAG executes successfully via template dispatch only
- [ ] All checkpoints and artifacts created at correct paths
- [ ] Filter reduces rows, transforms preserve row count
- [ ] Rerun of intermediate unit produces consistent results
- [ ] All existing tests still pass
- [ ] `ruff check .` clean
