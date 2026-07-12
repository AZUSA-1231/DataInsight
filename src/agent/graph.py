from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes.analysis import analysis_node
from src.agent.nodes.business_track import business_track_node as _bt_node_raw
from src.agent.nodes.data_track import data_track_node
from src.agent.nodes.planner import planner_node
from src.agent.nodes.report_gen import report_gen_node
from src.agent.state import AgentState


def _business_track_node(state: AgentState) -> dict[str, object]:
    """Wrapper: extract state update from business_track_node's tuple return."""
    state_update, _ = _bt_node_raw(state)
    return state_update


def _should_iterate(state: AgentState) -> Literal["business_track", "__end__"]:
    """Route back to business_track if user feedback is present (in-session iteration).

    Feedback re-enters through business_track so the feedback text is treated as
    additional dialog input and re-parsed into a Contextualized Intent alongside
    the current workspace Plan.
    """
    if state.feedback:
        return "business_track"
    return "__end__"


def build_graph() -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    """Construct the DataInsight analysis state machine.

    Flow:
                    START
                      |
                      v
                 data_track
                      |
                      v
               business_track
                      |
                      v
                   planner
                      |
                      v
                   analysis
                      |
                      v
                  report_gen
                      |
                      v
                     END
                      ^
                      |___ feedback → business_track
    """
    graph = StateGraph(AgentState)

    graph.add_node("data_track", data_track_node)
    graph.add_node("business_track", _business_track_node)
    graph.add_node("planner", planner_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("report_gen", report_gen_node)

    # Linear: START → data_track → business_track → planner → analysis → report_gen
    graph.add_edge(START, "data_track")
    graph.add_edge("data_track", "business_track")
    graph.add_edge("business_track", "planner")
    graph.add_edge("planner", "analysis")
    graph.add_edge("analysis", "report_gen")
    graph.add_conditional_edges(
        "report_gen",
        _should_iterate,
        {"business_track": "business_track", "__end__": END},
    )

    return graph.compile()
