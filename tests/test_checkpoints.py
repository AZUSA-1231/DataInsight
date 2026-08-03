from __future__ import annotations

import pandas as pd
import pytest

from src.agent.checkpoints import (
    CheckpointError,
    checkpoint_path,
    load_checkpoint,
    write_checkpoint_atomically,
)
from src.agent.state import CheckpointRecord


def test_checkpoint_write_is_relative_and_round_trips(tmp_path) -> None:
    frame = pd.DataFrame({"__di_row_id": ["orders:0"], "amount": [3.5]})
    analysis_dir = tmp_path / "analysis"
    write_checkpoint_atomically(
        frame,
        relative_path="analysis/checkpoints/cp_test.parquet",
        parent_output_dir=analysis_dir,
    )

    record = CheckpointRecord(
        checkpoint_id="cp_test",
        snapshot_id="snap_orders",
        run_id="run_test",
        path="analysis/checkpoints/cp_test.parquet",
        row_count=1,
        columns={},
    )
    assert checkpoint_path(record, analysis_dir).is_file()
    pd.testing.assert_frame_equal(load_checkpoint(record, analysis_dir), frame)


def test_missing_checkpoint_is_a_mechanical_error(tmp_path) -> None:
    record = CheckpointRecord(
        checkpoint_id="cp_missing",
        snapshot_id="snap_orders",
        run_id="run_test",
        path="sources/missing.parquet",
        row_count=1,
        columns={},
    )
    with pytest.raises(CheckpointError, match="is missing"):
        load_checkpoint(record, tmp_path / "analysis")


def test_checkpoint_path_escape_is_rejected(tmp_path) -> None:
    record = CheckpointRecord(
        checkpoint_id="cp_escape",
        snapshot_id="snap_orders",
        run_id="run_test",
        path="../outside.parquet",
        row_count=0,
        columns={},
    )
    with pytest.raises(CheckpointError, match="escapes"):
        checkpoint_path(record, tmp_path / "analysis")
