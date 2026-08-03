from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from src.agent.checkpoints import write_checkpoint_atomically
from src.agent.dag import execute_dag, rerun_dag
from src.agent.lineage import build_source_records, normalize_source_frame
from src.agent.nodes.analysis import _execute_unit, analysis_node
from src.agent.state import (
    AgentState,
    ColumnGraph,
    ColumnProfile,
    DataProfile,
    DeriveColumnUnit,
    Plan,
)


def _state(tmp_path) -> AgentState:
    profile = DataProfile(
        file_path="orders.csv",
        shape=(4, 3),
        columns=[
            ColumnProfile(
                name=name,
                dtype=dtype,
                null_count=0,
                null_pct=0.0,
                unique_count=4,
                unique_pct=100.0,
            )
            for name, dtype in (
                ("order_id", "int64"),
                ("amount", "int64"),
                ("region", "object"),
            )
        ],
        statistics={},
        head_sample=[],
    )
    source, snapshot, checkpoint, nodes = build_source_records(
        source_id="src_orders",
        display_name="orders.csv",
        upload_path="orders.csv",
        profile=profile,
        snapshot_name="orders",
        checkpoint_id="cp_source_orders",
        checkpoint_path="sources/orders.parquet",
        row_count=4,
    )
    frame = normalize_source_frame(
        pd.DataFrame(
            {
                "order_id": [1, 2, 3, 4],
                "amount": [10, 20, 30, 40],
                "region": ["East", "West", "East", "South"],
            }
        ),
        "orders",
    )
    write_checkpoint_atomically(
        frame,
        relative_path="sources/orders.parquet",
        parent_output_dir=tmp_path / "analysis",
    )
    plan = Plan.model_validate(
        {
            "units": [
                {
                    "unit_id": 1,
                    "operation": "derive_column",
                    "execution_mode": "template",
                    "purpose": "derive total",
                    "input_snapshot": "orders",
                    "input_columns": ["orders.amount"],
                    "output_columns": ["orders.total"],
                    "template_name": "column_arithmetic",
                    "params": {"operator": "*", "new_column": "total"},
                },
                {
                    "unit_id": 2,
                    "operation": "filter",
                    "execution_mode": "template",
                    "purpose": "east orders",
                    "depends_on": [1],
                    "input_snapshot": "orders",
                    "input_columns": ["orders.region", "orders.total"],
                    "output_snapshot": "east_orders",
                    "template_name": "filter_by_date",
                    "params": {"start": "2020-01-01", "date_column": "order_id"},
                },
                {
                    "unit_id": 3,
                    "operation": "terminal",
                    "execution_mode": "template",
                    "purpose": "terminal report",
                    "depends_on": [2],
                    "input_snapshot": "east_orders",
                    "input_columns": ["east_orders.total"],
                },
            ],
            "alignment_notes": "",
        }
    )
    return AgentState(
        user_requirement="",
        data_sources=[source],
        snapshot_registry={snapshot.snapshot_id: snapshot},
        checkpoint_registry={checkpoint.checkpoint_id: checkpoint},
        column_graph=ColumnGraph(nodes=nodes),
        plan=plan,
    )


def _executor(unit, input_path: str, output_dir: str, _previous=None) -> dict[str, object]:
    frame = pd.read_parquet(input_path)
    if unit.operation == "derive_column":
        result = frame.copy()
        result[unit.output_columns[0]] = result[unit.input_columns[0]] * 2
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "_result_df": result,
            "charts": [],
            "insights": [],
            "statistics": {},
            "output_dir": output_dir,
        }
    if unit.operation == "filter":
        result = frame.loc[frame[unit.input_columns[0]] == "East"].copy()
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "_result_df": result,
            "charts": [],
            "insights": [],
            "statistics": {},
            "output_dir": output_dir,
        }
    return {
        "unit_id": unit.unit_id,
        "status": "success",
        "charts": [],
        "insights": ["terminal ran"],
        "statistics": {},
        "output_dir": output_dir,
    }


def test_v2_dag_registers_explicit_checkpoints_and_lineage(tmp_path) -> None:
    state = _state(tmp_path)
    result = execute_dag(state, str(tmp_path / "analysis"), {}, _executor)

    assert result["status"] == "complete"
    unit_results = result["unit_results"]
    assert [item["status"] for item in unit_results] == ["success"] * 3
    assert unit_results[0]["input_checkpoint_ids"] == ["cp_source_orders"]
    assert unit_results[0]["output_checkpoint_id"].startswith("cp_run_")
    assert unit_results[1]["input_checkpoint_ids"] == [unit_results[0]["output_checkpoint_id"]]
    assert unit_results[2]["input_checkpoint_ids"] == [unit_results[1]["output_checkpoint_id"]]

    snapshots = result["snapshot_registry"]
    checkpoints = result["checkpoint_registry"]
    assert (
        snapshots["snap_orders"].current_checkpoint_id
        == unit_results[0]["output_checkpoint_id"]
    )
    assert (
        snapshots["snap_east_orders"].current_checkpoint_id
        == unit_results[1]["output_checkpoint_id"]
    )
    assert len(checkpoints) == 3
    assert any(
        node.ref == "orders.total" and node.created_by_unit_id == 1
        for node in result["column_graph"].nodes.values()
    )


