from __future__ import annotations

import pytest

from src.agent.lineage import build_source_records
from src.agent.plan_validation import (
    PlanValidationError,
    collect_plan_issues,
    validate_plan,
)
from src.agent.state import (
    AgentState,
    ColumnGraph,
    ColumnProfile,
    DataProfile,
    Plan,
)


def _profile(filename: str, columns: list[str]) -> DataProfile:
    return DataProfile(
        file_path=filename,
        shape=(3, len(columns)),
        columns=[
            ColumnProfile(
                name=name,
                dtype="object",
                null_count=0,
                null_pct=0.0,
                unique_count=3,
                unique_pct=100.0,
            )
            for name in columns
        ],
        statistics={},
        head_sample=[],
    )


@pytest.fixture
def registry_state() -> AgentState:
    order_profile = _profile(
        "orders.csv", ["order_id", "customer_id", "price", "quantity", "region"]
    )
    customer_profile = _profile("customers.csv", ["customer_id", "segment"])
    order_source, order_snapshot, order_checkpoint, order_nodes = build_source_records(
        source_id="src_orders",
        display_name="orders.csv",
        upload_path="orders.csv",
        profile=order_profile,
        snapshot_name="orders",
        checkpoint_id="cp_source_orders",
        checkpoint_path="sources/orders.parquet",
        row_count=3,
    )
    customer_source, customer_snapshot, customer_checkpoint, customer_nodes = (
        build_source_records(
            source_id="src_customers",
            display_name="customers.csv",
            upload_path="customers.csv",
            profile=customer_profile,
            snapshot_name="customers",
            checkpoint_id="cp_source_customers",
            checkpoint_path="sources/customers.parquet",
            row_count=3,
        )
    )
    return AgentState(
        user_requirement="",
        data_sources=[order_source, customer_source],
        snapshot_registry={
            order_snapshot.snapshot_id: order_snapshot,
            customer_snapshot.snapshot_id: customer_snapshot,
        },
        checkpoint_registry={
            order_checkpoint.checkpoint_id: order_checkpoint,
            customer_checkpoint.checkpoint_id: customer_checkpoint,
        },
        column_graph=ColumnGraph(nodes={**order_nodes, **customer_nodes}),
        unified_columns=list(order_checkpoint.columns) + list(customer_checkpoint.columns),
    )


def _plan(*units: dict[str, object]) -> Plan:
    return Plan.model_validate({"units": list(units), "alignment_notes": ""})


def test_registry_validation_accepts_derive_filter_join_terminal(
    registry_state: AgentState,
) -> None:
    plan = _plan(
        {
            "unit_id": 1,
            "operation": "derive_column",
            "purpose": "revenue",
            "input_snapshot": "orders",
            "input_columns": ["orders.price", "orders.quantity"],
            "output_columns": ["orders.revenue"],
        },
        {
            "unit_id": 2,
            "operation": "filter",
            "purpose": "east",
            "depends_on": [1],
            "input_snapshot": "orders",
            "input_columns": ["orders.region", "orders.revenue"],
            "output_snapshot": "east_orders",
        },
        {
            "unit_id": 3,
            "operation": "join",
            "purpose": "segment",
            "depends_on": [2],
            "inputs": [
                {"role": "left", "snapshot": "east_orders"},
                {"role": "right", "snapshot": "customers"},
            ],
            "output_snapshot": "east_orders_with_segment",
            "keys": [
                {
                    "left": "east_orders.customer_id",
                    "right": "customers.customer_id",
                }
            ],
            "select": [
                {"from": "east_orders.order_id", "as": "order_id"},
                {"from": "east_orders.revenue", "as": "revenue"},
                {"from": "customers.segment", "as": "segment"},
            ],
        },
        {
            "unit_id": 4,
            "operation": "terminal",
            "purpose": "report",
            "depends_on": [3],
            "input_snapshot": "east_orders_with_segment",
            "input_columns": ["east_orders_with_segment.segment"],
        },
    )

    validate_plan(plan, registry_state)


def test_missing_qualified_column_is_rejected(registry_state: AgentState) -> None:
    plan = _plan(
        {
            "unit_id": 1,
            "operation": "terminal",
            "purpose": "inspect",
            "input_snapshot": "orders",
            "input_columns": ["orders.not_a_column"],
        }
    )

    issues = collect_plan_issues(plan, registry_state)
    assert any(issue.code == "MISSING_COLUMN" for issue in issues)
    with pytest.raises(PlanValidationError):
        validate_plan(plan, registry_state)


def test_same_snapshot_derive_writers_must_be_chained(registry_state: AgentState) -> None:
    plan = _plan(
        {
            "unit_id": 1,
            "operation": "derive_column",
            "purpose": "revenue",
            "input_snapshot": "orders",
            "input_columns": ["orders.price"],
            "output_columns": ["orders.revenue"],
        },
        {
            "unit_id": 3,
            "operation": "derive_column",
            "purpose": "margin",
            "input_snapshot": "orders",
            "input_columns": ["orders.quantity"],
            "output_columns": ["orders.margin"],
        },
    )

    issues = collect_plan_issues(plan, registry_state)
    assert any(issue.code == "DERIVE_WRITERS_NOT_CHAINED" for issue in issues)


def test_output_snapshot_must_be_unused(registry_state: AgentState) -> None:
    plan = _plan(
        {
            "unit_id": 1,
            "operation": "filter",
            "purpose": "duplicate source name",
            "input_snapshot": "orders",
            "input_columns": ["orders.region"],
            "output_snapshot": "customers",
        }
    )

    issues = collect_plan_issues(plan, registry_state)
    assert any(issue.code == "OUTPUT_SNAPSHOT_EXISTS" for issue in issues)


def test_terminal_must_be_a_leaf(registry_state: AgentState) -> None:
    plan = _plan(
        {
            "unit_id": 1,
            "operation": "terminal",
            "purpose": "report",
            "input_snapshot": "orders",
            "input_columns": ["orders.region"],
        },
        {
            "unit_id": 2,
            "operation": "terminal",
            "purpose": "downstream report",
            "depends_on": [1],
            "input_snapshot": "orders",
            "input_columns": ["orders.region"],
        },
    )

    issues = collect_plan_issues(plan, registry_state)
    assert any(issue.code == "TERMINAL_NOT_LEAF" for issue in issues)
