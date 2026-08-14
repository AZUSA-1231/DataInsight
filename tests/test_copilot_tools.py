from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from src.agent.copilot_tools import (
    InspectColumnInput,
    InspectColumnResult,
    InspectResultsInput,
    InspectResultsResult,
    InspectSnapshotInput,
    InspectSnapshotResult,
    MockPlanEditGateway,
    PlanEditGatewayError,
    PlanEditInput,
    PlanEditResult,
    build_copilot_tool_bindings,
    inspect_column,
    inspect_results,
    inspect_snapshot,
    plan_edit,
)
from src.agent.lineage import build_source_records
from src.agent.state import (
    AgentState,
    ColumnGraph,
    ColumnProfile,
    DataProfile,
    Plan,
)


def _state(*, plan: Plan | None = None, results: dict[str, object] | None = None) -> AgentState:
    profile = DataProfile(
        file_path=r"C:\private\orders.csv",
        shape=(3, 3),
        columns=[
            ColumnProfile(
                name="amount",
                dtype="float64",
                null_count=1,
                null_pct=33.3,
                unique_count=2,
                unique_pct=66.7,
            ),
            ColumnProfile(
                name="region",
                dtype="object",
                null_count=0,
                null_pct=0.0,
                unique_count=2,
                unique_pct=66.7,
            ),
            ColumnProfile(
                name="__di_row_id",
                dtype="object",
                null_count=0,
                null_pct=0.0,
                unique_count=3,
                unique_pct=100.0,
            ),
        ],
        statistics={"amount": {"mean": 10.5, "max": 20.0}},
        head_sample=[
            {"amount": 10.0, "region": "East", "__di_row_id": "orders:0"},
            {"amount": 11.0, "region": "West", "__di_row_id": "orders:1"},
        ],
    )
    source, snapshot, checkpoint, nodes = build_source_records(
        source_id="src_orders",
        display_name="orders.csv",
        upload_path=r"C:\private\orders.csv",
        profile=profile,
        snapshot_name="orders",
        checkpoint_id="cp_orders",
        checkpoint_path=r"C:\private\checkpoints\orders.parquet",
        row_count=3,
    )
    return AgentState(
        user_requirement="inspect orders",
        data_sources=[source],
        snapshot_registry={snapshot.snapshot_id: snapshot},
        checkpoint_registry={checkpoint.checkpoint_id: checkpoint},
        column_graph=ColumnGraph(nodes=nodes),
        plan=plan,
        analysis_result=results,
    )


def _terminal_plan() -> Plan:
    return Plan.model_validate(
        {
            "units": [
                {
                    "unit_id": 1,
                    "operation": "terminal",
                    "purpose": "summarize amount",
                    "input_snapshot": "orders",
                    "input_columns": ["orders.amount"],
                }
            ],
            "alignment_notes": "",
        }
    )


def test_static_bindings_are_explicit_and_typed() -> None:
    bindings = build_copilot_tool_bindings()

    assert [binding.name for binding in bindings] == [
        "inspect_column",
        "inspect_snapshot",
        "inspect_results",
        "plan_edit",
    ]
    assert all(binding.schema["function"]["name"] == binding.name for binding in bindings)


def test_inspection_tools_return_only_public_workspace_facts() -> None:
    state = _state(
        results={
            "status": "complete",
            "stale_unit_ids": [1],
            "unit_results": [
                {
                    "unit_id": 1,
                    "status": "success",
                    "insights": ["amount is available"],
                    "statistics": {"mean": 10.5},
                    "warnings": [{"code": "MISSING_VALUES"}],
                    "charts": [r"C:\private\chart.png"],
                    "_result_df": object(),
                    "output_dir": r"C:\private\output",
                }
            ],
        }
    )

    column = inspect_column(state, InspectColumnInput(column_name="orders.amount"))
    snapshot = inspect_snapshot(state, InspectSnapshotInput(snapshot_name="orders"))
    results = inspect_results(state, InspectResultsInput())

    assert isinstance(column, InspectColumnResult)
    assert column.found is True
    assert column.statistics == {"mean": 10.5, "max": 20.0}
    assert column.sample_values == [10.0, 11.0]
    assert isinstance(snapshot, InspectSnapshotResult)
    assert snapshot.found is True
    assert [item.ref for item in snapshot.columns] == ["orders.amount", "orders.region"]
    assert isinstance(results, InspectResultsResult)
    assert results.found is True
    assert results.unit_results[0].chart_count == 1

    serialized = " ".join(
        [column.model_dump_json(), snapshot.model_dump_json(), results.model_dump_json()]
    )
    assert "__di_row_id" not in serialized
    assert "_result_df" not in serialized
    assert "C:\\private" not in serialized
    assert "node_id" not in serialized


def test_unknown_inspection_value_is_a_typed_not_found_result() -> None:
    state = _state()
    result = inspect_column(state, InspectColumnInput(column_name="orders.missing"))
    assert result.found is False
    assert "orders.amount" in result.available_columns

    with pytest.raises(ValidationError):
        InspectColumnInput.model_validate({"column_name": ""})


def test_plan_edit_gateway_returns_validated_plan_without_mutating_state() -> None:
    state = _state()
    gateway = MockPlanEditGateway(
        plan=_terminal_plan(),
        explanation="Use amount as the report input.",
        changed_unit_ids=[1],
    )

    result = plan_edit(
        state,
        PlanEditInput(request="Create a concise amount report"),
        gateway,
    )

    assert isinstance(result, PlanEditResult)
    assert result.plan.model_dump() == _terminal_plan().model_dump()
    assert result.changed_unit_ids == [1]
    assert state.plan is None


def test_plan_edit_gateway_can_parse_complete_plan_from_json_request() -> None:
    state = _state()
    payload = _terminal_plan().model_dump(mode="json")
    gateway = MockPlanEditGateway()

    result = plan_edit(
        state,
        PlanEditInput(request=json.dumps({"plan": payload})),
        gateway,
    )

    assert result.plan.model_dump(mode="json") == payload


def test_plan_edit_rejects_workspace_invalid_plan() -> None:
    state = _state()
    invalid = Plan.model_validate(
        {
            "units": [
                {
                    "unit_id": 1,
                    "operation": "terminal",
                    "purpose": "missing source",
                    "input_snapshot": "does_not_exist",
                    "input_columns": ["does_not_exist.amount"],
                }
            ]
        }
    )

    with pytest.raises(PlanEditGatewayError, match="workspace validation"):
        plan_edit(
            state,
            PlanEditInput(request="revise"),
            MockPlanEditGateway(plan=invalid),
        )
