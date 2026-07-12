from __future__ import annotations

import os

import pandas as pd
import pytest

from src.agent.dag import (
    DagCycleError,
    _checkpoint_path,
    execute_dag,
    load_checkpoint,
    resolve_rerun_input,
    save_checkpoint,
    topological_levels,
    transitive_dependents,
    validate_columns,
)
from src.agent.state import AgentState, PlanUnit

# ── helpers ────────────────────────────────────────────────────────────────


def _u(
    uid: int,
    deps: list[int] | None = None,
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    related: list[str] | None = None,
    *,
    unit_type: str = "transform",
    exec_mode: str = "llm",
    input_from: str | None = None,
    model_hint: str | None = None,
    template_name: str | None = None,
    tpl_params: dict | None = None,
) -> PlanUnit:
    return PlanUnit(
        unit_id=uid,
        unit_type=unit_type,  # type: ignore[arg-type]
        execution_mode=exec_mode,  # type: ignore[arg-type]
        purpose=f"Unit {uid}",
        model_hint=model_hint or "auto",
        cautious="",
        depends_on=deps or [],
        input_from=input_from,
        input_columns=inputs or [],
        output_columns=outputs or [],
        related_fields=related or [],
        template_name=template_name,
        template_params=tpl_params,
    )


# ── topological_levels ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_topo_empty() -> None:
    assert topological_levels([]) == []


@pytest.mark.unit
def test_topo_single_unit() -> None:
    units = [_u(1)]
    levels = topological_levels(units)
    assert levels == [[units[0]]]


@pytest.mark.unit
def test_topo_independent() -> None:
    units = [_u(1), _u(2), _u(3)]
    levels = topological_levels(units)
    assert len(levels) == 1
    assert len(levels[0]) == 3


@pytest.mark.unit
def test_topo_linear_chain() -> None:
    units = [
        _u(1),
        _u(2, deps=[1]),
        _u(3, deps=[2]),
    ]
    levels = topological_levels(units)
    assert len(levels) == 3
    assert [u.unit_id for u in levels[0]] == [1]
    assert [u.unit_id for u in levels[1]] == [2]
    assert [u.unit_id for u in levels[2]] == [3]


@pytest.mark.unit
def test_topo_fan_out() -> None:
    # 1 → 2, 1 → 3
    units = [
        _u(1),
        _u(2, deps=[1]),
        _u(3, deps=[1]),
    ]
    levels = topological_levels(units)
    assert len(levels) == 2
    assert [u.unit_id for u in levels[0]] == [1]
    assert {u.unit_id for u in levels[1]} == {2, 3}


@pytest.mark.unit
def test_topo_fan_in() -> None:
    # 1 → 3, 2 → 3
    units = [
        _u(1),
        _u(2),
        _u(3, deps=[1, 2]),
    ]
    levels = topological_levels(units)
    assert len(levels) == 2
    assert {u.unit_id for u in levels[0]} == {1, 2}
    assert [u.unit_id for u in levels[1]] == [3]


@pytest.mark.unit
def test_topo_diamond() -> None:
    # 1 → 2, 1 → 3, 2 → 4, 3 → 4
    units = [
        _u(1),
        _u(2, deps=[1]),
        _u(3, deps=[1]),
        _u(4, deps=[2, 3]),
    ]
    levels = topological_levels(units)
    assert len(levels) == 3
    assert [u.unit_id for u in levels[0]] == [1]
    assert {u.unit_id for u in levels[1]} == {2, 3}
    assert [u.unit_id for u in levels[2]] == [4]


@pytest.mark.unit
def test_topo_complex() -> None:
    # 1 → 2, 1 → 3, 2 → 4, 3 → 4, 5 (independent)
    units = [
        _u(1),
        _u(2, deps=[1]),
        _u(3, deps=[1]),
        _u(4, deps=[2, 3]),
        _u(5),
    ]
    levels = topological_levels(units)
    assert len(levels) == 3
    assert {u.unit_id for u in levels[0]} == {1, 5}
    assert {u.unit_id for u in levels[1]} == {2, 3}
    assert [u.unit_id for u in levels[2]] == [4]


