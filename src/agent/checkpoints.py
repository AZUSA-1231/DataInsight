"""Explicit checkpoint storage for the Cycle 5 execution contract."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pandas as pd

from src.agent.state import CheckpointRecord


class CheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be resolved or committed."""


def new_run_id() -> str:
    """Return a compact unique execution identifier."""
    return f"run_{uuid.uuid4().hex[:16]}"


def checkpoint_id(run_id: str, unit_id: int) -> str:
    """Build the stable checkpoint ID for one unit execution."""
    return f"cp_{run_id}_u{unit_id}"


def output_root(parent_output_dir: str | Path) -> Path:
    """Return the session output root for an analysis directory."""
    path = Path(parent_output_dir)
    return path.parent if path.name == "analysis" else path


def checkpoint_path(
    record: CheckpointRecord,
    parent_output_dir: str | Path,
) -> Path:
    """Resolve a persisted relative checkpoint path without guessing."""
    path = Path(record.path)
    if path.is_absolute():
        raise CheckpointError(
            f"Checkpoint {record.checkpoint_id} must use a relative path"
        )
    root = output_root(parent_output_dir).resolve()
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise CheckpointError(
            f"Checkpoint {record.checkpoint_id} path escapes the session output"
        ) from exc
    return resolved


def load_checkpoint(
    record: CheckpointRecord,
    parent_output_dir: str | Path,
) -> pd.DataFrame:
    """Load and minimally verify one registered checkpoint."""
    path = checkpoint_path(record, parent_output_dir)
    if not path.is_file():
        raise CheckpointError(
            f"Checkpoint {record.checkpoint_id} is missing at {record.path}"
        )
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        raise CheckpointError(
            f"Checkpoint {record.checkpoint_id} could not be read: {exc}"
        ) from exc
    if len(frame) != record.row_count:
        raise CheckpointError(
            f"Checkpoint {record.checkpoint_id} row count mismatch: "
            f"registry={record.row_count}, file={len(frame)}"
        )
    return frame


def write_checkpoint_atomically(
    frame: pd.DataFrame,
    *,
    relative_path: str,
    parent_output_dir: str | Path,
) -> Path:
    """Write a Parquet checkpoint and expose it only after read-back succeeds."""
    root = output_root(parent_output_dir).resolve()
    target = (root / relative_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise CheckpointError("Checkpoint path escapes the session output") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        frame.to_parquet(temp, index=False)
        verified = pd.read_parquet(temp)
        if len(verified) != len(frame) or list(verified.columns) != list(frame.columns):
            raise CheckpointError(
                f"Checkpoint read-back contract failed for {relative_path}"
            )
        os.replace(temp, target)
    except CheckpointError:
        temp.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp.unlink(missing_ok=True)
        raise CheckpointError(
            f"Checkpoint write failed for {relative_path}: {exc}"
        ) from exc
    return target
