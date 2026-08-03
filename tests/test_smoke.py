from __future__ import annotations

from unittest.mock import patch

from src.agent.dag import execute_dag
from tests.test_execution_v2 import _executor, _state


def test_v2_execution_smoke(tmp_path) -> None:
    state = _state(tmp_path)
    result = execute_dag(state, str(tmp_path / "analysis"), {}, _executor)
    assert result["status"] == "complete"
    assert result["unit_results"][-1]["status"] == "success"


def test_v2_analysis_node_smoke(tmp_path) -> None:
    state = _state(tmp_path).model_copy(
        update={"analysis_result": {"output_dir": str(tmp_path / "analysis")}}
    )
    with patch("src.agent.nodes.analysis._execute_unit", side_effect=_executor):
        from src.agent.nodes.analysis import analysis_node

        result = analysis_node(state)
    assert result["analysis_result"]["status"] == "complete"
