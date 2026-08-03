from __future__ import annotations

import pandas as pd
import pytest

from src.agent.lineage import ROW_ID_COLUMN
from src.agent.operations import (
    OperationContractError,
    validate_derive_frame,
    validate_filter_frame,
    validate_join_frame,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            ROW_ID_COLUMN: ["orders:0", "orders:1"],
            "amount": [10, 20],
        }
    )


def test_derive_contract_preserves_rows_and_adds_one_column() -> None:
    input_frame = _frame()
    output_frame = input_frame.assign(total=[20, 40])

    validate_derive_frame(input_frame, output_frame, "total")

    with pytest.raises(OperationContractError, match="row count"):
        validate_derive_frame(input_frame, output_frame.iloc[:1], "total")


def test_filter_contract_accepts_only_an_indexed_row_subset() -> None:
    input_frame = _frame()
    validate_filter_frame(input_frame, input_frame.iloc[[1]].copy())

    duplicate_rows = pd.concat([input_frame.iloc[[0]], input_frame.iloc[[0]]])
    with pytest.raises(OperationContractError, match="unique __di_row_id"):
        validate_filter_frame(input_frame, duplicate_rows)


def test_join_contract_requires_visible_aliases_after_hidden_row_id() -> None:
    output = pd.DataFrame({ROW_ID_COLUMN: ["joined:0"], "value": [1]})
    validate_join_frame(output, ["value"])

    with pytest.raises(OperationContractError, match="reserved"):
        validate_join_frame(output, [ROW_ID_COLUMN])
