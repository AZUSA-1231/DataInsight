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


class Suggestion(BaseModel):
    """A "perhaps consider" hint for the Planner — not a directive.

    These are recommended analytical angles derived from the business question.
    The Planner treats them as strong hints but may reject or adapt them based
    on actual data characteristics.
    """

    category: str  # "dimension" | "method" | "comparison" | "caution"
    content: str  # e.g. "按地区细分以发现地理差异"
    rationale: str  # e.g. "地区差异是销售波动的常见原因"


class AnalysisIntent(BaseModel):
    """Structured analytical intent extracted from the user's business question."""

    core_question: str
    target_variable: str | None = None
    analysis_type: str
    dimensions: list[str]
    comparison_baseline: str | None = None
    # --- Cycle 2 M3: question intelligence ---
    expanded_question: str | None = None
    complexity: str = "moderate"  # "simple" | "moderate" | "complex"
    suggestions: list[Suggestion] = []
    caution_notes: str | None = None


class PlanUnit(BaseModel):
    """A single unit of work — cleaning or analysis — within a Plan."""

    unit_id: int
    purpose: str
    model: str | None = None
    cautious: str
    depends_on: list[int] = []


class Plan(BaseModel):
    """Structured analysis orchestration plan (Cycle 2 M1).

    One fixed cleaning unit + N independent analysis units. Each unit specifies
    its purpose, preferred model, and cautions. Units are star-shaped (no chain
    dependencies) — depends_on reserved for future use.
    """

    cleaning: PlanUnit
    units: list[PlanUnit]
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
    plan: Plan | None = None
    preprocessing_result: dict[str, Any] | None = None
    analysis_result: dict[str, Any] | None = None
    final_report: str | None = None
    error: str | None = None
    feedback: str | None = None
