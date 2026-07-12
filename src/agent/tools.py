from __future__ import annotations

from pydantic import BaseModel, Field


class SubmitInstructionInput(BaseModel):
    """Schema for the submit_planner_instruction tool.

    This is the BT Agent's ONLY way to hand off to the Planner. Every field
    must be populated with care — the Planner has no other channel to get
    information from the BT Agent beyond this instruction and the conversation
    history.
    """

    core_question: str = Field(
        description="The user's business question, restated precisely and completely"
    )
    analysis_type: str = Field(
        description="One of: descriptive, diagnostic, predictive, comparative, trend"
    )
    complexity: str = Field(
        default="moderate",
        description="simple, moderate, or complex",
    )
    target_columns: list[str] = Field(
        default_factory=list,
        description="EXACT column names for target/dependent variables",
    )
    group_by: list[str] = Field(
        default_factory=list,
        description="EXACT column names for grouping/segmentation dimensions",
    )
    filter_hint: str | None = Field(
        default=None,
        description="Any data filter condition, e.g. 'exclude rows where year < 2020'",
    )
    unit_suggestions: list[dict[str, object]] = Field(
        default_factory=list,
        description=(
            "Pre-structured analysis units. Each dict has: purpose (str), "
            "model (str|None), related_fields (list[str]), cautious (str)"
        ),
    )
    is_revision: bool = Field(
        default=False,
        description="Whether this instruction modifies existing workspace units",
    )
    target_unit_ids: list[int] = Field(
        default_factory=list,
        description="Which existing unit IDs are being revised (empty if not revision)",
    )
    revision_notes: str | None = Field(
        default=None,
        description="What changed and why — natural language explanation for the Planner",
    )
    suggestions: list[dict[str, object]] = Field(
        default_factory=list,
        description=(
            "Additional analytical suggestions. Each dict has: "
            "category (dimension|method|comparison|caution), content, rationale"
        ),
    )
    caution_notes: str | None = Field(
        default=None,
        description="Analytical pitfalls and risks the Planner must be aware of",
    )
    instruction_nl: str = Field(
        default="",
        description=(
            "THE MOST IMPORTANT FIELD. A thorough natural-language brief (5-10 "
            "sentences) for the Planner. Explain the user's intent, the context "
            "from your conversation, any edge cases or trade-offs discussed, why "
            "you chose specific columns and methods, what to pay attention to, "
            "and anything the user said that structured fields can't capture. "
            "Write this like a handoff email to a trusted colleague — clear, "
            "thorough, honest about uncertainties."
        ),
    )


class InspectColumnInput(BaseModel):
    """Look up detailed statistics for a specific column in the dataset.

    Returns dtype, null count, null percentage, unique count, unique
    percentage, and sample values for the requested column. Use this
    before making column-specific recommendations.
    """

    column_name: str = Field(
        description=(
            "EXACT column name to inspect (case-sensitive, "
            "use the name as it appears in the data)"
        )
    )


# ---------------------------------------------------------------------------
# OpenAI-format tool schemas for bind_tools()
# ---------------------------------------------------------------------------


def _build_tool_schema(name: str, description: str, model: type[BaseModel]) -> dict[str, object]:
    """Build an OpenAI-compatible tool schema from a Pydantic model."""
    schema = model.model_json_schema()
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }


_SUBMIT_INSTRUCTION_TOOL = _build_tool_schema(
    name="submit_planner_instruction",
    description=(
        "Submit a structured analysis instruction to the Planner agent. "
        "Call this ONLY when you are confident you fully understand what the "
        "user wants. After calling this, your analysis phase ends — the "
        "Planner takes over. The instruction_nl field is the most important "
        "part — write a thorough natural-language brief explaining the full "
        "context, the user's intent, any edge cases discussed, and why you "
        "made the choices you did."
    ),
    model=SubmitInstructionInput,
)

_INSPECT_COLUMN_TOOL = _build_tool_schema(
    name="inspect_column",
    description=(
        "Look up detailed statistics for a specific column in the dataset. "
        "Returns dtype, null count, null percentage, unique count, unique "
        "percentage, and sample values."
    ),
    model=InspectColumnInput,
)

BT_TOOLS: list[dict[str, object]] = [_SUBMIT_INSTRUCTION_TOOL, _INSPECT_COLUMN_TOOL]


# ---------------------------------------------------------------------------
# Runtime tool resolution
# ---------------------------------------------------------------------------


def resolve_inspect_column(column_name: str, data_profile: object | None = None) -> str:
    """Resolve an inspect_column tool call using the data profile from state.

    Args:
        column_name: Exact column name to look up.
        data_profile: A DataProfile instance, or None if no data is loaded.

    Returns:
        A formatted string with column statistics, or an error message.
    """
    if data_profile is None:
        return "No data uploaded yet. Please upload a CSV or Excel file first."

    from src.agent.state import DataProfile

    if not isinstance(data_profile, DataProfile):
        return "Data profile is not available."

    for col in data_profile.columns:
        if col.name == column_name:
            stats = data_profile.statistics.get(column_name, {})
            sample_values: list[object] = []
            for row in data_profile.head_sample:
                if column_name in row:
                    sample_values.append(row[column_name])
            samples_str = ", ".join(repr(v) for v in sample_values[:5])

            return (
                f"Column: {col.name}\n"
                f"  dtype: {col.dtype}\n"
                f"  null_count: {col.null_count} ({col.null_pct:.1f}%)\n"
                f"  unique_count: {col.unique_count} ({col.unique_pct:.1f}%)\n"
                f"  statistics: {stats or '(none)'}\n"
                f"  sample values: [{samples_str}]"
            )

    available = [c.name for c in data_profile.columns]
    return f"Column '{column_name}' not found. Available columns: {available}"
