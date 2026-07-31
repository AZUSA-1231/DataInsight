from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, model_validator


class UnitType(str, Enum):
    TRANSFORM = "transform"
    FILTER = "filter"
    TERMINAL = "terminal"


class ExecutionMode(str, Enum):
    TEMPLATE = "template"
    LLM = "llm"


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
    """DEPRECATED: Use PlannerInstruction instead.

    Kept for backward compatibility with in-flight sessions and tests.
    Planner node falls back to AnalysisIntent when PlannerInstruction is absent.
    """

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


class UnitSuggestion(BaseModel):
    """A pre-structured analysis unit suggestion from Business Track.

    More concrete than the high-level Suggestion — specifies exact fields
    and a recommended method, bridging business intent to technical plan.
    """

    purpose: str
    model: str | None = None
    related_fields: list[str] = []
    cautious: str = ""


class PlannerInstruction(BaseModel):
    """Highly structured instruction from Business Track to Planner.

    This is the BT→Planner contract. BT has access to data columns and
    business context, so it produces concrete field assignments rather
    than vague business language. Planner's job is to validate, flesh out
    missing details, and produce executable PlanUnits.
    """

    core_question: str
    analysis_type: str  # descriptive | diagnostic | predictive | comparative | trend
    complexity: str = "moderate"  # simple | moderate | complex

    # Concrete column assignments (BT has access to unified_columns)
    target_columns: list[str] = []
    group_by: list[str] = []
    filter_hint: str | None = None

    # Pre-structured analysis units (may be empty — Planner fills gaps)
    unit_suggestions: list[UnitSuggestion] = []

    # Revision context (when workspace plan already exists)
    is_revision: bool = False
    target_unit_ids: list[int] = []
    revision_notes: str | None = None

    # General guidance
    suggestions: list[Suggestion] = []
    caution_notes: str | None = None

    # Natural-language brief — the most important field
    instruction_nl: str = ""


class PlanUnit(BaseModel):
    """A single unit of work within a Plan — Transform, Filter, or Terminal.

    Each unit specifies its type (what it produces), execution mode
    (template or LLM-generated code), DAG topology, and column contract.

    The ``model`` key is accepted as a deprecated alias for ``model_hint``
    during construction and validation.
    """

    unit_id: int
    unit_type: UnitType = UnitType.TRANSFORM
    execution_mode: ExecutionMode = ExecutionMode.LLM
    purpose: str
    model_hint: str | None = None
    cautious: str = ""
    depends_on: list[int] = []
    input_from: str | None = None
    input_columns: list[str] = []
    output_columns: list[str] = []
    related_fields: list[str] = []
    template_name: str | None = None
    template_params: dict[str, object] | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_model_alias(cls, data: object) -> object:
        """Accept ``model`` as an alias for ``model_hint``."""
        if isinstance(data, dict) and "model" in data and "model_hint" not in data:
            data = {**data, "model_hint": data["model"]}
            del data["model"]
        return data


class Plan(BaseModel):
    """Structured analysis orchestration plan.

    N analysis units. Each unit specifies its purpose, preferred model,
    cautions, related fields, and optional dependencies (DAG execution).
    """

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
    unified_columns: list[str] = []
    analysis_intent: AnalysisIntent | None = None
    planner_instruction: PlannerInstruction | None = None
    plan: Plan | None = None
    analysis_result: dict[str, Any] | None = None
    final_report: str | None = None
    error: str | None = None
    feedback: str | None = None
    dashboard_pins: list[dict[str, Any]] = []
    dialogue_history: list[dict[str, str]] = []
    persisted_at: str | None = None
