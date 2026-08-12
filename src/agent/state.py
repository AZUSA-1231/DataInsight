from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    model_serializer,
    model_validator,
)


class UnitType(StrEnum):
    TRANSFORM = "transform"
    FILTER = "filter"
    TERMINAL = "terminal"


class ExecutionMode(StrEnum):
    TEMPLATE = "template"
    LLM = "llm"


OperationName = Literal["derive_column", "filter", "join", "terminal"]


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


class DataSource(BaseModel):
    """One uploaded source retained by a v2 Session."""

    source_id: str
    display_name: str
    upload_path: str
    snapshot_id: str
    source_checkpoint_id: str
    profile: DataProfile


class SnapshotRecord(BaseModel):
    """Logical data view and its current physical checkpoint head."""

    snapshot_id: str
    name: str
    display_name: str
    current_checkpoint_id: str
    created_by_unit_id: int | None = None
    parent_snapshot_ids: list[str] = Field(default_factory=list)


class CheckpointRecord(BaseModel):
    """Immutable physical data result and qualified-column mapping."""

    checkpoint_id: str
    snapshot_id: str
    parent_checkpoint_ids: list[str] = Field(default_factory=list)
    producer_unit_id: int | None = None
    run_id: str
    path: str
    row_count: int
    columns: dict[str, str] = Field(default_factory=dict)


class ColumnNode(BaseModel):
    """One concrete version of a visible column in the Column Graph."""

    node_id: str
    ref: str
    name: str
    snapshot: str
    dtype: str
    row_count: int
    source_table: str | None = None
    source_column: str | None = None
    origin_columns: list[str] = Field(default_factory=list)
    created_by_unit_id: int | None = None
    derived_from_node_ids: list[str] = Field(default_factory=list)


class ColumnGraph(BaseModel):
    """Persisted Column Graph container."""

    nodes: dict[str, ColumnNode] = Field(default_factory=dict)


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
    suggestions: list[Suggestion] = Field(default_factory=list)
    caution_notes: str | None = None


class UnitSuggestion(BaseModel):
    """A pre-structured analysis unit suggestion from Business Track.

    More concrete than the high-level Suggestion — specifies exact fields
    and a recommended method, bridging business intent to technical plan.
    """

    purpose: str
    model: str | None = None
    related_fields: list[str] = Field(default_factory=list)
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
    suggestions: list[Suggestion] = Field(default_factory=list)
    caution_notes: str | None = None

    # Natural-language brief — the most important field
    instruction_nl: str = ""


class PlanUnit(BaseModel):
    """Legacy Cycle 4 unit adapter.

    New plans use one of the operation-specific models below. This adapter is
    intentionally kept so old in-memory fixtures and explicitly incompatible
    Cycle 4 callers fail or migrate at a controlled boundary instead of being
    silently interpreted as a v2 operation.
    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    unit_id: int = Field(gt=0)
    operation: Literal["legacy"] = "legacy"
    unit_type: UnitType = UnitType.TRANSFORM
    execution_mode: ExecutionMode = ExecutionMode.LLM
    purpose: str
    model_hint: str | None = None
    cautious: str = ""
    depends_on: list[int] = Field(default_factory=list)
    input_from: str | None = None
    input_columns: list[str] = Field(default_factory=list)
    output_columns: list[str] = Field(default_factory=list)
    related_fields: list[str] = Field(default_factory=list)
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


class _PlanUnitV2Base(BaseModel):
    """Fields common to every persisted v2 operation unit."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    operation: OperationName
    unit_id: int = Field(gt=0)
    execution_mode: ExecutionMode = ExecutionMode.LLM
    purpose: str
    model_hint: str | None = Field(
        default=None,
        validation_alias=AliasChoices("model_hint", "model"),
    )
    cautious: str = ""
    depends_on: list[int] = Field(default_factory=list)
    template_name: str | None = None
    template_params: dict[str, object] | None = Field(
        default=None,
        validation_alias=AliasChoices("template_params", "params"),
    )

    @model_validator(mode="after")
    def _validate_dependencies(self) -> _PlanUnitV2Base:
        if self.unit_id in self.depends_on:
            raise ValueError("depends_on cannot contain the unit's own unit_id")
        if len(self.depends_on) != len(set(self.depends_on)):
            raise ValueError("depends_on must not contain duplicate unit IDs")
        if any(dependency <= 0 for dependency in self.depends_on):
            raise ValueError("depends_on must contain positive unit IDs")
        return self

    @property
    def unit_type(self) -> UnitType:
        """Cycle 4 compatibility projection for the executor migration."""
        if self.operation == "filter":
            return UnitType.FILTER
        if self.operation == "terminal":
            return UnitType.TERMINAL
        return UnitType.TRANSFORM

    @property
    def input_from(self) -> str | None:
        """Cycle 4 branch projection; M3 removes its execution use."""
        input_snapshot = self.__dict__.get("input_snapshot")
        if input_snapshot is not None:
            return str(input_snapshot)
        inputs = self.__dict__.get("inputs")
        if isinstance(inputs, list) and inputs:
            first = inputs[0]
            return getattr(first, "snapshot", None)
        return None

    @property
    def related_fields(self) -> list[str]:
        """Cycle 4 field-chip projection derived from v2 inputs."""
        return list(getattr(self, "input_columns", []))

    @property
    def params(self) -> dict[str, object] | None:
        return self.template_params


