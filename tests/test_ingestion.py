from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.agent.ingestion import ingest_source
from src.agent.lineage import ROW_ID_COLUMN
from src.agent.state import ColumnNode


def test_ingest_source_writes_normalized_parquet(sample_csv_path: str, tmp_path: Path) -> None:
    output_root = tmp_path / "output"
    records = ingest_source(
        source_path=Path(sample_csv_path),
        display_name="orders.csv",
        source_id="src_orders",
        output_root=output_root,
        existing_snapshot_names=[],
    )
    source, snapshot, checkpoint, nodes = records

    path = output_root / checkpoint.path
    assert path.exists()
    frame = pd.read_parquet(path)
    assert ROW_ID_COLUMN in frame.columns
    assert frame[ROW_ID_COLUMN].is_unique
    assert len(frame) == source.profile.shape[0]
    assert snapshot.name == "orders"
    assert checkpoint.columns.keys() == nodes_by_ref(nodes)


def nodes_by_ref(nodes: dict[str, ColumnNode]) -> set[str]:
    return {node.ref for node in nodes.values()}
