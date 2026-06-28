from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class AgentState(TypedDict):
    """Shared state flowing through the four-stage analysis pipeline.

    All nodes read from and write to this state. New dicts are returned
    rather than mutating in place (LangGraph convention).
    """

    file_path: str
    user_requirement: str
    data_report: NotRequired[str]
    business_plan: NotRequired[str]
    execution_plan: NotRequired[str]
    execution_result: NotRequired[dict[str, Any]]
    final_report: NotRequired[str]
    error: NotRequired[str]
    feedback: NotRequired[str]