# ── cycle detection ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_cycle_direct() -> None:
    units = [
        _u(1, deps=[2]),
        _u(2, deps=[1]),
    ]
    with pytest.raises(DagCycleError) as exc:
        topological_levels(units)
    assert 1 in exc.value.unit_ids
    assert 2 in exc.value.unit_ids


@pytest.mark.unit
def test_cycle_self_loop() -> None:
    units = [_u(1, deps=[1])]
    with pytest.raises(DagCycleError) as exc:
        topological_levels(units)
    assert 1 in exc.value.unit_ids


@pytest.mark.unit
def test_cycle_three_node() -> None:
    units = [
        _u(1, deps=[3]),
        _u(2, deps=[1]),
        _u(3, deps=[2]),
    ]
    with pytest.raises(DagCycleError):
        topological_levels(units)


@pytest.mark.unit
def test_cycle_missing_dependency() -> None:
    units = [_u(1, deps=[99])]
    with pytest.raises(DagCycleError) as exc:
        topological_levels(units)
    assert 1 in exc.value.unit_ids
    assert 99 in exc.value.unit_ids


# ── column validation ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_validate_exact_match() -> None:
    missing, found = validate_columns(
        ["A", "B"], {"A", "B", "C"},
    )
    assert missing == []
    assert found == ["A", "B"]


@pytest.mark.unit
def test_validate_all_missing() -> None:
    missing, found = validate_columns(["X"], {"A", "B"})
    assert missing == ["X"]
    assert found == []


@pytest.mark.unit
def test_validate_partial() -> None:
    missing, found = validate_columns(["A", "X"], {"A", "B"})
    assert missing == ["X"]
    assert found == ["A"]


@pytest.mark.unit
def test_validate_empty_required() -> None:
    missing, found = validate_columns([], {"A"})
    assert missing == []
    assert found == []


@pytest.mark.unit
def test_validate_case_sensitive() -> None:
    missing, found = validate_columns(["a"], {"A"})
    assert missing == ["a"]
    assert found == []


# ── checkpoint helpers ─────────────────────────────────────────────────────


@pytest.mark.unit
def test_checkpoint_path_wide() -> None:
    path = _checkpoint_path("/tmp/session", "wide", 1)
    assert path == os.path.join("/tmp/session", "checkpoints", "wide_l1.parquet")


@pytest.mark.unit
def test_checkpoint_path_snapshot() -> None:
    path = _checkpoint_path("/tmp/session", "recent", 2)
    expected = os.path.join("/tmp/session", "checkpoints", "snapshots", "recent_l2.parquet")
    assert path == expected


@pytest.mark.unit
def test_save_and_load_checkpoint(tmp_path) -> None:
    df = pd.DataFrame({"A": [1, 2], "B": [3.0, 4.0]})
    cp_path = os.path.join(str(tmp_path), "test.parquet")
    save_checkpoint(df, cp_path)
    assert os.path.exists(cp_path)

    loaded = load_checkpoint(cp_path)
    assert list(loaded.columns) == ["A", "B"]
    assert len(loaded) == 2
    assert loaded["A"].tolist() == [1, 2]


@pytest.mark.unit
def test_save_checkpoint_overwrites(tmp_path) -> None:
    df1 = pd.DataFrame({"X": [1]})
    df2 = pd.DataFrame({"X": [2]})
    cp_path = os.path.join(str(tmp_path), "test.parquet")
    save_checkpoint(df1, cp_path)
    save_checkpoint(df2, cp_path)
    loaded = load_checkpoint(cp_path)
    assert loaded["X"].tolist() == [2]


# ── execute_dag ────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_execute_dag_no_plan() -> None:
    state = AgentState(file_path="/tmp/test.csv", user_requirement="Test")
    result = execute_dag(state, "/tmp/out", {}, lambda *a, **kw: {})
    assert result["status"] == "failed"
    assert "No plan" in result["dag_error"]


