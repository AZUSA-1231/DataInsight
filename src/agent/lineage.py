"""Pure helpers for Cycle 5 source identity and initial lineage records."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from pathlib import Path

import pandas as pd

from src.agent.state import (
    CheckpointRecord,
    ColumnGraph,
    ColumnNode,
    DataProfile,
    DataSource,
    SnapshotRecord,
)

ROW_ID_COLUMN = "__di_row_id"


def resolve_local_columns(
    checkpoint: CheckpointRecord,
    column_graph: ColumnGraph,
    refs: Iterable[str],
) -> dict[str, str]:
    """Resolve exact qualified refs to physical DataFrame column names."""
    resolved: dict[str, str] = {}
    for ref in refs:
        node_id = checkpoint.columns.get(ref)
        if node_id is None:
            raise KeyError(
                f"Qualified column '{ref}' is not present in checkpoint "
                f"'{checkpoint.checkpoint_id}'"
            )
        node = column_graph.nodes.get(node_id)
        if node is None:
            raise KeyError(
                f"Checkpoint column '{ref}' points to missing node '{node_id}'"
            )
        resolved[ref] = node.name
    return resolved


def inherited_column_node(
    *,
    node_id: str,
    ref: str,
    name: str,
    snapshot: str,
    dtype: str,
    row_count: int,
    parent: ColumnNode,
    created_by_unit_id: int,
) -> ColumnNode:
    """Create a new node for a Filter-inherited column."""
    return ColumnNode(
        node_id=node_id,
        ref=ref,
        name=name,
        snapshot=snapshot,
        dtype=dtype,
        row_count=row_count,
        source_table=parent.source_table,
        source_column=parent.source_column,
        origin_columns=list(parent.origin_columns),
        created_by_unit_id=created_by_unit_id,
        derived_from_node_ids=[parent.node_id],
    )


def joined_column_node(
    *,
    node_id: str,
    ref: str,
    name: str,
    snapshot: str,
    dtype: str,
    row_count: int,
    parent: ColumnNode,
    created_by_unit_id: int,
) -> ColumnNode:
    """Create a Join output node with direct source provenance."""
    return ColumnNode(
        node_id=node_id,
        ref=ref,
        name=name,
        snapshot=snapshot,
        dtype=dtype,
        row_count=row_count,
        source_table=parent.source_table,
        source_column=parent.source_column,
        origin_columns=list(parent.origin_columns),
        created_by_unit_id=created_by_unit_id,
        derived_from_node_ids=[parent.node_id],
    )


def derived_column_node(
    *,
    node_id: str,
    ref: str,
    name: str,
    snapshot: str,
    dtype: str,
    row_count: int,
    parents: Mapping[str, ColumnNode],
    created_by_unit_id: int,
) -> ColumnNode:
    """Create a node for a Derive output and preserve root origins."""
    origins: list[str] = []
    parent_ids: list[str] = []
    for parent in parents.values():
        parent_ids.append(parent.node_id)
        for origin in parent.origin_columns:
            if origin not in origins:
                origins.append(origin)
    return ColumnNode(
        node_id=node_id,
        ref=ref,
        name=name,
        snapshot=snapshot,
        dtype=dtype,
        row_count=row_count,
        origin_columns=origins,
        created_by_unit_id=created_by_unit_id,
        derived_from_node_ids=parent_ids,
    )


def snapshot_name_from_filename(
    filename: str,
    existing_names: Iterable[str] = (),
) -> str:
    """Return a stable ASCII identifier derived from a source filename."""
    stem = Path(filename).stem
    normalized = unicodedata.normalize("NFKD", stem)
    ascii_stem = normalized.encode("ascii", "ignore").decode("ascii")
    candidate = re.sub(r"[^A-Za-z0-9_-]+", "_", ascii_stem).strip("_-").lower()
    candidate = candidate or "source"

    used = {name.lower() for name in existing_names}
    if candidate not in used:
        return candidate

    suffix = 2
    while f"{candidate}_{suffix}" in used:
        suffix += 1
    return f"{candidate}_{suffix}"


def normalize_source_frame(df: pd.DataFrame, snapshot_name: str) -> pd.DataFrame:
    """Add a hidden stable row identifier to a source frame."""
    if ROW_ID_COLUMN in df.columns:
        raise ValueError(f"'{ROW_ID_COLUMN}' is reserved by DataInsight")

    normalized = df.reset_index(drop=True).copy()
    row_ids = [f"{snapshot_name}:{index}" for index in range(len(normalized))]
    normalized.insert(0, ROW_ID_COLUMN, row_ids)
    return normalized


def build_source_records(
    *,
    source_id: str,
    display_name: str,
    upload_path: str,
    profile: DataProfile,
    snapshot_name: str,
    checkpoint_id: str,
    checkpoint_path: str,
    row_count: int,
) -> tuple[DataSource, SnapshotRecord, CheckpointRecord, dict[str, ColumnNode]]:
    """Build the durable source, Snapshot, checkpoint, and raw column records."""
    snapshot_id = f"snap_{snapshot_name}"
    column_map: dict[str, str] = {}
    nodes: dict[str, ColumnNode] = {}

    for index, column in enumerate(profile.columns):
        ref = f"{snapshot_name}.{column.name}"
        node_id = f"coln_{snapshot_name}_{index}"
        column_map[ref] = node_id
        nodes[node_id] = ColumnNode(
            node_id=node_id,
            ref=ref,
            name=column.name,
            snapshot=snapshot_name,
            dtype=column.dtype,
            row_count=row_count,
            source_table=snapshot_name,
            source_column=column.name,
            origin_columns=[ref],
        )

    source = DataSource(
        source_id=source_id,
        display_name=display_name,
        upload_path=upload_path,
        snapshot_id=snapshot_id,
        source_checkpoint_id=checkpoint_id,
        profile=profile,
    )
    snapshot = SnapshotRecord(
        snapshot_id=snapshot_id,
        name=snapshot_name,
        display_name=display_name,
        current_checkpoint_id=checkpoint_id,
    )
    checkpoint = CheckpointRecord(
        checkpoint_id=checkpoint_id,
        snapshot_id=snapshot_id,
        parent_checkpoint_ids=[],
        producer_unit_id=None,
        run_id="ingest",
        path=checkpoint_path,
        row_count=row_count,
        columns=column_map,
    )
    return source, snapshot, checkpoint, nodes
