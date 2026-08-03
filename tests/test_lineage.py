from __future__ import annotations

import pandas as pd

from src.agent.lineage import (
    ROW_ID_COLUMN,
    build_source_records,
    normalize_source_frame,
    snapshot_name_from_filename,
)
from src.agent.state import ColumnProfile, DataProfile


def _profile() -> DataProfile:
    return DataProfile(
        file_path="orders.csv",
        shape=(2, 2),
        columns=[
            ColumnProfile(
                name="order_id",
                dtype="int64",
                null_count=0,
                null_pct=0.0,
                unique_count=2,
                unique_pct=100.0,
            ),
            ColumnProfile(
                name="amount",
                dtype="float64",
                null_count=0,
                null_pct=0.0,
                unique_count=2,
                unique_pct=100.0,
            ),
        ],
        statistics={},
        head_sample=[],
    )


def test_snapshot_name_is_ascii_and_collision_safe() -> None:
    assert snapshot_name_from_filename("Orders 2025.csv") == "orders_2025"
    assert snapshot_name_from_filename("订单.csv") == "source"
    assert snapshot_name_from_filename("orders.csv", ["orders"]) == "orders_2"
    assert snapshot_name_from_filename("orders.csv", ["orders", "orders_2"]) == "orders_3"


def test_normalize_source_frame_adds_stable_hidden_row_ids() -> None:
    frame = pd.DataFrame({"order_id": [10, 11], "amount": [2.5, 3.0]})
    normalized = normalize_source_frame(frame, "orders")

    assert list(normalized.columns) == [ROW_ID_COLUMN, "order_id", "amount"]
    assert normalized[ROW_ID_COLUMN].tolist() == ["orders:0", "orders:1"]
    assert frame.index.tolist() == [0, 1]


def test_normalize_source_frame_rejects_reserved_column() -> None:
    frame = pd.DataFrame({ROW_ID_COLUMN: ["existing"]})

    try:
        normalize_source_frame(frame, "orders")
    except ValueError as exc:
        assert ROW_ID_COLUMN in str(exc)
    else:
        raise AssertionError("reserved row ID column should be rejected")


def test_build_source_records_creates_raw_column_lineage() -> None:
    source, snapshot, checkpoint, nodes = build_source_records(
        source_id="src_1",
        display_name="orders.csv",
        upload_path="data/uploads/session/orders.csv",
        profile=_profile(),
        snapshot_name="orders",
        checkpoint_id="cp_source_orders",
        checkpoint_path="sources/snap_orders.parquet",
        row_count=2,
    )

    assert source.snapshot_id == "snap_orders"
    assert snapshot.current_checkpoint_id == checkpoint.checkpoint_id
    assert checkpoint.columns == {
        "orders.order_id": "coln_orders_0",
        "orders.amount": "coln_orders_1",
    }
    assert nodes["coln_orders_0"].source_column == "order_id"
    assert nodes["coln_orders_0"].origin_columns == ["orders.order_id"]
