"""Deterministic pandas execution for the v2 Join operation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, cast

import pandas as pd

from src.agent.lineage import ROW_ID_COLUMN
from src.agent.operations import OperationContractError, validate_join_frame
from src.agent.state import JoinUnit

JOIN_MODES = frozenset({"inner", "left", "right", "outer", "cross", "semi", "anti"})


class JoinExecutionError(ValueError):
    """Raised when a Join cannot be materialized from its declared inputs."""


@dataclass(frozen=True)
class JoinExecutionResult:
    """A materialized Join frame and durable analytical warnings."""

    frame: pd.DataFrame
    warnings: list[dict[str, object]]
    statistics: dict[str, object]


def execute_join(
    unit: JoinUnit,
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    *,
    left_columns: Mapping[str, str],
    right_columns: Mapping[str, str],
    row_id_prefix: str,
) -> JoinExecutionResult:
    """Execute one Join without generated code or filesystem access."""
    if unit.how not in JOIN_MODES:
        raise JoinExecutionError(f"Unsupported join mode '{unit.how}'")
    _validate_input_frame(left_frame, "left")
    _validate_input_frame(right_frame, "right")

    left_key_refs = [key.left for key in unit.keys]
    right_key_refs = [key.right for key in unit.keys]
    left_keys = [_resolve_column(left_columns, ref, "left") for ref in left_key_refs]
    right_keys = [_resolve_column(right_columns, ref, "right") for ref in right_key_refs]

    if unit.how == "cross" and unit.keys:
        raise JoinExecutionError("Cross joins must not declare key pairs")
    if unit.how != "cross" and not unit.keys:
        raise JoinExecutionError(f"{unit.how} joins require at least one key pair")

    selected_roles: list[tuple[str, str, str]] = []
    seen_aliases: set[str] = set()
    for selected in unit.select:
        alias = selected.as_
        if not alias or alias == ROW_ID_COLUMN:
            raise JoinExecutionError(
                f"Join alias '{alias}' is empty or reserved"
            )
        if alias in seen_aliases:
            raise JoinExecutionError(f"Join select alias '{alias}' is duplicated")
        seen_aliases.add(alias)
        role = _role_for_ref(unit, selected.from_)
        if unit.how in {"semi", "anti"} and role != "left":
            raise JoinExecutionError(
                f"{unit.how} joins may select columns only from the left Snapshot"
            )
        local = _resolve_column(
            left_columns if role == "left" else right_columns,
            selected.from_,
            role,
        )
        selected_roles.append((role, local, alias))

    dtype_details = _dtype_mismatch_details(
        unit, left_frame, right_frame, left_keys, right_keys
    )
    duplicate_details = _duplicate_key_details(
        left_frame, right_frame, left_keys, right_keys
    )

    left_internal, left_internal_columns = _rename_frame(left_frame, "__di_left_")
    right_internal, right_internal_columns = _rename_frame(right_frame, "__di_right_")
    left_internal_keys = [left_internal_columns[column] for column in left_keys]
    right_internal_keys = [right_internal_columns[column] for column in right_keys]

    if unit.how == "cross":
        merged = left_internal.merge(right_internal, how="cross", sort=False)
        output_internal = merged
    elif unit.how in {"semi", "anti"}:
        right_key_frame = right_internal.loc[:, right_internal_keys].drop_duplicates()
        matched = left_internal.merge(
            right_key_frame,
            how="left",
            left_on=left_internal_keys,
            right_on=right_internal_keys,
            indicator=True,
            sort=False,
        )
        is_match = matched["_merge"].eq("both").to_numpy()
        output_internal = left_internal.loc[is_match].reset_index(drop=True)
        if unit.how == "anti":
            output_internal = left_internal.loc[~is_match].reset_index(drop=True)
    else:
        if unit.how not in {"left", "right", "inner", "outer"}:
            raise JoinExecutionError(f"Unsupported pandas join mode '{unit.how}'")
        pandas_how = cast(
            Literal["left", "right", "inner", "outer"],
            unit.how,
        )
        output_internal = left_internal.merge(
            right_internal,
            how=pandas_how,
            left_on=left_internal_keys,
            right_on=right_internal_keys,
            sort=False,
        )

    selected_parts: list[pd.DataFrame] = []
    for role, local, alias in selected_roles:
        internal_name = (
            left_internal_columns[local]
            if role == "left"
            else right_internal_columns[local]
        )
        selected_part = output_internal.loc[:, [internal_name]].copy()
        selected_part.columns = [alias]
        selected_parts.append(selected_part)

    output = pd.concat(selected_parts, axis=1).reset_index(drop=True)
    output.insert(
        0,
        ROW_ID_COLUMN,
        [f"{row_id_prefix}:{index}" for index in range(len(output))],
    )
    try:
        validate_join_frame(output, [selected.as_ for selected in unit.select])
    except OperationContractError as exc:
        raise JoinExecutionError(str(exc)) from exc

    unmatched_details = _unmatched_key_details(
        left_frame, right_frame, left_keys, right_keys
    )
    warnings: list[dict[str, object]] = []
    if duplicate_details is not None and duplicate_details.get("many_to_many"):
        warnings.append(
            _warning(
                "JOIN_MANY_TO_MANY",
                "Matched Join keys are duplicated on both inputs.",
                duplicate_details,
            )
        )

    baseline = _row_expansion_baseline(unit.how, len(left_frame), len(right_frame))
    if unit.how not in {"semi", "anti"} and len(output) > baseline:
        warnings.append(
            _warning(
                "JOIN_ROW_EXPANSION",
                "Join output contains more rows than its mode baseline.",
                {
                    "how": unit.how,
                    "baseline_row_count": baseline,
                    "output_row_count": len(output),
                    "left_row_count": len(left_frame),
                    "right_row_count": len(right_frame),
                },
            )
        )

    if dtype_details:
        warnings.append(
            _warning(
                "JOIN_KEY_DTYPE_MISMATCH",
                "One or more paired Join keys use different pandas dtypes.",
                {"keys": dtype_details},
            )
        )

    if unmatched_details is not None:
        warnings.append(
            _warning(
                "JOIN_UNMATCHED_KEYS",
                "Some Join key rows have no counterpart on the other input.",
                unmatched_details,
            )
        )

    statistics: dict[str, object] = {
        "how": unit.how,
        "left_row_count": len(left_frame),
        "right_row_count": len(right_frame),
        "output_row_count": len(output),
        "key_count": len(unit.keys),
        "key_dtypes": [
            {
                "left": key.left,
                "right": key.right,
                "left_dtype": str(left_frame[left_column].dtype),
                "right_dtype": str(right_frame[right_column].dtype),
            }
            for key, left_column, right_column in zip(
                unit.keys, left_keys, right_keys, strict=True
            )
        ],
        "duplicate_keys": duplicate_details or {},
        "unmatched_keys": unmatched_details or {},
        "cardinality": _observed_cardinality(
            left_frame, right_frame, left_keys, right_keys
        ),
    }
    return JoinExecutionResult(frame=output, warnings=warnings, statistics=statistics)


def _validate_input_frame(frame: pd.DataFrame, role: str) -> None:
    if ROW_ID_COLUMN not in frame.columns:
        raise JoinExecutionError(f"{role} Join input is missing {ROW_ID_COLUMN}")
    if not frame.columns.is_unique:
        raise JoinExecutionError(f"{role} Join input has duplicate column names")
    if not frame[ROW_ID_COLUMN].is_unique:
        raise JoinExecutionError(f"{role} Join input has duplicate {ROW_ID_COLUMN} values")


def _resolve_column(mapping: Mapping[str, str], ref: str, role: str) -> str:
    local = mapping.get(ref)
    if local is None:
        raise JoinExecutionError(
            f"Join {role} column '{ref}' is not present in the registered checkpoint"
        )
    return local


def _role_for_ref(unit: JoinUnit, ref: str) -> str:
    roles = [
        item.role
        for item in unit.inputs
        if ref.startswith(f"{item.snapshot}.")
    ]
    if len(roles) != 1:
        raise JoinExecutionError(
            f"Join column '{ref}' does not resolve to exactly one input role"
        )
    return roles[0]


def _rename_frame(
    frame: pd.DataFrame,
    prefix: str,
) -> tuple[pd.DataFrame, dict[str, str]]:
    mapping: dict[str, str] = {}
    for index, column in enumerate(frame.columns):
        if not isinstance(column, str):
            raise JoinExecutionError("Join input columns must be strings")
        mapping[column] = f"{prefix}{index}"
    return frame.rename(columns=mapping), mapping


def _dtype_mismatch_details(
    unit: JoinUnit,
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
) -> list[dict[str, object]]:
    details: list[dict[str, object]] = []
    for key, left_column, right_column in zip(
        unit.keys, left_keys, right_keys, strict=True
    ):
        left_dtype = left_frame[left_column].dtype
        right_dtype = right_frame[right_column].dtype
        if not pd.api.types.is_dtype_equal(left_dtype, right_dtype):
            details.append(
                {
                    "left": key.left,
                    "right": key.right,
                    "left_dtype": str(left_dtype),
                    "right_dtype": str(right_dtype),
                }
            )
    return details


def _duplicate_key_details(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
) -> dict[str, object] | None:
    if not left_keys:
        return None
    left_duplicate_mask = left_frame.duplicated(subset=left_keys, keep=False)
    right_duplicate_mask = right_frame.duplicated(subset=right_keys, keep=False)
    left_duplicate_rows = int(left_duplicate_mask.sum())
    right_duplicate_rows = int(right_duplicate_mask.sum())
    details: dict[str, object] = {
        "left_duplicate_key_rows": left_duplicate_rows,
        "right_duplicate_key_rows": right_duplicate_rows,
        "left_duplicate_key_count": int(
            left_frame.loc[left_duplicate_mask, left_keys].drop_duplicates().shape[0]
        ),
        "right_duplicate_key_count": int(
            right_frame.loc[right_duplicate_mask, right_keys].drop_duplicates().shape[0]
        ),
        "many_to_many": False,
        "many_to_many_key_count": 0,
    }
    if not left_duplicate_rows or not right_duplicate_rows:
        return details

    key_names = [f"__di_duplicate_key_{index}" for index in range(len(left_keys))]
    left_duplicate_keys = (
        left_frame.loc[left_duplicate_mask, left_keys].drop_duplicates().copy()
    )
    right_duplicate_keys = (
        right_frame.loc[right_duplicate_mask, right_keys].drop_duplicates().copy()
    )
    left_duplicate_keys.columns = key_names
    right_duplicate_keys.columns = key_names
    try:
        matched = left_duplicate_keys.merge(
            right_duplicate_keys,
            how="inner",
            on=key_names,
            sort=False,
        )
    except (TypeError, ValueError):
        return details
    details["many_to_many_key_count"] = int(len(matched))
    details["many_to_many"] = bool(len(matched))
    return details


def _observed_cardinality(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
) -> str:
    """Classify the relationship among key values that actually match."""
    if not left_keys:
        return "cross"
    key_names = [f"__di_cardinality_key_{index}" for index in range(len(left_keys))]
    left_keys_frame = left_frame.loc[:, left_keys].copy()
    right_keys_frame = right_frame.loc[:, right_keys].copy()
    left_keys_frame.columns = key_names
    right_keys_frame.columns = key_names
    try:
        left_counts = (
            left_keys_frame.groupby(key_names, dropna=False, sort=False)
            .size()
            .reset_index(name="left_count")
        )
        right_counts = (
            right_keys_frame.groupby(key_names, dropna=False, sort=False)
            .size()
            .reset_index(name="right_count")
        )
        matched = left_counts.merge(right_counts, how="inner", on=key_names, sort=False)
    except (TypeError, ValueError):
        return "unknown"
    if matched.empty:
        return "no_matches"
    left_many = bool((matched["left_count"] > 1).any())
    right_many = bool((matched["right_count"] > 1).any())
    if left_many and right_many:
        return "many_to_many"
    if left_many:
        return "many_to_one"
    if right_many:
        return "one_to_many"
    return "one_to_one"


def _unmatched_key_details(
    left_frame: pd.DataFrame,
    right_frame: pd.DataFrame,
    left_keys: list[str],
    right_keys: list[str],
) -> dict[str, object] | None:
    if not left_keys:
        return None
    key_names = [f"__di_join_key_{index}" for index in range(len(left_keys))]
    left_key_frame = left_frame.loc[:, left_keys].copy()
    right_key_frame = right_frame.loc[:, right_keys].copy()
    left_key_frame.columns = key_names
    right_key_frame.columns = key_names
    try:
        left_matches = left_key_frame.merge(
            right_key_frame.drop_duplicates(),
            how="left",
            on=key_names,
            indicator=True,
            sort=False,
        )
        right_matches = right_key_frame.merge(
            left_key_frame.drop_duplicates(),
            how="left",
            on=key_names,
            indicator=True,
            sort=False,
        )
    except (TypeError, ValueError):
        return None

    left_unmatched = left_matches["_merge"].eq("left_only")
    right_unmatched = right_matches["_merge"].eq("left_only")
    left_rows = int(left_unmatched.sum())
    right_rows = int(right_unmatched.sum())
    if not left_rows and not right_rows:
        return None
    return {
        "left_unmatched_rows": left_rows,
        "right_unmatched_rows": right_rows,
        "left_unmatched_key_count": int(
            left_matches.loc[left_unmatched, key_names].drop_duplicates().shape[0]
        ),
        "right_unmatched_key_count": int(
            right_matches.loc[right_unmatched, key_names].drop_duplicates().shape[0]
        ),
    }


def _row_expansion_baseline(how: str, left_count: int, right_count: int) -> int:
    if how == "left":
        return left_count
    if how == "right":
        return right_count
    return max(left_count, right_count)


def _warning(
    code: str,
    message: str,
    details: dict[str, object],
) -> dict[str, object]:
    return {
        "code": code,
        "severity": "warning",
        "message": message,
        "details": details,
    }
