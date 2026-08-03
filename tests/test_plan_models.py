from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.agent.state import (
    DeriveColumnUnit,
    FilterUnit,
    JoinUnit,
    Plan,
    TerminalUnit,
)


def _complete_payload() -> dict[str, object]:
    return {
        "units": [
            {
                "unit_id": 1,
                "operation": "derive_column",
                "execution_mode": "template",
                "purpose": "Calculate revenue",
                "cautious": "",
                "depends_on": [],
                "input_snapshot": "orders",
                "input_columns": ["orders.price", "orders.quantity"],
                "output_columns": ["orders.revenue"],
                "template_name": "column_arithmetic",
                "params": {"operator": "*", "new_column": "revenue"},
            },
            {
                "unit_id": 2,
                "operation": "filter",
                "execution_mode": "llm",
                "purpose": "Select East orders",
                "cautious": "",
                "depends_on": [1],
                "input_snapshot": "orders",
                "input_columns": ["orders.region"],
                "output_snapshot": "east_orders",
                "params": {"condition": "region == 'East'"},
            },
            {
                "unit_id": 3,
                "operation": "join",
                "execution_mode": "template",
                "purpose": "Add customer segment",
                "cautious": "",
                "depends_on": [2],
                "inputs": [
                    {"role": "left", "snapshot": "east_orders"},
                    {"role": "right", "snapshot": "customers"},
                ],
                "output_snapshot": "east_orders_with_segment",
                "how": "left",
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
                "execution_mode": "template",
                "purpose": "Report segments",
                "cautious": "",
                "depends_on": [3],
                "input_snapshot": "east_orders_with_segment",
                "input_columns": ["east_orders_with_segment.segment"],
                "template_name": "scatter_plot",
            },
        ],
        "alignment_notes": "The source supports this workflow.",
    }


def test_plan_v2_uses_operation_discriminator_and_round_trips() -> None:
    plan = Plan.model_validate(_complete_payload())

    assert isinstance(plan.units[0], DeriveColumnUnit)
    assert isinstance(plan.units[1], FilterUnit)
    assert isinstance(plan.units[2], JoinUnit)
    assert isinstance(plan.units[3], TerminalUnit)
    assert plan.units[0].template_params == {
        "operator": "*",
        "new_column": "revenue",
    }

    dumped = plan.model_dump()
    assert dumped["units"][0]["operation"] == "derive_column"
    assert "related_fields" not in dumped["units"][0]
    assert "input_from" not in dumped["units"][0]
    assert "unit_type" not in dumped["units"][0]

    restored = Plan.model_validate(dumped)
    assert restored.model_dump() == dumped


def test_derive_requires_exactly_one_output_column() -> None:
    payload = _complete_payload()
    unit = payload["units"][0]
    assert isinstance(unit, dict)
    unit["output_columns"] = []

    with pytest.raises(ValidationError):
        Plan.model_validate(payload)


def test_v2_requires_an_explicit_operation() -> None:
    with pytest.raises(ValidationError, match="declare an operation"):
        Plan.model_validate(
            {
                "units": [
                    {
                        "unit_id": 1,
                        "purpose": "missing operation",
                    }
                ],
                "alignment_notes": "",
            }
        )


def test_join_rejects_duplicate_aliases() -> None:
    payload = _complete_payload()
    unit = payload["units"][2]
    assert isinstance(unit, dict)
    unit["select"] = [
        {"from": "east_orders.order_id", "as": "id"},
        {"from": "customers.segment", "as": "id"},
    ]

    with pytest.raises(ValidationError, match="aliases must be unique"):
        Plan.model_validate(payload)
