from __future__ import annotations

import pytest

from src.agent.dag import (
    DagCycleError,
    topological_levels,
    transitive_dependents,
    validate_columns,
)
from src.agent.state import TerminalUnit


def _terminal(unit_id: int, depends_on: list[int] | None = None) -> TerminalUnit:
    return TerminalUnit(
        unit_id=unit_id,
        purpose=f"terminal {unit_id}",
        depends_on=depends_on or [],
        input_snapshot="orders",
        input_columns=["orders.amount"],
    )


def test_topological_levels_and_cycle_detection() -> None:
    units = [_terminal(1), _terminal(2, [1]), _terminal(3, [1])]
    levels = topological_levels(units)
    assert [[unit.unit_id for unit in level] for level in levels] == [[1], [2, 3]]

    with pytest.raises(DagCycleError):
        topological_levels([_terminal(1, [2]), _terminal(2, [1])])


def test_validate_columns_is_exact() -> None:
    assert validate_columns(["orders.amount", "orders.missing"], {"orders.amount"}) == (
        ["orders.missing"],
        ["orders.amount"],
    )


def test_transitive_dependents_follow_dag_order() -> None:
    units = [_terminal(1), _terminal(2, [1]), _terminal(3, [2]), _terminal(4, [1])]
    assert transitive_dependents(1, units) == [2, 4, 3]
