from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from src.agent.nodes.analysis import analysis_node
from src.agent.nodes.business_track import business_track_node
from src.agent.nodes.data_track import data_track_node
from src.agent.nodes.planner import planner_node
from src.agent.nodes.preprocessing import preprocessing_node
from src.agent.nodes.report_gen import report_gen_node
from src.agent.state import AgentState


def _should_skip_business_track(
    state: AgentState,
) -> Literal["planner", "business_track"]:
    """Skip business_track and go directly to planner when draft_plan is provided (review mode)."""
    if state.draft_plan is not None:
        return "planner"
    return "business_track"


def _should_retry_preprocessing(
    state: AgentState,
) -> Literal["preprocessing", "analysis", "report_gen"]:
    retry_count = (state.preprocessing_result or {}).get("retry_count", 0)
    if state.error and retry_count < 3:
        return "preprocessing"
    if state.error and retry_count >= 3:
        return "report_gen"
    return "analysis"


def _should_iterate(state: AgentState) -> Literal["planner", "__end__"]:
    """Route back to planner if user feedback is present (in-session iteration)."""
    if state.feedback:
        return "planner"
    return "__end__"


def build_graph() -> CompiledStateGraph[AgentState, Any, AgentState, AgentState]:
    """Construct the DataInsight analysis state machine.

    Flow:
                    START
                      |
                      v
                 data_track
                   /      \\
         (draft_plan)  (no draft_plan)
              /              \\
             v                v
          planner        business_track
                            |
                            v
                          planner
                            |
                            v
                      preprocessing
                        /      \\
               (success)    (error → ReAct × 3)
                      /          \\
                     v            v
                 analysis      report_gen (partial)
                     |
                     v
                report_gen
                     |
                     v
                    END
                     ^
                     |___ feedback → planner
    """
    graph = StateGraph(AgentState)

    graph.add_node("data_track", data_track_node)
    graph.add_node("business_track", business_track_node)
    graph.add_node("planner", planner_node)
    graph.add_node("preprocessing", preprocessing_node)
    graph.add_node("analysis", analysis_node)
    graph.add_node("report_gen", report_gen_node)

    # Serial: START → data_track first, then conditionally route through business_track
    graph.add_edge(START, "data_track")
    graph.add_conditional_edges(
        "data_track",
        _should_skip_business_track,
        {
            "planner": "planner",
            "business_track": "business_track",
        },
    )
    graph.add_edge("business_track", "planner")

    # Planner → Preprocessing (with ReAct retry, fallback to report_gen)
    graph.add_edge("planner", "preprocessing")
    graph.add_conditional_edges(
        "preprocessing",
        _should_retry_preprocessing,
        {
            "preprocessing": "preprocessing",
            "analysis": "analysis",
            "report_gen": "report_gen",
        },
    )

    # Analysis → Report Gen (per-unit ReAct retry handled internally)
    graph.add_edge("analysis", "report_gen")
    graph.add_conditional_edges(
        "report_gen",
        _should_iterate,
        {"planner": "planner", "__end__": END},
    )

    return graph.compile()