@pytest.mark.unit
def test_execute_dag_cycle_detected() -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, deps=[2]), _u(2, deps=[1])],
        alignment_notes="cycle test",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
    )
    result = execute_dag(state, "/tmp/out", {}, lambda *a, **kw: {})
    assert result["status"] == "failed"
    assert "Cycle" in result["dag_error"]


@pytest.mark.unit
def test_execute_dag_single_unit_success(tmp_path) -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1)],
        alignment_notes="single",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 1
    assert result["unit_results"][0]["status"] == "success"


@pytest.mark.unit
def test_execute_dag_linear_chain(tmp_path) -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[
            _u(1, outputs=["Cluster"]),
            _u(2, deps=[1], inputs=["Cluster"], outputs=["Score"]),
            _u(3, deps=[2], inputs=["Score"]),
        ],
        alignment_notes="chain",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    call_order = []

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        call_order.append(unit.unit_id)
        output_csv = os.path.join(output_dir, "output.csv")
        if unit.unit_id == 1:
            pd.DataFrame({"Cluster": [0, 1]}).to_csv(output_csv, index=False)
        elif unit.unit_id == 2:
            pd.DataFrame({"Score": [0.5, 0.8]}).to_csv(output_csv, index=False)
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 3
    assert call_order.index(1) < call_order.index(2) < call_order.index(3)


@pytest.mark.unit
def test_execute_dag_failure_isolation(tmp_path) -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[
            _u(1),
            _u(2, deps=[1], inputs=["Cluster"]),
            _u(3),  # independent, should still succeed
        ],
        alignment_notes="isolation",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        if unit.unit_id == 1:
            return {
                "unit_id": 1,
                "status": "failed",
                "parsed_output": None,
                "charts": [],
                "insights": [],
                "statistics": {},
                "error": "Script error",
                "retry_count": 3,
                "scripts": [],
                "stdout": "",
                "output_dir": output_dir,
            }
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "partial"
    unit_results = {ur["unit_id"]: ur for ur in result["unit_results"]}
    assert unit_results[1]["status"] == "failed"
    assert unit_results[2]["status"] == "failed"
    assert "Cluster" in unit_results[2]["error"]
    assert unit_results[3]["status"] == "success"


@pytest.mark.unit
def test_execute_dag_column_validation_passes(tmp_path) -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, inputs=["A", "B"])],
        alignment_notes="col check",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B", "C"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"
    assert result["unit_results"][0]["status"] == "success"


@pytest.mark.unit
def test_execute_dag_falls_back_to_related_fields(tmp_path) -> None:
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, related=["A", "X"])],
        alignment_notes="fallback",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"


@pytest.mark.unit
def test_execute_dag_executor_exception(tmp_path) -> None:
    """execute_unit_fn raises RuntimeError → caught by executor except handler."""
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1), _u(2)],
        alignment_notes="executor exception",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        if unit.unit_id == 1:
            raise RuntimeError("Simulated executor crash")
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "partial"
    unit_results = {ur["unit_id"]: ur for ur in result["unit_results"]}
    assert unit_results[1]["status"] == "failed"
    assert "Simulated executor crash" in unit_results[1]["error"]
    assert unit_results[2]["status"] == "success"


# ── Parquet checkpoint integration ─────────────────────────────────────────


