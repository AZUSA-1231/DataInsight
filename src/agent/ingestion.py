"""Deterministic source normalization for Cycle 5 sessions."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd

from src.agent.lineage import (
    build_source_records,
    normalize_source_frame,
    snapshot_name_from_filename,
)
from src.agent.nodes.data_track import inspect_file
from src.agent.state import (
    CheckpointRecord,
    ColumnNode,
    DataSource,
    SnapshotRecord,
)


class SourceIngestionError(ValueError):
    """Raised when a source cannot be profiled or normalized."""


def _detect_csv_encoding(path: Path) -> str:
    """Use the same deterministic encoding order as the inspection script."""
    for encoding in ("utf-8", "utf-8-sig", "latin-1", "gbk", "gb2312", "cp1252"):
        try:
            pd.read_csv(path, encoding=encoding, nrows=1)
            return encoding
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def load_source_frame(path: Path) -> pd.DataFrame:
    """Load one supported source using deterministic pandas readers."""
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, encoding=_detect_csv_encoding(path))
    if suffix in {".xls", ".xlsx"}:
        return pd.read_excel(path)
    raise SourceIngestionError(f"Unsupported source type: {suffix}")


def _write_parquet_atomically(df: pd.DataFrame, path: Path) -> None:
    """Write a normalized source without exposing a partial Parquet file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp.parquet")
    try:
        df.to_parquet(temp_path, index=False)
        temp_path.replace(path)
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise SourceIngestionError(f"Failed to write normalized source: {exc}") from exc


def ingest_source(
    *,
    source_path: Path,
    display_name: str,
    source_id: str,
    output_root: Path,
    existing_snapshot_names: list[str],
) -> tuple[
    DataSource,
    SnapshotRecord,
    CheckpointRecord,
    dict[str, ColumnNode],
]:
    """Profile, normalize, and register one source in memory.

    The caller owns the state transaction. This function writes only the new
    normalized source file and returns records that can be committed together.
    """
    try:
        profile = inspect_file(str(source_path))
        frame = load_source_frame(source_path)
    except Exception as exc:
        if isinstance(exc, SourceIngestionError):
            raise
        raise SourceIngestionError(str(exc)) from exc

    snapshot_name = snapshot_name_from_filename(display_name, existing_snapshot_names)
    normalized = normalize_source_frame(frame, snapshot_name)
    snapshot_id = f"snap_{snapshot_name}"
    checkpoint_id = f"cp_source_{snapshot_name}"
    relative_checkpoint_path = Path("sources") / f"{snapshot_id}.parquet"
    checkpoint_path = output_root / relative_checkpoint_path

    # A normalized source is immutable for the lifetime of the Session. A
    # collision here indicates a registry bug or an already-used Snapshot name.
    if checkpoint_path.exists():
        raise SourceIngestionError(
            f"Normalized source checkpoint already exists: {checkpoint_id}"
        )
    _write_parquet_atomically(normalized, checkpoint_path)

    # Keep the profile focused on user columns; the hidden row ID is not part of
    # the inspection result and therefore never enters Planner or UI context.
    profile = profile.model_copy(update={"file_path": os.fspath(source_path)})
    return build_source_records(
        source_id=source_id,
        display_name=display_name,
        upload_path=os.fspath(source_path),
        profile=profile,
        snapshot_name=snapshot_name,
        checkpoint_id=checkpoint_id,
        checkpoint_path=relative_checkpoint_path.as_posix(),
        row_count=len(normalized),
    )
