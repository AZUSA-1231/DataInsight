from __future__ import annotations

import pandas as pd
import pytest
from pydantic import ValidationError

from src.agent.join_executor import JoinExecutionError, execute_join
from src.agent.nodes.analysis import _execute_unit
from src.agent.state import JoinUnit

LEFT_COLUMNS = {
    "left.id": "id",
    "left.value": "value",
}
RIGHT_COLUMNS = {
    "right.id": "id",
    "right.label": "label",
}


def _left(ids: list[object] | None = None) -> pd.DataFrame:
    values = ids or [1, 2, 3]
    return pd.DataFrame(
        {
            "__di_row_id": [f"left:{index}" for index in range(len(values))],
            "id": values,
            "value": [f"v{index}" for index in range(len(values))],
        }
    )


def _right(ids: list[object] | None = None) -> pd.DataFrame:
    values = ids or [2, 3, 4]
    return pd.DataFrame(
        {
            "__di_row_id": [f"right:{index}" for index in range(len(values))],
            "id": values,
            "label": [f"l{index}" for index in range(len(values))],
        }
    )


def _unit(
    how: str,
    *,
    select_right: bool = True,
    keys: bool = True,
) -> JoinUnit:
    return JoinUnit(
        unit_id=1,
        purpose=f"{how} join",
        inputs=[
            {"role": "left", "snapshot": "left"},
            {"role": "right", "snapshot": "right"},
        ],
        output_snapshot="joined",
        how=how,
        keys=(
            [{"left": "left.id", "right": "right.id"}]
            if keys
            else []
        ),
        select=[
            {"from": "left.value", "as": "value"},
            *([{"from": "right.label", "as": "label"}] if select_right else []),
        ],
    )


@pytest.mark.parametrize(
    ("how", "expected_rows"),
    [
        ("inner", 2),
        ("left", 3),
        ("right", 3),
        ("outer", 4),
        ("semi", 2),
        ("anti", 1),
    ],
)
def test_keyed_modes_materialize_declared_aliases(
    how: str,
    expected_rows: int,
) -> None:
    result = execute_join(
        _unit(how, select_right=how not in {"semi", "anti"}),
        _left(),
        _right(),
        left_columns=LEFT_COLUMNS,
        right_columns=RIGHT_COLUMNS,
        row_id_prefix="joined:run",
    )

    assert len(result.frame) == expected_rows
    assert list(result.frame.columns) == ["__di_row_id", "value"] + (
        [] if how in {"semi", "anti"} else ["label"]
    )
    assert result.frame["__di_row_id"].is_unique
    assert not set(result.frame["__di_row_id"]).intersection(
        set(_left()["__di_row_id"]) | set(_right()["__di_row_id"])
    )
    if how == "semi":
        assert result.frame["value"].tolist() == ["v1", "v2"]
    if how == "anti":
        assert result.frame["value"].tolist() == ["v0"]


def test_cross_mode_has_no_keys_and_is_deterministic() -> None:
    result = execute_join(
        _unit("cross", keys=False),
        _left(),
        _right(),
        left_columns=LEFT_COLUMNS,
        right_columns=RIGHT_COLUMNS,
        row_id_prefix="crossed:run",
    )

    assert len(result.frame) == 9
    assert result.frame[["value", "label"]].to_dict("records")[:2] == [
        {"value": "v0", "label": "l0"},
        {"value": "v0", "label": "l1"},
    ]


def test_join_warnings_are_structured_and_non_blocking() -> None:
    unit = _unit("inner")
    result = execute_join(
        unit,
        _left([1, 1, 2]),
        _right([1, 1, 3]),
        left_columns=LEFT_COLUMNS,
        right_columns=RIGHT_COLUMNS,
        row_id_prefix="joined:warning",
    )

    assert len(result.frame) == 4
    warnings = {warning["code"]: warning for warning in result.warnings}
    assert {
        "JOIN_MANY_TO_MANY",
        "JOIN_ROW_EXPANSION",
        "JOIN_UNMATCHED_KEYS",
    } <= warnings.keys()
    assert warnings["JOIN_MANY_TO_MANY"]["severity"] == "warning"
    assert warnings["JOIN_ROW_EXPANSION"]["details"]["output_row_count"] == 4


def test_dtype_mismatch_warns_when_pandas_can_execute() -> None:
    right = _right([1.0, 2.0, 4.0])
    result = execute_join(
        _unit("inner"),
        _left(),
        right,
        left_columns=LEFT_COLUMNS,
        right_columns=RIGHT_COLUMNS,
        row_id_prefix="joined:dtype",
    )

    assert len(result.frame) == 2
    mismatch = next(
        warning for warning in result.warnings
        if warning["code"] == "JOIN_KEY_DTYPE_MISMATCH"
    )
    assert mismatch["details"]["keys"][0]["left_dtype"] == "int64"
    assert mismatch["details"]["keys"][0]["right_dtype"] == "float64"


def test_missing_key_is_a_mechanical_error() -> None:
    with pytest.raises(JoinExecutionError, match="not present"):
        execute_join(
            _unit("inner"),
            _left(),
            _right(),
            left_columns={},
            right_columns=RIGHT_COLUMNS,
            row_id_prefix="joined:error",
        )


def test_semi_anti_and_alias_contracts_fail_before_execution() -> None:
    with pytest.raises(ValidationError, match="left Snapshot"):
        _unit("semi", select_right=True)

    with pytest.raises(ValidationError, match="aliases must be unique"):
        JoinUnit(
            unit_id=2,
            purpose="duplicate aliases",
            inputs=[
                {"role": "left", "snapshot": "left"},
                {"role": "right", "snapshot": "right"},
            ],
            output_snapshot="joined",
            keys=[{"left": "left.id", "right": "right.id"}],
            select=[
                {"from": "left.value", "as": "same"},
                {"from": "right.label", "as": "same"},
            ],
        )


def test_legacy_single_input_entry_never_generates_join_code(tmp_path) -> None:
    result = _execute_unit(_unit("inner"), "missing.parquet", str(tmp_path))

    assert result["status"] == "failed"
    assert "two-input DAG" in result["error"]
