from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes.business_track import business_track_node
from src.agent.nodes.data_track import data_track_node
from src.agent.nodes.decision_match import decision_match_node
from src.agent.nodes.execution import execution_node
from src.agent.nodes.report_gen import report_gen_node
from src.agent.state import AgentState


def _should_retry_execution(state: AgentState) -> Literal["execution", "report_gen"]:
    if state.get("error") and state.get("execution_result", {}).get("retry_count", 0) < 3:
        return "execution"
    return "report_gen"


def _should_iterate(state: AgentState) -> Literal["decision_match", "__end__"]:
    """Route back to decision_match if user feedback is present (in-session iteration)."""
    if state.get("feedback"):
        return "decision_match"
    return "__end__"


def build_graph() -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    """Construct the four-stage DataInsight analysis state machine.

    Flow:
        START -> data_track -> business_track -> decision_match
              -> execution -> report_gen -> END
                 ^              |            ^
                 |--(on error)--/            |
                 |--(user feedback)----------/
    """
    graph: StateGraph[AgentState, Any, AgentState, AgentState] = StateGraph(AgentState)

    graph.add_node("data_track", data_track_node)
    graph.add_node("business_track", business_track_node)
    graph.add_node("decision_match", decision_match_node)
    graph.add_node("execution", execution_node)
    graph.add_node("report_gen", report_gen_node)

    graph.add_edge(START, "data_track")
    graph.add_edge("data_track", "business_track")
    graph.add_edge("business_track", "decision_match")
    graph.add_edge("decision_match", "execution")
    graph.add_conditional_edges(
        "execution",
        _should_retry_execution,
        {"execution": "execution", "report_gen": "report_gen"},
    )
    graph.add_conditional_edges(
        "report_gen",
        _should_iterate,
        {"decision_match": "decision_match", "__end__": END},
    )

    return graph.compile()
