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
        description=(
            "EXACT qualified Snapshot refs for target/dependent variables, "
            "such as orders.amount"
        ),
    )
    group_by: list[str] = Field(
        default_factory=list,
        description=(
            "EXACT qualified Snapshot refs for grouping dimensions, such as "
            "orders.region"
        ),
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
    """Look up detailed statistics for an exact qualified column reference.

    Returns dtype, null count, null percentage, unique count, unique
    percentage, and sample values for the requested column. Use this
    before making column-specific recommendations.
    """

    column_name: str = Field(
        description=(
            "EXACT qualified reference to inspect (case-sensitive, for example "
            "orders.amount). Use the Snapshot registry spelling."
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
        "Look up detailed statistics for an exact qualified Snapshot column "
        "reference. Returns dtype, null count, unique count, and samples when "
        "the source profile contains them."
    ),
    model=InspectColumnInput,
)

BT_TOOLS: list[dict[str, object]] = [_SUBMIT_INSTRUCTION_TOOL, _INSPECT_COLUMN_TOOL]


# ---------------------------------------------------------------------------
# Runtime tool resolution
# ---------------------------------------------------------------------------


def resolve_inspect_column(column_name: str, data_profile: object | None = None) -> str:
    """Resolve an inspect call against a v2 registry or legacy profile."""
    from src.agent.state import AgentState, DataProfile

    if isinstance(data_profile, AgentState):
        state = data_profile
        for snapshot in state.snapshot_registry.values():
            checkpoint = state.checkpoint_registry.get(snapshot.current_checkpoint_id)
            if checkpoint is None or column_name not in checkpoint.columns:
                continue

            node_id = checkpoint.columns[column_name]
            node = state.column_graph.nodes.get(node_id)
            if node is None:
                return f"Column '{column_name}' is registered without a graph node."

            source = next(
                (
                    source
                    for source in state.data_sources
                    if source.snapshot_id == snapshot.snapshot_id
                ),
                None,
            )
            profile = None
            if source is not None:
                profile = next(
                    (item for item in source.profile.columns if item.name == node.name),
                    None,
                )
            stats = source.profile.statistics.get(node.name, {}) if source else {}
            sample_values: list[object] = []
            if source is not None:
                for row in source.profile.head_sample:
                    if node.name in row:
                        sample_values.append(row[node.name])
            samples_str = ", ".join(repr(value) for value in sample_values[:5])
            profile_text = (
                f"  null_count: {profile.null_count} ({profile.null_pct:.1f}%)\n"
                f"  unique_count: {profile.unique_count} ({profile.unique_pct:.1f}%)\n"
                if profile is not None
                else "  profile: (not available for this derived column)\n"
            )
            return (
                f"Column: {column_name}\n"
                f"  snapshot: {snapshot.name}\n"
                f"  dtype: {node.dtype}\n"
                f"  row_count: {node.row_count}\n"
                f"{profile_text}"
                f"  statistics: {stats or '(none)'}\n"
                f"  sample values: [{samples_str}]"
            )

        available = sorted(
            ref
            for snapshot in state.snapshot_registry.values()
            if (checkpoint := state.checkpoint_registry.get(snapshot.current_checkpoint_id))
            for ref in checkpoint.columns
        )
        return f"Column '{column_name}' not found. Available qualified columns: {available}"

    if data_profile is None:
        return "No data uploaded yet. Please upload a CSV or Excel file first."

    if not isinstance(data_profile, DataProfile):
        return "Data profile is not available."

    for col in data_profile.columns:
        if col.name == column_name:
            stats = data_profile.statistics.get(column_name, {})
            legacy_sample_values: list[object] = []
            for row in data_profile.head_sample:
                if column_name in row:
                    legacy_sample_values.append(row[column_name])
            samples_str = ", ".join(repr(value) for value in legacy_sample_values[:5])

            return (
                f"Column: {col.name}\n"
                f"  dtype: {col.dtype}\n"
                f"  null_count: {col.null_count} ({col.null_pct:.1f}%)\n"
                f"  unique_count: {col.unique_count} ({col.unique_pct:.1f}%)\n"
                f"  statistics: {stats or '(none)'}\n"
                f"  sample values: [{samples_str}]"
            )

    available = [column.name for column in data_profile.columns]
    return f"Column '{column_name}' not found. Available columns: {available}"