def test_missing_checkpoint_never_calls_executor(tmp_path) -> None:
    state = _state(tmp_path)
    source_path = tmp_path / "sources" / "orders.parquet"
    source_path.unlink()
    called = False

    def fail_if_called(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("missing checkpoint must fail before execution")

    result = execute_dag(state, str(tmp_path / "analysis"), {}, fail_if_called)
    assert result["status"] == "partial"
    assert result["unit_results"][0]["status"] == "failed"
    assert "missing" in result["unit_results"][0]["error"].lower()
    assert called is False


def test_rerun_retains_history_and_cascade_uses_new_head(tmp_path) -> None:
    state = _state(tmp_path)
    first = execute_dag(state, str(tmp_path / "analysis"), {}, _executor)
    state = state.model_copy(
        update={
            "snapshot_registry": first["snapshot_registry"],
            "checkpoint_registry": first["checkpoint_registry"],
            "column_graph": first["column_graph"],
            "analysis_result": {
                "status": first["status"],
                "run_id": first["run_id"],
                "output_dir": str(tmp_path / "analysis"),
                "unit_results": first["unit_results"],
            },
        }
    )

    rerun = rerun_dag(
        state,
        str(tmp_path / "analysis"),
        1,
        cascade=False,
        execute_unit_fn=_executor,
    )
    rerun_id = rerun["rerun_result"]["output_checkpoint_id"]
    assert rerun_id != first["unit_results"][0]["output_checkpoint_id"]
    assert rerun["stale_unit_ids"] == [2, 3]
    assert len(rerun["analysis_result"]["history"]) == 1

    state = state.model_copy(
        update={
            "snapshot_registry": rerun["snapshot_registry"],
            "checkpoint_registry": rerun["checkpoint_registry"],
            "column_graph": rerun["column_graph"],
            "analysis_result": rerun["analysis_result"],
        }
    )
    cascaded = rerun_dag(
        state,
        str(tmp_path / "analysis"),
        1,
        cascade=True,
        execute_unit_fn=_executor,
    )
    cascade_results = cascaded["analysis_result"]["unit_results"]
    assert all(item["status"] == "success" for item in cascade_results)
    assert cascade_results[1]["input_checkpoint_ids"] == [
        cascade_results[0]["output_checkpoint_id"]
    ]
    assert cascaded["stale_unit_ids"] == []


def test_rerun_intermediate_unit_uses_its_recorded_input(tmp_path) -> None:
    state = _state(tmp_path)
    first = execute_dag(state, str(tmp_path / "analysis"), {}, _executor)
    state = state.model_copy(
        update={
            "snapshot_registry": first["snapshot_registry"],
            "checkpoint_registry": first["checkpoint_registry"],
            "column_graph": first["column_graph"],
            "analysis_result": {
                "status": first["status"],
                "run_id": first["run_id"],
                "output_dir": str(tmp_path / "analysis"),
                "unit_results": first["unit_results"],
            },
        }
    )
    rerun = rerun_dag(
        state,
        str(tmp_path / "analysis"),
        2,
        cascade=False,
        execute_unit_fn=_executor,
    )
    assert rerun["rerun_result"]["status"] == "success"
    assert rerun["rerun_result"]["input_checkpoint_ids"] == [
        first["unit_results"][1]["input_checkpoint_ids"][0]
    ]
    assert rerun["stale_unit_ids"] == [3]


def test_real_template_executor_uses_physical_column_names(tmp_path) -> None:
    state = _state(tmp_path)
    source = state.checkpoint_registry["cp_source_orders"]
    source_path = tmp_path / source.path
    unit = DeriveColumnUnit(
        unit_id=1,
        execution_mode="template",
        purpose="derive total",
        input_snapshot="orders",
        input_columns=["amount", "amount"],
        output_columns=["total"],
        template_name="column_arithmetic",
        template_params={"operator": "*", "new_column": "total"},
    )
    result = _execute_unit(unit, str(source_path), str(tmp_path / "unit_1"))

    assert result["status"] == "success"
    output = result["_result_df"]
    assert list(output["total"]) == [100, 400, 900, 1600]
    assert list(output["__di_row_id"]) == [
        "orders:0", "orders:1", "orders:2", "orders:3"
    ]


def test_analysis_node_returns_registry_patch(tmp_path) -> None:
    state = _state(tmp_path).model_copy(
        update={"analysis_result": {"output_dir": str(tmp_path / "analysis")}}
    )
    with patch("src.agent.nodes.analysis._execute_unit", side_effect=_executor):
        update = analysis_node(state)

    assert update["analysis_result"]["status"] == "complete"
    assert "snapshot_registry" in update
    assert "checkpoint_registry" in update
    assert "column_graph" in update
    assert "snapshot_registry" not in update["analysis_result"]


def test_join_dag_uses_two_checkpoints_and_persists_lineage(tmp_path) -> None:
    def profile(name: str, dtype: str) -> DataProfile:
        return DataProfile(
            file_path=f"{name}.csv",
            shape=(3, 2),
            columns=[
                ColumnProfile(
                    name=column,
                    dtype=column_dtype,
                    null_count=0,
                    null_pct=0.0,
                    unique_count=3,
                    unique_pct=100.0,
                )
                for column, column_dtype in (("id", dtype), ("value", "object"))
            ],
            statistics={},
            head_sample=[],
        )

    left_source, left_snapshot, left_checkpoint, left_nodes = build_source_records(
        source_id="src_left",
        display_name="left.csv",
        upload_path="left.csv",
        profile=profile("left", "int64"),
        snapshot_name="left",
        checkpoint_id="cp_source_left",
        checkpoint_path="sources/left.parquet",
        row_count=3,
    )
    right_source, right_snapshot, right_checkpoint, right_nodes = build_source_records(
        source_id="src_right",
        display_name="right.csv",
        upload_path="right.csv",
        profile=profile("right", "int64"),
        snapshot_name="right",
        checkpoint_id="cp_source_right",
        checkpoint_path="sources/right.parquet",
        row_count=3,
    )
    write_checkpoint_atomically(
        normalize_source_frame(
            pd.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]}),
            "left",
        ),
        relative_path="sources/left.parquet",
        parent_output_dir=tmp_path / "analysis",
    )
    write_checkpoint_atomically(
        normalize_source_frame(
            pd.DataFrame({"id": [2, 3, 4], "value": ["x", "y", "z"]}),
            "right",
        ),
        relative_path="sources/right.parquet",
        parent_output_dir=tmp_path / "analysis",
    )
    plan = Plan.model_validate(
        {
            "units": [
                {
                    "unit_id": 1,
                    "operation": "join",
                    "execution_mode": "template",
                    "purpose": "join source values",
                    "inputs": [
                        {"role": "right", "snapshot": "right"},
                        {"role": "left", "snapshot": "left"},
                    ],
                    "output_snapshot": "joined",
                    "how": "left",
                    "keys": [
                        {"left": "left.id", "right": "right.id"},
                    ],
                    "select": [
                        {"from": "left.value", "as": "left_value"},
                        {"from": "right.value", "as": "right_value"},
                    ],
                },
                {
                    "unit_id": 2,
                    "operation": "terminal",
                    "execution_mode": "template",
                    "purpose": "inspect joined values",
                    "depends_on": [1],
                    "input_snapshot": "joined",
                    "input_columns": ["joined.left_value"],
                },
            ]
        }
    )
    state = AgentState(
        user_requirement="",
        data_sources=[left_source, right_source],
        snapshot_registry={
            left_snapshot.snapshot_id: left_snapshot,
            right_snapshot.snapshot_id: right_snapshot,
        },
        checkpoint_registry={
            left_checkpoint.checkpoint_id: left_checkpoint,
            right_checkpoint.checkpoint_id: right_checkpoint,
        },
        column_graph=ColumnGraph(nodes={**left_nodes, **right_nodes}),
        plan=plan,
    )
    calls: list[int] = []

    def terminal_executor(unit, _input_path, output_dir, _previous=None):
        calls.append(unit.unit_id)
        return {
            "unit_id": unit.unit_id,
            "status": "success",
            "charts": [],
            "insights": [],
            "statistics": {},
            "output_dir": output_dir,
        }

    result = execute_dag(
        state,
        str(tmp_path / "analysis"),
        {},
        terminal_executor,
    )

    assert result["status"] == "complete"
    assert calls == [2]
    join_result = result["unit_results"][0]
    assert join_result["input_checkpoint_ids"] == [
        "cp_source_left",
        "cp_source_right",
    ]
    assert {
        warning["code"] for warning in join_result["warnings"]
    } == {"JOIN_UNMATCHED_KEYS"}
    output_id = join_result["output_checkpoint_id"]
    checkpoint = result["checkpoint_registry"][output_id]
    output = pd.read_parquet(tmp_path / checkpoint.path)
    assert list(output.columns) == ["__di_row_id", "left_value", "right_value"]
    assert output["__di_row_id"].is_unique
    assert checkpoint.parent_checkpoint_ids == [
        "cp_source_left",
        "cp_source_right",
    ]
    graph = result["column_graph"]
    left_node_id = checkpoint.columns["joined.left_value"]
    right_node_id = checkpoint.columns["joined.right_value"]
    assert graph.nodes[left_node_id].derived_from_node_ids == [
        left_checkpoint.columns["left.value"]
    ]
    assert graph.nodes[right_node_id].derived_from_node_ids == [
        right_checkpoint.columns["right.value"]
    ]