class DeriveColumnUnit(_PlanUnitV2Base):
    """Add exactly one column to an existing Snapshot."""

    operation: Literal["derive_column"] = "derive_column"
    input_snapshot: str
    input_columns: list[str] = Field(min_length=1)
    output_columns: list[str] = Field(min_length=1, max_length=1)


class FilterUnit(_PlanUnitV2Base):
    """Create a new Snapshot containing an indexed subset of the input."""

    operation: Literal["filter"] = "filter"
    input_snapshot: str
    input_columns: list[str] = Field(min_length=1)
    output_snapshot: str

    @property
    def output_columns(self) -> list[str]:
        return []


class JoinInput(BaseModel):
    """One side of a deterministic two-Snapshot join."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["left", "right"]
    snapshot: str


class JoinKey(BaseModel):
    """A qualified left/right key pair."""

    model_config = ConfigDict(extra="forbid")

    left: str
    right: str


class JoinSelect(BaseModel):
    """A selected qualified input column and its output alias."""

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
    )

    from_: str = Field(
        validation_alias=AliasChoices("from", "from_"),
        serialization_alias="from",
    )
    as_: str = Field(
        validation_alias=AliasChoices("as", "as_"),
        serialization_alias="as",
    )

    @property
    def source(self) -> str:
        return self.from_

    @property
    def alias(self) -> str:
        return self.as_

    @model_serializer(mode="plain")
    def _serialize_with_contract_names(self) -> dict[str, str]:
        return {"from": self.from_, "as": self.as_}


class JoinUnit(_PlanUnitV2Base):
    """Join two existing Snapshots into one explicitly selected Snapshot."""

    operation: Literal["join"] = "join"
    inputs: list[JoinInput] = Field(min_length=2, max_length=2)
    keys: list[JoinKey] = Field(default_factory=list)
    select: list[JoinSelect] = Field(min_length=1)
    output_snapshot: str
    how: Literal[
        "left", "right", "inner", "outer", "cross", "semi", "anti"
    ] = "left"

    @model_validator(mode="before")
    @classmethod
    def _flatten_join_spec(cls, data: object) -> object:
        """Accept the documented nested ``join`` object as input syntax."""
        if not isinstance(data, dict) or not isinstance(data.get("join"), dict):
            return data
        flattened = {key: value for key, value in data.items() if key != "join"}
        nested = data["join"]
        for key in ("keys", "select", "how"):
            if key not in flattened and key in nested:
                flattened[key] = nested[key]
        return flattened

    @model_validator(mode="after")
    def _validate_join_shape(self) -> JoinUnit:
        roles = [item.role for item in self.inputs]
        if sorted(roles) != ["left", "right"]:
            raise ValueError("inputs must contain exactly one left and one right item")
        if self.how == "cross" and self.keys:
            raise ValueError("cross joins must not declare key pairs")
        if self.how != "cross" and not self.keys:
            raise ValueError("non-cross joins require at least one key pair")
        aliases = [item.as_ for item in self.select]
        if len(aliases) != len(set(aliases)):
            raise ValueError("join select aliases must be unique")
        if any(not alias or alias == "__di_row_id" for alias in aliases):
            raise ValueError("join select aliases must be non-empty and cannot use __di_row_id")
        if self.how in {"semi", "anti"}:
            left_input = next(item for item in self.inputs if item.role == "left")
            if any(
                not selected.from_.startswith(f"{left_input.snapshot}.")
                for selected in self.select
            ):
                raise ValueError(
                    f"{self.how} joins may select columns only from the left Snapshot"
                )
        return self

    @property
    def input_columns(self) -> list[str]:
        refs = [key.left for key in self.keys] + [key.right for key in self.keys]
        refs.extend(item.from_ for item in self.select)
        return list(dict.fromkeys(refs))

    @property
    def output_columns(self) -> list[str]:
        return []


class TerminalUnit(_PlanUnitV2Base):
    """Produce artifacts from one Snapshot without creating data columns."""

    operation: Literal["terminal"] = "terminal"
    input_snapshot: str
    input_columns: list[str] = Field(min_length=1)

    @property
    def output_columns(self) -> list[str]:
        return []


PlanUnitDiscriminated = Annotated[
    DeriveColumnUnit | FilterUnit | JoinUnit | TerminalUnit,
    Field(discriminator="operation"),
]
PlanUnitValue = PlanUnitDiscriminated | PlanUnit
PlanUnitLike = PlanUnitValue

# Short public aliases make the operation models convenient to import while
# keeping the descriptive names used by the persisted contract.
DeriveUnit = DeriveColumnUnit
FilterOperation = FilterUnit
JoinOperation = JoinUnit
TerminalOperation = TerminalUnit
PlanUnitUnion = PlanUnitDiscriminated


class Plan(BaseModel):
    """Structured analysis orchestration plan.

    The first branch is a real operation discriminator. The legacy branch is
    only a compatibility adapter for pre-Cycle-5 in-memory callers; v2 API and
    Planner payloads always carry an explicit ``operation``.
    """

    model_config = ConfigDict(extra="forbid")

    units: list[PlanUnitValue]
    alignment_notes: str = ""

    @model_validator(mode="before")
    @classmethod
    def _require_explicit_operation(cls, data: object) -> object:
        """Keep missing operation fields from silently becoming v1 units."""
        if isinstance(data, dict):
            raw_units = data.get("units", [])
            if isinstance(raw_units, list) and any(
                isinstance(unit, dict) and "operation" not in unit
                for unit in raw_units
            ):
                raise ValueError("Every Plan unit must declare an operation")
        return data


class AgentState(BaseModel):
    """Shared state flowing through the analysis pipeline.

    All nodes read from and write to this state. Nodes return partial dicts
    that LangGraph merges into the model — never mutate in place.
    """

    # Cycle 5 durable state. Cycle 4 fields below remain only as a temporary
    # runtime adapter until the Plan v2 migration is complete.
    schema_version: int = 2
    user_requirement: str
    data_sources: list[DataSource] = Field(default_factory=list)
    snapshot_registry: dict[str, SnapshotRecord] = Field(default_factory=dict)
    checkpoint_registry: dict[str, CheckpointRecord] = Field(default_factory=dict)
    column_graph: ColumnGraph = Field(default_factory=ColumnGraph)

    # Temporary compatibility inputs for the existing graph and CLI. New
    # persistence and API ingestion use the registries above as source of truth.
    file_path: str = ""
    data_profile: DataProfile | None = None
    unified_columns: list[str] = Field(default_factory=list)
    analysis_intent: AnalysisIntent | None = None
    planner_instruction: PlannerInstruction | None = None
    plan: Plan | None = None
    analysis_result: dict[str, Any] | None = None
    final_report: str | None = None
    error: str | None = None
    feedback: str | None = None
    dashboard_pins: list[dict[str, Any]] = Field(default_factory=list)
    dialogue_history: list[dict[str, str]] = Field(default_factory=list)
    persisted_at: str | None = None