@pytest.mark.unit
def test_execute_dag_transform_saves_checkpoint(tmp_path) -> None:
    """Transform unit → output.csv saved → Parquet checkpoint created."""
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, outputs=["Margin"])],
        alignment_notes="checkpoint",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["Revenue", "Cost"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        output_csv = os.path.join(output_dir, "output.csv")
        pd.DataFrame({"Revenue": [100, 200], "Cost": [60, 120], "Margin": [40, 80]}).to_csv(
            output_csv, index=False
        )
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"

    cp = os.path.join(str(tmp_path), "checkpoints", "wide_l1.parquet")
    assert os.path.exists(cp)
    loaded = load_checkpoint(cp)
    assert "Margin" in loaded.columns


@pytest.mark.unit
def test_execute_dag_filter_saves_snapshot(tmp_path) -> None:
    """Filter unit → snapshot checkpoint saved."""
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, unit_type="filter", outputs=[])],
        alignment_notes="filter",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        output_csv = os.path.join(output_dir, "output.csv")
        pd.DataFrame({"A": [1], "B": [3]}).to_csv(output_csv, index=False)
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
            "snapshot_name": "recent",
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"

    cp = os.path.join(str(tmp_path), "checkpoints", "snapshots", "recent_l0.parquet")
    assert os.path.exists(cp)
    loaded = load_checkpoint(cp)
    assert len(loaded) == 1


