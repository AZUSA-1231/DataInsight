from __future__ import annotations

import json

import pytest

from src.agent.nodes.data_track import _parse_data_profile, data_track_node
from src.agent.state import AgentState, ColumnProfile, DataProfile


def _make_minimal_profile() -> DataProfile:
    return DataProfile(
        file_path="/tmp/test.csv",
        shape=(10, 3),
        columns=[
            ColumnProfile(
                name="sales",
                dtype="float64",
                null_count=2,
                null_pct=20.0,
                unique_count=8,
                unique_pct=80.0,
            ),
            ColumnProfile(
                name="region",
                dtype="object",
                null_count=3,
                null_pct=30.0,
                unique_count=3,
                unique_pct=30.0,
            ),
        ],
        statistics={},
        head_sample=[{"sales": 100, "region": "East"}],
    )


@pytest.mark.unit
def test_parse_data_profile() -> None:
    inspection = json.dumps(
        {
            "file_path": "/tmp/data.csv",
            "shape": {"rows": 50, "cols": 2},
            "columns": [
                {
                    "name": "col_a",
                    "dtype": "int64",
                    "null_count": 0,
                    "null_pct": 0.0,
                    "unique_count": 50,
                    "unique_pct": 100.0,
                },
                {
                    "name": "col_b",
                    "dtype": "object",
                    "null_count": 5,
                    "null_pct": 10.0,
                    "unique_count": 10,
                    "unique_pct": 20.0,
                },
            ],
            "statistics": {"col_a": {"mean": 42}},
            "head": [{"col_a": 1, "col_b": "x"}],
            "encoding": "utf-8",
        }
    )

    profile = _parse_data_profile(inspection)

    assert profile.file_path == "/tmp/data.csv"
    assert profile.shape == (50, 2)
    assert len(profile.columns) == 2
    assert profile.columns[0].name == "col_a"
    assert profile.columns[0].dtype == "int64"
    assert profile.columns[0].null_count == 0
    assert profile.columns[1].null_pct == 10.0
    assert profile.encoding == "utf-8"
    assert profile.statistics == {"col_a": {"mean": 42}}
    assert profile.head_sample == [{"col_a": 1, "col_b": "x"}]


@pytest.mark.unit
def test_data_track_node_success(sample_csv_path: str, set_llm_env: None) -> None:
    _ = set_llm_env  # fixture side effect

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Analyze sales trend",
    )

    new_state = data_track_node(state)

    assert "data_profile" in new_state
    assert "unified_columns" in new_state
    assert "error" not in new_state
    assert isinstance(new_state["data_profile"], DataProfile)
    assert new_state["data_profile"].shape[0] == 5  # 5 rows in sample CSV
    assert "name" in new_state["unified_columns"]  # CSV columns
    assert "age" in new_state["unified_columns"]
    assert "salary" in new_state["unified_columns"]
    assert "dept" in new_state["unified_columns"]
    assert "hire_date" in new_state["unified_columns"]
    # No longer calls LLM — cleaning_insights should NOT be in result
    assert "cleaning_insights" not in new_state


@pytest.mark.unit
def test_data_track_node_inspection_failure() -> None:
    state = AgentState(
        file_path="/nonexistent/file.csv",
        user_requirement="anything",
    )

    new_state = data_track_node(state)

    assert "error" in new_state
    assert new_state["error"] is not None
    assert "data_profile" not in new_state
    assert "unified_columns" not in new_state


@pytest.mark.unit
def test_data_track_node_preserves_state(sample_csv_path: str, set_llm_env: None) -> None:
    _ = set_llm_env

    state = AgentState(
        file_path=sample_csv_path,
        user_requirement="Why did sales drop?",
    )

    new_state = data_track_node(state)

    assert "unified_columns" in new_state
    assert isinstance(new_state["data_profile"], DataProfile)
    assert len(new_state["unified_columns"]) == 5
    assert "cleaning_insights" not in new_state
