from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes.analysis import analysis_node
from src.agent.nodes.business_track import business_track_node
from src.agent.nodes.data_track import data_track_node
from src.agent.nodes.decision_match import decision_match_node
from src.agent.nodes.preprocessing import preprocessing_node
from src.agent.nodes.report_gen import report_gen_node
from src.agent.state import AgentState


def _should_retry_preprocessing(
    state: AgentState,
) -> Literal["preprocessing", "analysis", "report_gen"]:
    retry_count = (state.preprocessing_result or {}).get("retry_count", 0)
    if state.error and retry_count < 3:
        return "preprocessing"
    if state.error and retry_count >= 3:
        return "report_gen"
    return "analysis"


def _should_retry_analysis(state: AgentState) -> Literal["analysis", "report_gen"]:
    retry_count = (state.analysis_result or {}).get("retry_count", 0)
    if state.error and retry_count < 3:
        return "analysis"
    return "report_gen"


def _should_iterate(state: AgentState) -> Literal["decision_match", "__end__"]:
    """Route back to decision_match if user feedback is present (in-session iteration)."""
    if state.feedback:
        return "decision_match"
    return "__end__"


def build_graph() -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    """Construct the DataInsight analysis state machine.

    Flow:
                    START
                   /      \\
                  v        v
          data_track    business_track
                  \\      /
                   v    v
              decision_match
                   |
                   v
              preprocessing
                /      \\
       (success)    (error → ReAct × 3)
              /          \\
             v            v
         analysis      report_gen (partial)
           /   \\
   (success)  (error → ReAct × 3)
         /       \\
        v         v
   report_gen   report_gen (partial)
        |
        v
       END
        ^
        |___ feedback → decision_match
    """
    graph = StateGraph(AgentState)

    graph.add_node("data_track", data_track_node)
    graph.add_node("business_track", business_track_node)
    graph.add_node("decision_match", decision_match_node)
    graph.add_node("preprocessing", preprocessing_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("report_gen", report_gen_node)

    # Parallel fan-out from START to both tracks
    graph.add_edge(START, "data_track")
    graph.add_edge(START, "business_track")
    # Fan-in: both tracks converge at decision_match
    graph.add_edge("data_track", "decision_match")
    graph.add_edge("business_track", "decision_match")

    # Decision Match → Preprocessing (with ReAct retry, fallback to report_gen)
    graph.add_edge("decision_match", "preprocessing")
    graph.add_conditional_edges(
        "preprocessing",
        _should_retry_preprocessing,
        {
            "preprocessing": "preprocessing",
            "analysis": "analysis",
            "report_gen": "report_gen",
        },
    )

    # Analysis → Report Gen (with ReAct retry, fallback to report_gen)
    graph.add_conditional_edges(
        "analysis",
        _should_retry_analysis,
        {"analysis": "analysis", "report_gen": "report_gen"},
    )
    graph.add_conditional_edges(
        "report_gen",
        _should_iterate,
        {"decision_match": "decision_match", "__end__": END},
    )

    return graph.compile()