@pytest.mark.unit
def test_execute_dag_terminal_skips_checkpoint(tmp_path) -> None:
    """Terminal unit → no checkpoint saved."""
    from src.agent.state import Plan

    plan = Plan(
        units=[_u(1, unit_type="terminal", outputs=[])],
        alignment_notes="terminal",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {"charts": ["scatter.png"]},
            "charts": ["scatter.png"],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"

    checkpoints_dir = os.path.join(str(tmp_path), "checkpoints")
    wide_files = [
        f for f in os.listdir(checkpoints_dir) if f.startswith("wide_")
    ] if os.path.isdir(checkpoints_dir) else []
    assert len(wide_files) == 0


@pytest.mark.unit
def test_execute_dag_input_from_snapshot(tmp_path) -> None:
    """Unit with input_from reads from named snapshot checkpoint."""
    from src.agent.state import Plan

    # Unit 1: Filter → creates snapshot "recent"
    # Unit 2: Transform on snapshot "recent"
    plan = Plan(
        units=[
            _u(1, unit_type="filter"),
            _u(2, unit_type="transform", deps=[1], input_from="recent"),
        ],
        alignment_notes="snapshot chain",
    )
    state = AgentState(
        file_path="/tmp/test.csv",
        user_requirement="Test",
        plan=plan,
        unified_columns=["A", "B"],
    )

    # Pre-create the snapshot checkpoint so unit 2 can read it
    snap_dir = os.path.join(str(tmp_path), "checkpoints", "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    pd.DataFrame({"A": [1, 2], "B": [3, 4]}).to_parquet(
        os.path.join(snap_dir, "recent_l0.parquet")
    )

    inputs_received = {}

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        inputs_received[unit.unit_id] = input_path
        output_csv = os.path.join(output_dir, "output.csv")
        pd.DataFrame({"A": [1, 2], "B": [3, 4]}).to_csv(output_csv, index=False)
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
            "snapshot_name": "recent",
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"
    # Unit 2 should receive the snapshot parquet path
    assert "snapshots" in inputs_received[2]
    assert "recent_l0.parquet" in inputs_received[2]


# ── template-mode DAG integration ────────────────────────────────────────────


@pytest.mark.unit
def test_execute_dag_template_chain(tmp_path) -> None:
    """Two template-mode units through execute_dag: transform + terminal."""
    from src.agent.state import Plan
    from src.agent.templates import dispatch as _dispatch

    # Write original data to tmp_path
    data_path = os.path.join(str(tmp_path), "data.csv")
    pd.DataFrame({
        "revenue": [100, 200, 300],
        "cost": [60, 120, 180],
        "volume": [10, 20, 30],
    }).to_csv(data_path, index=False)

    plan = Plan(
        units=[
            _u(
                1, unit_type="transform", exec_mode="template",
                template_name="column_arithmetic",
                inputs=["revenue", "cost"], outputs=["margin"],
                tpl_params={"operator": "+", "new_column": "margin"},
            ),
            _u(
                2, unit_type="terminal", exec_mode="template",
                template_name="scatter_plot",
                inputs=["revenue", "margin"], deps=[1],
            ),
        ],
        alignment_notes="template chain",
    )
    state = AgentState(
        file_path=data_path,
        user_requirement="Test",
        plan=plan,
        unified_columns=["revenue", "cost", "volume"],
    )

    def _mock_execute(unit, input_path, output_dir, retry_state=None):
        """Thin wrapper: load data, call real dispatch for template units."""
        if unit.execution_mode == "template":
            if input_path.endswith(".parquet"):
                df = pd.read_parquet(input_path)
            else:
                df = pd.read_csv(input_path)
            result = _dispatch(unit, df, output_dir)
            if result is not None:
                return result
        # LLM-mode: mock success
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "parsed_output": {},
            "charts": [],
            "insights": [],
            "statistics": {},
            "error": None,
            "retry_count": 0,
            "scripts": [],
            "stdout": "",
            "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _mock_execute)
    assert result["status"] == "complete"
    assert len(result["unit_results"]) == 2
    assert all(r["status"] == "success" for r in result["unit_results"])

    # Check transform checkpoint
    cp = os.path.join(str(tmp_path), "checkpoints", "wide_l1.parquet")
    assert os.path.exists(cp)
    loaded = pd.read_parquet(cp)
    assert "margin" in loaded.columns

    # Check terminal artifact
    scatter_png = os.path.join(str(tmp_path), "unit_2", "scatter.png")
    assert os.path.exists(scatter_png), f"Expected {scatter_png} to exist"


# ── transitive_dependents ────────────────────────────────────────────────────


@pytest.mark.unit
def test_transitive_dependents_direct() -> None:
    units = [_u(1), _u(2, deps=[1]), _u(3)]
    result = transitive_dependents(1, units)
    assert result == [2]


@pytest.mark.unit
def test_transitive_dependents_chain() -> None:
    units = [_u(1), _u(2, deps=[1]), _u(3, deps=[2])]
    result = transitive_dependents(1, units)
    assert result == [2, 3]


@pytest.mark.unit
def test_transitive_dependents_diamond() -> None:
    units = [_u(1), _u(2, deps=[1]), _u(3, deps=[1]), _u(4, deps=[2, 3])]
    result = transitive_dependents(1, units)
    assert result == [2, 3, 4]


@pytest.mark.unit
def test_transitive_dependents_none() -> None:
    units = [_u(1), _u(2), _u(3)]
    result = transitive_dependents(3, units)
    assert result == []


@pytest.mark.unit
def test_transitive_dependents_mid_chain() -> None:
    """Dependents of a middle node in a chain."""
    units = [_u(1), _u(2, deps=[1]), _u(3, deps=[2]), _u(4, deps=[3])]
    result = transitive_dependents(2, units)
    assert result == [3, 4]


# ── resolve_rerun_input ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_resolve_rerun_input_wide(tmp_path) -> None:
    checkpoints_dir = os.path.join(str(tmp_path), "checkpoints")
    os.makedirs(checkpoints_dir, exist_ok=True)
    pd.DataFrame({"A": [1]}).to_parquet(
        os.path.join(checkpoints_dir, "wide_l1.parquet")
    )
    pd.DataFrame({"A": [2]}).to_parquet(
        os.path.join(checkpoints_dir, "wide_l2.parquet")
    )

    unit = _u(1)
    path = resolve_rerun_input(unit, str(tmp_path))
    assert path is not None
    assert "wide_l2.parquet" in path


@pytest.mark.unit
def test_resolve_rerun_input_snapshot(tmp_path) -> None:
    snap_dir = os.path.join(str(tmp_path), "checkpoints", "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    pd.DataFrame({"A": [1]}).to_parquet(
        os.path.join(snap_dir, "recent_l0.parquet")
    )

    unit = _u(1, input_from="recent")
    path = resolve_rerun_input(unit, str(tmp_path))
    assert path is not None
    assert "recent_l0.parquet" in path


@pytest.mark.unit
def test_resolve_rerun_input_none(tmp_path) -> None:
    """No checkpoint → returns None (caller uses original data)."""
    unit = _u(1)
    path = resolve_rerun_input(unit, str(tmp_path))
    assert path is None


# ── M5: MVP 4-node template DAG integration test ─────────────────────────────


@pytest.mark.unit
def test_mvp_dag_4_node_template_chain(sample_csv_100_rows: str, tmp_path) -> None:
    """Full Cycle 4 contract validation: Filter → Transform → Transform → Terminal.

    Uses only template-mode units (no LLM/sandbox) to validate the data
    contract end-to-end on 120 rows of deterministic CSV data.
    """
    from src.agent.state import Plan
    from src.agent.templates import dispatch as _dispatch

    data_path = sample_csv_100_rows

    # Load original data to know expected row count
    original = pd.read_csv(data_path)
    original_rows = len(original)
    assert original_rows >= 100, f"Fixture too small: {original_rows} rows"

    # Count rows that should pass the 2024+ filter
    original["_date_parsed"] = pd.to_datetime(original["date"], errors="coerce")
    expected_filtered = int((original["_date_parsed"] >= pd.Timestamp("2024-01-01")).sum())

    plan = Plan(
        units=[
            # Unit 1: Filter → snapshot "recent"
            _u(
                1, unit_type="filter", exec_mode="template",
                template_name="filter_by_date",
                inputs=["date"],
                tpl_params={
                    "date_column": "date",
                    "start": "2024-01-01",
                    "snapshot_name": "recent",
                },
            ),
            # Unit 2: Transform → margin = revenue + cost
            _u(
                2, unit_type="transform", exec_mode="template",
                template_name="column_arithmetic",
                inputs=["revenue", "cost"], outputs=["margin"],
                deps=[1], input_from="recent",
                tpl_params={"operator": "+", "new_column": "margin"},
            ),
            # Unit 3: Transform → linear regression predicted_volume
            _u(
                3, unit_type="transform", exec_mode="template",
                template_name="linear_regression",
                inputs=["volume", "margin"], outputs=["predicted_volume"],
                deps=[2], input_from="recent",
                tpl_params={"pred_column": "predicted_volume"},
            ),
            # Unit 4: Terminal → scatter plot
            _u(
                4, unit_type="terminal", exec_mode="template",
                template_name="scatter_plot",
                inputs=["volume", "margin"], deps=[3], input_from="recent",
            ),
        ],
        alignment_notes="MVP integration test — 4-node template DAG",
    )
    state = AgentState(
        file_path=data_path,
        user_requirement="Analyze sales trends",
        plan=plan,
        unified_columns=["date", "region", "revenue", "cost", "volume"],
    )

    # ── Execute ──────────────────────────────────────────────────────────
    def _template_executor(unit, input_path, output_dir, retry_state=None):
        if input_path.endswith(".parquet"):
            df = pd.read_parquet(input_path)
        else:
            df = pd.read_csv(input_path)
        result = _dispatch(unit, df, output_dir)
        if result is not None:
            return result
        return {
            "unit_id": unit.unit_id,
            "status": "failed",
            "error": "template dispatch returned None",
            "charts": [], "insights": [], "statistics": {},
            "parsed_output": None, "retry_count": 0,
            "scripts": [], "stdout": "", "output_dir": output_dir,
        }

    result = execute_dag(state, str(tmp_path), {}, _template_executor)

    # ── DAG-level assertions ─────────────────────────────────────────────
    assert result["status"] == "complete", f"DAG failed: {result.get('dag_error')}"
    unit_results = {ur["unit_id"]: ur for ur in result["unit_results"]}
    assert len(unit_results) == 4
    for uid in (1, 2, 3, 4):
        assert unit_results[uid]["status"] == "success", \
            f"Unit {uid} failed: {unit_results[uid].get('error')}"

    # ── Checkpoint assertions ────────────────────────────────────────────
    snap_dir = os.path.join(str(tmp_path), "checkpoints", "snapshots")

    # Filter: snapshot recent_l0.parquet
    cp_l0 = os.path.join(snap_dir, "recent_l0.parquet")
    assert os.path.exists(cp_l0), f"Missing: {cp_l0}"
    df_l0 = pd.read_parquet(cp_l0)
    assert len(df_l0) == expected_filtered, \
        f"Filter: expected {expected_filtered}, got {len(df_l0)}"
    # Column set invariant
    assert set(df_l0.columns) == {"date", "region", "revenue", "cost", "volume"}
    assert unit_results[1]["snapshot_name"] == "recent"

    # Transform 1 (arithmetic): snapshot recent_l1.parquet
    cp_l1 = os.path.join(snap_dir, "recent_l1.parquet")
    assert os.path.exists(cp_l1), f"Missing: {cp_l1}"
    df_l1 = pd.read_parquet(cp_l1)
    assert len(df_l1) == len(df_l0), \
        f"Transform row count changed: {len(df_l0)} → {len(df_l1)}"
    assert "margin" in df_l1.columns
    # Verify margin = revenue + cost (tolerance for float)
    expected_margin = df_l0["revenue"] + df_l0["cost"]
    pd.testing.assert_series_equal(
        df_l1["margin"], expected_margin, check_names=False,
    )

    # Transform 2 (regression): snapshot recent_l2.parquet
    cp_l2 = os.path.join(snap_dir, "recent_l2.parquet")
    assert os.path.exists(cp_l2), f"Missing: {cp_l2}"
    df_l2 = pd.read_parquet(cp_l2)
    assert len(df_l2) == len(df_l0), \
        f"Regression row count changed: {len(df_l0)} → {len(df_l2)}"
    assert "predicted_volume" in df_l2.columns
    assert df_l2["predicted_volume"].notna().all(), \
        "predicted_volume contains NaN (degenerate regression?)"

    # Terminal: artifact
    scatter_png = os.path.join(str(tmp_path), "unit_4", "scatter.png")
    assert os.path.exists(scatter_png), f"Missing: {scatter_png}"
    assert os.path.getsize(scatter_png) > 0, "scatter.png is empty"

    # Terminal: NO checkpoint
    wide_cp = os.path.join(str(tmp_path), "checkpoints", "wide_l1.parquet")
    assert not os.path.exists(wide_cp), "Terminal should not produce wide checkpoint"

    # ── Rerun consistency ────────────────────────────────────────────────
    # Rerun Unit 2 (arithmetic) from the same input → identical margin
    rerun2_dir = os.path.join(str(tmp_path), "unit_2_rerun")
    os.makedirs(rerun2_dir, exist_ok=True)
    unit2 = plan.units[1]  # Unit 2
    rerun2 = _dispatch(unit2, df_l0, rerun2_dir)
    assert rerun2 is not None
    assert rerun2["status"] == "success"

    # Load the rerun output.csv and compare margin
    rerun_csv = os.path.join(str(tmp_path), "unit_2_rerun", "output.csv")
    assert os.path.exists(rerun_csv)
    df_rerun2 = pd.read_csv(rerun_csv)
    pd.testing.assert_series_equal(
        df_rerun2["margin"], df_l1["margin"], check_names=False,
    )

    # Rerun Unit 3 (regression) from rerun's L1 → identical predicted_volume
    rerun3_dir = os.path.join(str(tmp_path), "unit_3_rerun")
    os.makedirs(rerun3_dir, exist_ok=True)
    unit3 = plan.units[2]  # Unit 3
    rerun3 = _dispatch(unit3, df_rerun2, rerun3_dir)
    assert rerun3 is not None
    assert rerun3["status"] == "success"
    rerun3_csv = os.path.join(str(tmp_path), "unit_3_rerun", "output.csv")
    df_rerun3 = pd.read_csv(rerun3_csv)
    import numpy as np
    assert np.allclose(
        df_rerun3["predicted_volume"].values,
        df_l2["predicted_volume"].values,
    ), "Rerun regression predictions differ from original"
