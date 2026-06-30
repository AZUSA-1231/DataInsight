from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ColumnProfile(BaseModel):
    """Per-column metadata from deterministic inspection."""

    name: str
    dtype: str
    null_count: int
    null_pct: float
    unique_count: int
    unique_pct: float


class DataProfile(BaseModel):
    """Structured data profile from deterministic inspection script."""

    file_path: str
    shape: tuple[int, int]
    columns: list[ColumnProfile]
    statistics: dict[str, dict[str, Any]]
    head_sample: list[dict[str, Any]]
    encoding: str | None = None


class AnalysisIntent(BaseModel):
    """Structured analytical intent extracted from the user's business question."""

    core_question: str
    target_variable: str | None = None
    analysis_type: str
    dimensions: list[str]
    comparison_baseline: str | None = None


class ExecutionPlan(BaseModel):
    """Planner output: concrete analysis plan bridging data reality to business goals."""

    feasibility_map: list[dict[str, Any]]
    model_selections: list[dict[str, Any]]
    preprocessing_steps: list[dict[str, Any]]
    analysis_steps: list[dict[str, Any]]
    alignment_notes: str


class AgentState(BaseModel):
    """Shared state flowing through the analysis pipeline.

    All nodes read from and write to this state. Nodes return partial dicts
    that LangGraph merges into the model — never mutate in place.
    """

    file_path: str
    user_requirement: str
    data_profile: DataProfile | None = None
    cleaning_insights: str | None = None
    analysis_intent: AnalysisIntent | None = None
    execution_plan: ExecutionPlan | None = None
    preprocessing_result: dict[str, Any] | None = None
    execution_result: dict[str, Any] | None = None
    final_report: str | None = None
    error: str | None = None
    feedback: str | None = None
