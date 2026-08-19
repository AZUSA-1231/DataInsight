"""Fresh, JSON-safe context projection for the Cycle 6 Copilot.

The Copilot receives a deliberately whitelisted view of ``AgentState``.  This
module does not serialize the state wholesale: durable/runtime details such as
paths, checkpoint IDs, Column Graph node IDs, hidden row IDs, and executor
objects must stay outside the model context.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from enum import Enum
from pathlib import Path
from typing import cast

from pydantic import BaseModel

from src.agent.state import (
    AgentChatMessage,
    AgentState,
    ColumnNode,
    DataSource,
    SnapshotRecord,
)

_MAX_HISTORY_MESSAGES = 10
_MAX_MESSAGE_CHARS = 4000
_MAX_REPORT_CHARS = 12000
_MAX_SAMPLE_VALUES = 5
_HIDDEN_ROW_ID = "__di_row_id"

_PRIVATE_KEYS = frozenset(
    {
        "file_path",
        "upload_path",
        "path",
        "output_dir",
        "source_id",
        "snapshot_id",
        "source_checkpoint_id",
        "checkpoint_id",
        "parent_checkpoint_ids",
        "run_id",
        "node_id",
        "derived_from_node_ids",
        "input_checkpoint_ids",
        "output_checkpoint_id",
    }
)
_WINDOWS_ABSOLUTE_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\|//)")


def _is_private_key(key: str) -> bool:
    return key.startswith("_") or key in _PRIVATE_KEYS


def _is_hidden_ref(value: str) -> bool:
    return value == _HIDDEN_ROW_ID or value.endswith(f".{_HIDDEN_ROW_ID}")


def _json_safe(value: object) -> object:
    """Convert a value to a bounded JSON-safe representation.

    The explicit context builders below already avoid runtime objects.  This
    helper is an additional guard for statistics, template parameters, and
    persisted result metadata whose value types may come from pandas/numpy.
    """

    if value is None or isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        if _is_hidden_ref(value):
            return "[hidden value omitted]"
        if _WINDOWS_ABSOLUTE_PATH.match(value) or value.startswith("/"):
            return "[path omitted]"
        return value
    if isinstance(value, Path):
        return "[path omitted]"
    if isinstance(value, Enum):
        return _json_safe(value.value)
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="python"))
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for raw_key, raw_item in value.items():
            key = str(raw_key)
            if _is_private_key(key):
                continue
            result[key] = _json_safe(raw_item)
        return result
    if isinstance(value, list | tuple | set | frozenset):
        return [_json_safe(item) for item in value]

    item_method = getattr(value, "item", None)
    if callable(item_method):
        try:
            return _json_safe(item_method())
        except Exception:  # pragma: no cover - defensive boundary for odd scalars
            pass

    return "[unsupported value omitted]"


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "\n[truncated]"


def _snapshot_name_map(state: AgentState) -> dict[str, str]:
    return {
        snapshot_id: snapshot.name
        for snapshot_id, snapshot in state.snapshot_registry.items()
    }


def _source_map(state: AgentState) -> dict[str, DataSource]:
    return {source.snapshot_id: source for source in state.data_sources}


def _current_columns(
    state: AgentState,
) -> list[tuple[SnapshotRecord, str, ColumnNode | None]]:
    """Return visible current-head columns without exposing internal IDs."""

    columns: list[tuple[SnapshotRecord, str, ColumnNode | None]] = []
    for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        if checkpoint is None:
            continue
        for ref, node_id in checkpoint.columns.items():
            if _is_hidden_ref(ref):
                continue
            columns.append((snapshot, ref, state.column_graph.nodes.get(node_id)))
    return columns


def _profile_column(
    column: object,
    statistics: Mapping[str, object],
    sample_values: list[object],
) -> dict[str, object]:
    name = str(getattr(column, "name", ""))
    return {
        "name": name,
        "dtype": str(getattr(column, "dtype", "unknown")),
        "null_count": int(getattr(column, "null_count", 0)),
        "null_pct": float(getattr(column, "null_pct", 0.0)),
        "unique_count": int(getattr(column, "unique_count", 0)),
        "unique_pct": float(getattr(column, "unique_pct", 0.0)),
        "statistics": cast(dict[str, object], _json_safe(statistics)),
        "sample_values": [_json_safe(value) for value in sample_values[:_MAX_SAMPLE_VALUES]],
    }


def _project_sources(state: AgentState) -> list[dict[str, object]]:
    sources: list[dict[str, object]] = []
    snapshot_names = _snapshot_name_map(state)

    for source in sorted(state.data_sources, key=lambda item: item.display_name):
        profile = source.profile
        visible_columns = [
            column for column in profile.columns if not _is_hidden_ref(column.name)
        ]
        legacy_sample_by_name: dict[str, list[object]] = {
            column.name: [] for column in visible_columns
        }
        for row in profile.head_sample:
            for name in legacy_sample_by_name:
                if name in row:
                    legacy_sample_by_name[name].append(row[name])
        sources.append(
            {
                "display_name": source.display_name,
                "snapshot": snapshot_names.get(source.snapshot_id, ""),
                "shape": list(profile.shape),
                "columns": [
                    _profile_column(
                        column,
                        profile.statistics.get(column.name, {}),
                        legacy_sample_by_name[column.name],
                    )
                    for column in visible_columns
                ],
            }
        )

    if not sources and state.data_profile is not None:
        profile = state.data_profile
        visible_columns = [
            column for column in profile.columns if not _is_hidden_ref(column.name)
        ]
        sample_by_name: dict[str, list[object]] = {
            column.name: [] for column in visible_columns
        }
        for row in profile.head_sample:
            for name in sample_by_name:
                if name in row:
                    sample_by_name[name].append(row[name])
        sources.append(
            {
                "display_name": "uploaded data",
                "snapshot": "",
                "shape": list(profile.shape),
                "columns": [
                    _profile_column(
                        column,
                        profile.statistics.get(column.name, {}),
                        sample_by_name[column.name],
                    )
                    for column in visible_columns
                ],
            }
        )

    return sources


def _project_snapshots(state: AgentState) -> list[dict[str, object]]:
    snapshot_names = _snapshot_name_map(state)
    snapshots: list[dict[str, object]] = []
    for snapshot in sorted(state.snapshot_registry.values(), key=lambda item: item.name):
        checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
        snapshots.append(
            {
                "name": snapshot.name,
                "display_name": snapshot.display_name,
                "row_count": checkpoint.row_count if checkpoint is not None else None,
                "columns": (
                    [
                        ref
                        for ref in checkpoint.columns
                        if not _is_hidden_ref(ref)
                    ]
                    if checkpoint is not None
                    else []
                ),
                "parents": [
                    snapshot_names.get(parent_id, "")
                    for parent_id in snapshot.parent_snapshot_ids
                    if parent_id in snapshot_names
                ],
                "created_by_unit_id": snapshot.created_by_unit_id,
            }
        )
    return snapshots


def _project_columns_and_lineage(
    state: AgentState,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    columns: list[dict[str, object]] = []
    lineage: list[dict[str, object]] = []
    source_by_snapshot = _source_map(state)

    for snapshot, ref, node in _current_columns(state):
        source = source_by_snapshot.get(snapshot.snapshot_id)
        source_column = node.source_column if node is not None else None
        profile_column = None
        if source is not None and source_column:
            profile_column = next(
                (item for item in source.profile.columns if item.name == source_column),
                None,
            )
        column_info: dict[str, object] = {
            "ref": ref,
            "snapshot": snapshot.name,
            "name": node.name if node is not None else ref.rsplit(".", 1)[-1],
            "dtype": node.dtype if node is not None else "unknown",
        }
        if profile_column is not None:
            column_info.update(
                {
                    "null_count": profile_column.null_count,
                    "null_pct": profile_column.null_pct,
                    "unique_count": profile_column.unique_count,
                    "unique_pct": profile_column.unique_pct,
                }
            )
        columns.append(column_info)

        parent_refs: list[str] = []
        if node is not None:
            parent_refs = [
                state.column_graph.nodes[parent_id].ref
                for parent_id in node.derived_from_node_ids
                if parent_id in state.column_graph.nodes
                and not _is_hidden_ref(state.column_graph.nodes[parent_id].ref)
            ]
        lineage.append(
            {
                "ref": ref,
                "snapshot": snapshot.name,
                "source_column": (
                    source_column if source_column and not _is_hidden_ref(source_column) else None
                ),
                "origin_refs": (
                    [
                        origin
                        for origin in node.origin_columns
                        if not _is_hidden_ref(origin)
                    ]
                    if node is not None
                    else []
                ),
                "derived_from": parent_refs,
                "created_by_unit_id": node.created_by_unit_id if node is not None else None,
            }
        )

    if not columns and state.unified_columns:
        columns = [
            {"ref": ref, "name": ref, "dtype": "unknown"}
            for ref in state.unified_columns
            if not _is_hidden_ref(ref)
        ]

    return columns, lineage


def _project_plan(state: AgentState) -> dict[str, object] | None:
    if state.plan is None:
        return None
    return cast(
        dict[str, object],
        _json_safe(
            {
                "units": [unit.model_dump(mode="json", by_alias=True) for unit in state.plan.units],
                "alignment_notes": state.plan.alignment_notes,
            }
        ),
    )


def _project_execution(state: AgentState) -> dict[str, object]:
    raw = state.analysis_result
    if not isinstance(raw, dict):
        return {}

    projection: dict[str, object] = {"status": str(raw.get("status", "idle"))}
    stale_ids = raw.get("stale_unit_ids")
    if isinstance(stale_ids, list):
        projection["stale_unit_ids"] = [int(item) for item in stale_ids if isinstance(item, int)]

    units: list[dict[str, object]] = []
    raw_units = raw.get("unit_results", [])
    if isinstance(raw_units, list):
        for raw_unit in raw_units:
            if not isinstance(raw_unit, dict):
                continue
            unit: dict[str, object] = {}
            for key in (
                "unit_id",
                "status",
                "error",
                "insights",
                "statistics",
                "warnings",
                "stale",
                "row_count_before",
                "row_count_after",
                "row_count_delta",
            ):
                if key in raw_unit:
                    unit[key] = _json_safe(raw_unit[key])
            charts = raw_unit.get("charts")
            if isinstance(charts, list):
                unit["chart_count"] = len(charts)
            units.append(unit)
    projection["unit_results"] = units
    return cast(dict[str, object], _json_safe(projection))


def build_workspace_context(state: AgentState) -> dict[str, object]:
    """Build the whitelisted workspace projection for one Copilot request."""

    columns, lineage = _project_columns_and_lineage(state)
    report = state.final_report or ""
    return {
        "sources": _project_sources(state),
        "snapshots": _project_snapshots(state),
        "qualified_columns": columns,
        "plan": _project_plan(state),
        "execution": _project_execution(state),
        "lineage": lineage,
        "report": _truncate(report, _MAX_REPORT_CHARS) if report else None,
    }


def _project_history(history: Sequence[object]) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for turn in history[-_MAX_HISTORY_MESSAGES:]:
        role: str | None
        content: str | None
        if isinstance(turn, AgentChatMessage):
            role = turn.role
            content = turn.content
        elif isinstance(turn, Mapping):
            raw_role = turn.get("role")
            raw_content = turn.get("content")
            role = raw_role if isinstance(raw_role, str) else None
            content = raw_content if isinstance(raw_content, str) else None
        else:
            continue
        if role not in {"user", "assistant"} or not content:
            continue
        projected.append(
            {
                "role": role,
                "content": _truncate(str(content), _MAX_MESSAGE_CHARS),
            }
        )
    return projected


def build_copilot_context(
    state: AgentState,
    current_request: str,
    *,
    conversation: Sequence[object] | None = None,
) -> dict[str, object]:
    """Build the complete JSON context sent for a single Copilot turn."""

    return {
        "conversation": _project_history(
            state.dialogue_history if conversation is None else conversation
        ),
        "workspace": build_workspace_context(state),
        "current_request": current_request,
    }
