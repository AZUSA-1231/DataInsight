"""Frame-level contracts for operation-specific execution."""

from __future__ import annotations

from collections.abc import Iterable

import pandas as pd

from src.agent.lineage import ROW_ID_COLUMN


class OperationContractError(ValueError):
    """Raised when an operation returns a frame outside its declared contract."""


def validate_derive_frame(
    input_frame: pd.DataFrame,
    output_frame: pd.DataFrame,
    output_column: str,
) -> None:
    """Validate the row-preserving, one-new-column Derive contract."""
    _validate_row_id(input_frame, "input")
    _validate_row_id(output_frame, "output")
    if len(output_frame) != len(input_frame):
        raise OperationContractError("Derive changed row count")
    if output_frame[ROW_ID_COLUMN].tolist() != input_frame[ROW_ID_COLUMN].tolist():
        raise OperationContractError("Derive changed row identity or row order")
    expected_columns = [*input_frame.columns, output_column]
    if list(output_frame.columns) != expected_columns:
        raise OperationContractError(
            "Derive must preserve all input columns and add exactly one output column"
        )


def validate_filter_frame(
    input_frame: pd.DataFrame,
    output_frame: pd.DataFrame,
) -> None:
    """Validate the indexed-subset Filter contract."""
    _validate_row_id(input_frame, "input")
    _validate_row_id(output_frame, "output")
    if list(output_frame.columns) != list(input_frame.columns):
        raise OperationContractError("Filter must preserve the complete column set")
    if len(output_frame) > len(input_frame):
        raise OperationContractError("Filter cannot add rows")
    input_ids = input_frame[ROW_ID_COLUMN]
    output_ids = output_frame[ROW_ID_COLUMN]
    if not output_ids.is_unique:
        raise OperationContractError("Filter must return unique row IDs")
    if not output_ids.isin(input_ids).all():
        raise OperationContractError("Filter introduced row IDs not present in its input")


def validate_join_frame(
    output_frame: pd.DataFrame,
    aliases: Iterable[str],
) -> None:
    """Validate the explicit visible-column shape of a Join result."""
    _validate_row_id(output_frame, "join output")
    expected_aliases = list(aliases)
    if len(expected_aliases) != len(set(expected_aliases)):
        raise OperationContractError("Join select aliases must be unique")
    if ROW_ID_COLUMN in expected_aliases:
        raise OperationContractError(f"'{ROW_ID_COLUMN}' is reserved by DataInsight")
    expected_columns = [ROW_ID_COLUMN, *expected_aliases]
    if list(output_frame.columns) != expected_columns:
        raise OperationContractError(
            "Join output columns do not match the declared select aliases"
        )


def _validate_row_id(frame: pd.DataFrame, label: str) -> None:
    if ROW_ID_COLUMN not in frame.columns:
        raise OperationContractError(
            f"{label} data-producing frame must contain {ROW_ID_COLUMN}"
        )
    if not frame.columns.is_unique:
        raise OperationContractError(f"{label} frame must have unique column names")
    if not frame[ROW_ID_COLUMN].is_unique:
        raise OperationContractError(f"{label} frame must have unique {ROW_ID_COLUMN}")
