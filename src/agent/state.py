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


class AgentState(BaseModel):
    """Shared state flowing through the analysis pipeline.

    All nodes read from and write to this state. Nodes return partial dicts
    that LangGraph merges into the model — never mutate in place.
    """

    file_path: str
    user_requirement: str
    data_profile: DataProfile | None = None
    cleaning_insights: str | None = None
    business_plan: str | None = None
    execution_plan: str | None = None
    execution_result: dict[str, Any] | None = None
    final_report: str | None = None
    error: str | None = None
    feedback: str | None = None
