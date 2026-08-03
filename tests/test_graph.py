from __future__ import annotations

from unittest.mock import patch

from src.agent.graph import _should_iterate, build_graph
from src.agent.nodes.analysis import analysis_node
from src.agent.state import AgentState
from tests.test_execution_v2 import _executor, _state


def test_graph_compiles_and_exposes_current_nodes() -> None:
    graph = build_graph()
    assert graph is not None
    assert {
        "data_track",
        "business_track",
        "planner",
        "analysis",
        "report_gen",
    }.issubset(graph.nodes)


def test_graph_iteration_decision() -> None:
    assert (
        _should_iterate(
            AgentState(user_requirement="", feedback="please revise")
        )
        == "business_track"
    )
    assert _should_iterate(AgentState(user_requirement="", feedback="")) == "__end__"
    assert _should_iterate(AgentState(user_requirement="")) == "__end__"


def test_graph_v2_analysis_stage(tmp_path) -> None:
    state = _state(tmp_path).model_copy(
        update={"analysis_result": {"output_dir": str(tmp_path / "analysis")}}
    )
    with patch("src.agent.nodes.analysis._execute_unit", side_effect=_executor):
        result = analysis_node(state)
    assert result["analysis_result"]["status"] == "complete"


def test_analysis_without_plan_returns_structured_failure() -> None:
    result = analysis_node(AgentState(user_requirement="Analyze"))
    assert result["analysis_result"]["status"] == "failed"
