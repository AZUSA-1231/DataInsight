"""Small, typed Copilot tools for the Cycle 6 bounded turn.

The functions in this module are deliberately ordinary domain adapters.  The
tool names and their input/output models are declared in one small static
mapping; there is no generic action registry and no tool is allowed to invoke
the Copilot recursively.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from src.agent.copilot_context import build_workspace_context
from src.agent.plan_validation import PlanValidationError, validate_plan
from src.agent.state import AgentState, Plan, PlanUnit

if TYPE_CHECKING:
    from src.agent.copilot import CopilotToolBinding, CopilotToolHandler


class _StrictToolModel(BaseModel):
    """Base contract for tool payloads: unknown fields are not silently ignored."""

    model_config = ConfigDict(extra="forbid")


class InspectColumnInput(_StrictToolModel):
    """Input for inspecting one exact qualified column reference."""

    column_name: str = Field(
        min_length=1,
        max_length=256,
        description=(
            "Exact qualified column reference, for example orders.amount. "
            "Use the spelling shown by the current Snapshot workspace."
        ),
    )

    @field_validator("column_name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("column_name must not be blank")
        return value


class InspectSnapshotInput(_StrictToolModel):
    """Input for inspecting one logical Snapshot by its public name."""

    snapshot_name: str = Field(
        min_length=1,
        max_length=128,
        description="Exact logical Snapshot name, for example orders or east_orders.",
    )

    @field_validator("snapshot_name")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("snapshot_name must not be blank")
        return value


class InspectResultsInput(_StrictToolModel):
    """Input for inspecting all execution results or one unit's result."""

    unit_id: int | None = Field(
        default=None,
        gt=0,
        description="Optional positive Plan unit ID to inspect in detail.",
    )


class PlanEditInput(_StrictToolModel):
    """Request passed to the injectable Plan editing boundary."""

    request: str = Field(
        min_length=1,
        max_length=4000,
        description="The user's requested Plan change, including relevant constraints.",
    )

    @field_validator("request")
    @classmethod
    def _non_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("request must not be blank")
        return value


class LineageSummary(_StrictToolModel):
    """Public lineage facts; internal node and checkpoint IDs are excluded."""

    source_column: str | None = None
    origin_refs: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    created_by_unit_id: int | None = None


class InspectColumnResult(_StrictToolModel):
    """JSON-safe result for a column inspection."""

    found: bool
    column_name: str
    snapshot: str | None = None
    name: str | None = None
    dtype: str | None = None
    row_count: int | None = None
    null_count: int | None = None
    null_pct: float | None = None
    unique_count: int | None = None
    unique_pct: float | None = None
    statistics: dict[str, object] = Field(default_factory=dict)
    sample_values: list[object] = Field(default_factory=list)
    lineage: LineageSummary | None = None
    available_columns: list[str] = Field(default_factory=list)
    message: str = ""


class SnapshotColumnSummary(_StrictToolModel):
    """A visible column summary nested in a Snapshot inspection."""

    ref: str
    name: str
    dtype: str = "unknown"


class InspectSnapshotResult(_StrictToolModel):
    """JSON-safe result for a Snapshot inspection."""

    found: bool
    snapshot_name: str
    display_name: str | None = None
    row_count: int | None = None
    columns: list[SnapshotColumnSummary] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)
    lineage: list[LineageSummary] = Field(default_factory=list)
    available_snapshots: list[str] = Field(default_factory=list)
    message: str = ""


class ExecutionUnitSummary(_StrictToolModel):
    """Safe subset of one persisted execution result."""

    unit_id: int
    status: str
    error: str | None = None
    insights: list[str] = Field(default_factory=list)
    statistics: dict[str, object] = Field(default_factory=dict)
    warnings: list[dict[str, object]] = Field(default_factory=list)
    stale: bool = False
    row_count_before: int | None = None
    row_count_after: int | None = None
    row_count_delta: int | None = None
    chart_count: int = 0


class InspectResultsResult(_StrictToolModel):
    """JSON-safe result for current execution metadata and unit summaries."""

    found: bool
    status: str = "idle"
    stale_unit_ids: list[int] = Field(default_factory=list)
    unit_results: list[ExecutionUnitSummary] = Field(default_factory=list)
    message: str = ""


class PlanEditResult(_StrictToolModel):
    """A complete proposed Plan edit; it is never a state mutation."""

    plan: Plan
    explanation: str
    changed_unit_ids: list[int] = Field(default_factory=list)

    @field_validator("changed_unit_ids")
    @classmethod
    def _unique_positive_ids(cls, value: list[int]) -> list[int]:
        if any(item <= 0 for item in value):
            raise ValueError("changed_unit_ids must contain positive unit IDs")
        if len(value) != len(set(value)):
            raise ValueError("changed_unit_ids must not contain duplicates")
        return value


class PlanEditGateway(Protocol):
    """Replaceable boundary for proposing a complete Plan edit."""

    def propose(
        self,
        request: str,
        workspace_json: dict[str, object],
    ) -> PlanEditResult: ...


class PlanEditGatewayError(ValueError):
    """Raised when a gateway cannot produce a complete typed Plan."""


class MockPlanEditGateway:
    """Deterministic in-memory Plan edit gateway for tests and local wiring.

    A fixed ``plan`` or ``result`` can be supplied by a test/future adapter.
    For simple development use, a JSON request containing either a complete
    Plan or ``{"plan": ...}`` is also accepted.  If neither is supplied, the
    current projected Plan is returned as a validated no-op proposal.  The
    gateway only creates a result; it never receives or mutates ``AgentState``.
    """

    def __init__(
        self,
        plan: Plan | Mapping[str, object] | None = None,
        *,
        explanation: str = "Proposed Plan edit; the Workspace has not been changed.",
        changed_unit_ids: Sequence[int] | None = None,
        result: PlanEditResult | Mapping[str, object] | None = None,
    ) -> None:
        if plan is not None and result is not None:
            raise ValueError("provide either plan or result, not both")
        self._plan = plan
        self._explanation = explanation
        self._changed_unit_ids = (
            list(changed_unit_ids) if changed_unit_ids is not None else None
        )
        self._result = result

    def propose(
        self,
        request: str,
        workspace_json: dict[str, object],
    ) -> PlanEditResult:
        if self._result is not None:
            return self._validate_result(self._result)

        candidate: object = self._plan
        request_payload = _json_object(request)
        if candidate is None and request_payload is not None:
            candidate = request_payload.get("plan", request_payload)
        if candidate is None:
            workspace_plan = workspace_json.get("plan")
            if workspace_plan is not None:
                candidate = workspace_plan
        if candidate is None:
            raise PlanEditGatewayError(
                "the mock PlanEditGateway has no complete Plan proposal configured"
            )

        try:
            parsed_plan = Plan.model_validate(candidate)
        except ValidationError as exc:
            raise PlanEditGatewayError(
                f"Plan proposal is malformed: {_validation_summary(exc)}"
            ) from exc

        changed_unit_ids = self._changed_unit_ids
        if changed_unit_ids is None:
            changed_unit_ids = _changed_unit_ids(workspace_json.get("plan"), parsed_plan)

        try:
            return PlanEditResult(
                plan=parsed_plan,
                explanation=self._explanation,
                changed_unit_ids=changed_unit_ids,
            )
        except ValidationError as exc:
            raise PlanEditGatewayError(
                f"Plan edit result is malformed: {_validation_summary(exc)}"
            ) from exc

    @staticmethod
    def _validate_result(
        result: PlanEditResult | Mapping[str, object],
    ) -> PlanEditResult:
        try:
            return PlanEditResult.model_validate(result)
        except ValidationError as exc:
            raise PlanEditGatewayError(
                f"Plan edit result is malformed: {_validation_summary(exc)}"
            ) from exc


# These aliases keep the intent obvious to callers while retaining one
# implementation and one in-memory behavior.
InMemoryPlanEditGateway = MockPlanEditGateway
DefaultPlanEditGateway = MockPlanEditGateway


def inspect_column(state: AgentState, request: InspectColumnInput) -> InspectColumnResult:
    """Inspect one visible qualified column using only projected workspace facts."""

    workspace = _workspace_mapping(build_workspace_context(state))
    requested = request.column_name
    columns = _visible_columns(workspace)
    available = [str(item["ref"]) for item in columns if isinstance(item.get("ref"), str)]

    match = next(
        (item for item in columns if item.get("ref") == requested),
        None,
    )
    source_column: Mapping[str, object] | None = None
    if match is not None:
        source_column = _source_column(workspace, match)
    elif "." not in requested:
        # Legacy profiles may not have qualified refs yet.  This fallback is
        # still limited to the public source profile projection.
        source_column = _legacy_source_column(workspace, requested)
        if source_column is not None:
            match = {
                "ref": requested,
                "snapshot": _source_snapshot(source_column),
                "name": requested,
                "dtype": source_column.get("dtype", "unknown"),
            }

    if match is None:
        return InspectColumnResult(
            found=False,
            column_name=requested,
            available_columns=available,
            message=(
                f"Column '{requested}' was not found in the current workspace."
            ),
        )

    snapshot = _optional_string(match.get("snapshot"))
    name = _optional_string(match.get("name")) or requested.rsplit(".", 1)[-1]
    source_column = source_column or _source_column_by_name(workspace, snapshot, name)
    lineage_raw = _find_lineage(workspace, requested)
    lineage = _lineage_summary(lineage_raw) if lineage_raw else None
    row_count = _optional_int(match.get("row_count"))
    if row_count is None and snapshot is not None:
        row_count = next(
            (
                _optional_int(item.get("row_count"))
                for item in _mapping_list(workspace.get("snapshots"))
                if item.get("name") == snapshot
            ),
        )

    return InspectColumnResult(
        found=True,
        column_name=requested,
        snapshot=snapshot,
        name=name,
        dtype=_optional_string(match.get("dtype")) or _optional_string(
            source_column.get("dtype") if source_column else None
        ),
        row_count=row_count,
        null_count=_optional_int(
            source_column.get("null_count") if source_column else match.get("null_count")
        ),
        null_pct=_optional_float(
            source_column.get("null_pct") if source_column else match.get("null_pct")
        ),
        unique_count=_optional_int(
            source_column.get("unique_count")
            if source_column
            else match.get("unique_count")
        ),
        unique_pct=_optional_float(
            source_column.get("unique_pct") if source_column else match.get("unique_pct")
        ),
        statistics=_mapping_or_empty(
            source_column.get("statistics") if source_column else match.get("statistics")
        ),
        sample_values=_object_list(
            source_column.get("sample_values") if source_column else match.get("sample_values")
        ),
        lineage=lineage,
        available_columns=available,
        message="",
    )


def inspect_snapshot(
    state: AgentState,
    request: InspectSnapshotInput,
) -> InspectSnapshotResult:
    """Inspect one Snapshot, visible columns, and public lineage summaries."""

    workspace = _workspace_mapping(build_workspace_context(state))
    requested = request.snapshot_name
    snapshots = _mapping_list(workspace.get("snapshots"))
    available = [
        name
        for item in snapshots
        if (name := _optional_string(item.get("name"))) is not None
    ]
    snapshot = next((item for item in snapshots if item.get("name") == requested), None)
    if snapshot is None:
        return InspectSnapshotResult(
            found=False,
            snapshot_name=requested,
            available_snapshots=available,
            message=(
                f"Snapshot '{requested}' was not found in the current workspace."
            ),
        )

    refs = [ref for ref in _string_list(snapshot.get("columns")) if _is_public_ref(ref)]
    qualified_columns = {
        str(item.get("ref")): item
        for item in _visible_columns(workspace)
        if isinstance(item.get("ref"), str)
    }
    column_summaries = [
        SnapshotColumnSummary(
            ref=ref,
            name=(
                _optional_string(qualified_columns.get(ref, {}).get("name"))
                or ref.rsplit(".", 1)[-1]
            ),
            dtype=_optional_string(qualified_columns.get(ref, {}).get("dtype")) or "unknown",
        )
        for ref in refs
    ]
    lineage = [
        summary
        for item in _mapping_list(workspace.get("lineage"))
        if item.get("snapshot") == requested
        and (summary := _lineage_summary(item)) is not None
    ]
    return InspectSnapshotResult(
        found=True,
        snapshot_name=requested,
        display_name=_optional_string(snapshot.get("display_name")),
        row_count=_optional_int(snapshot.get("row_count")),
        columns=column_summaries,
        parents=[parent for parent in _string_list(snapshot.get("parents")) if parent],
        lineage=lineage,
        available_snapshots=available,
        message="",
    )


def inspect_results(
    state: AgentState,
    request: InspectResultsInput,
) -> InspectResultsResult:
    """Inspect safe execution status and result summaries."""

    workspace = _workspace_mapping(build_workspace_context(state))
    execution = _mapping(workspace.get("execution"))
    status = _optional_string(execution.get("status")) or "idle"
    stale_ids = [
        item for item in _object_list(execution.get("stale_unit_ids")) if isinstance(item, int)
    ]
    unit_results: list[ExecutionUnitSummary] = []
    for raw in _mapping_list(execution.get("unit_results")):
        unit_id = raw.get("unit_id")
        if not isinstance(unit_id, int) or unit_id <= 0:
            continue
        if request.unit_id is not None and request.unit_id != unit_id:
            continue
        unit_results.append(
            ExecutionUnitSummary(
                unit_id=unit_id,
                status=_optional_string(raw.get("status")) or "unknown",
                error=_optional_string(raw.get("error")),
                insights=[item for item in _string_list(raw.get("insights"))],
                statistics=_mapping_or_empty(raw.get("statistics")),
                warnings=[
                    dict(item)
                    for item in _mapping_list(raw.get("warnings"))
                ],
                stale=bool(raw.get("stale", False)),
                row_count_before=_optional_int(raw.get("row_count_before")),
                row_count_after=_optional_int(raw.get("row_count_after")),
                row_count_delta=_optional_int(raw.get("row_count_delta")),
                chart_count=_optional_int(raw.get("chart_count")) or 0,
            )
        )

    found = bool(unit_results) if request.unit_id is not None else bool(
        unit_results or status != "idle" or stale_ids
    )
    message = ""
    if not found:
        message = (
            f"No execution result was found for unit {request.unit_id}."
            if request.unit_id is not None
            else "No execution results are available in the current workspace."
        )
    return InspectResultsResult(
        found=found,
        status=status,
        stale_unit_ids=stale_ids,
        unit_results=unit_results,
        message=message,
    )


def plan_edit(
    state: AgentState,
    request: PlanEditInput,
    gateway: PlanEditGateway,
) -> PlanEditResult:
    """Propose and validate a complete Plan without mutating ``state``."""

    context = build_workspace_context(state)
    raw_result = gateway.propose(
        request.request,
        _workspace_mapping(context),
    )
    try:
        result = PlanEditResult.model_validate(raw_result)
    except ValidationError as exc:
        raise PlanEditGatewayError(
            f"Plan edit gateway returned malformed output: {_validation_summary(exc)}"
        ) from exc

    if any(isinstance(unit, PlanUnit) for unit in result.plan.units):
        raise PlanEditGatewayError(
            "Plan edit must return explicit Cycle 5 Plan v2 operation units"
        )
    try:
        validate_plan(result.plan, state)
    except PlanValidationError as exc:
        raise PlanEditGatewayError(f"Plan edit failed workspace validation: {exc}") from exc
    return result


@dataclass(frozen=True)
class CopilotToolSpec:
    """Static metadata for one typed Copilot tool."""

    name: str
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]


# Keep this mapping explicit and small.  It is intentionally not a dynamic
# registry: adding a tool requires adding its schema and handler here.
COPILOT_TOOL_SPECS: dict[str, CopilotToolSpec] = {
    "inspect_column": CopilotToolSpec(
        name="inspect_column",
        description=(
            "Inspect exact qualified column statistics, samples, and public lineage."
        ),
        input_model=InspectColumnInput,
        output_model=InspectColumnResult,
    ),
    "inspect_snapshot": CopilotToolSpec(
        name="inspect_snapshot",
        description="Inspect a logical Snapshot's visible columns, row count, and lineage.",
        input_model=InspectSnapshotInput,
        output_model=InspectSnapshotResult,
    ),
    "inspect_results": CopilotToolSpec(
        name="inspect_results",
        description="Inspect current execution status and safe unit result summaries.",
        input_model=InspectResultsInput,
        output_model=InspectResultsResult,
    ),
    "plan_edit": CopilotToolSpec(
        name="plan_edit",
        description=(
            "Propose a complete validated Plan edit. The result is a proposal and "
            "does not update the Workspace."
        ),
        input_model=PlanEditInput,
        output_model=PlanEditResult,
    ),
}

COPILOT_TOOL_SCHEMAS: dict[str, dict[str, object]] = {
    "inspect_column": {
        "type": "function",
        "function": {
            "name": "inspect_column",
            "description": COPILOT_TOOL_SPECS["inspect_column"].description,
            "parameters": InspectColumnInput.model_json_schema(),
        },
    },
    "inspect_snapshot": {
        "type": "function",
        "function": {
            "name": "inspect_snapshot",
            "description": COPILOT_TOOL_SPECS["inspect_snapshot"].description,
            "parameters": InspectSnapshotInput.model_json_schema(),
        },
    },
    "inspect_results": {
        "type": "function",
        "function": {
            "name": "inspect_results",
            "description": COPILOT_TOOL_SPECS["inspect_results"].description,
            "parameters": InspectResultsInput.model_json_schema(),
        },
    },
    "plan_edit": {
        "type": "function",
        "function": {
            "name": "plan_edit",
            "description": COPILOT_TOOL_SPECS["plan_edit"].description,
            "parameters": PlanEditInput.model_json_schema(),
        },
    },
}


InputModelT = TypeVar("InputModelT", bound=BaseModel)
OutputModelT = TypeVar("OutputModelT", bound=BaseModel)


def _typed_handler(
    input_model: type[InputModelT],
    output_model: type[OutputModelT],
    handler: Callable[[AgentState, InputModelT], OutputModelT],
) -> Callable[[AgentState, dict[str, object]], object]:
    def invoke(state: AgentState, raw_arguments: dict[str, object]) -> object:
        parsed = input_model.model_validate(raw_arguments)
        result = handler(state, parsed)
        return output_model.model_validate(result)

    return invoke


def build_copilot_tool_handler_map(
    plan_edit_gateway: PlanEditGateway | None = None,
) -> dict[str, CopilotToolHandler]:
    """Return the explicit name-to-handler map for one tool wiring instance."""

    from src.agent.copilot import CopilotToolHandler

    gateway = plan_edit_gateway or DefaultPlanEditGateway()
    return {
        "inspect_column": cast(
            CopilotToolHandler,
            _typed_handler(InspectColumnInput, InspectColumnResult, inspect_column),
        ),
        "inspect_snapshot": cast(
            CopilotToolHandler,
            _typed_handler(InspectSnapshotInput, InspectSnapshotResult, inspect_snapshot),
        ),
        "inspect_results": cast(
            CopilotToolHandler,
            _typed_handler(InspectResultsInput, InspectResultsResult, inspect_results),
        ),
        "plan_edit": cast(
            CopilotToolHandler,
            _typed_handler(
                PlanEditInput,
                PlanEditResult,
                lambda state, request: plan_edit(state, request, gateway),
            ),
        ),
    }


def build_copilot_tool_bindings(
    plan_edit_gateway: PlanEditGateway | None = None,
) -> tuple[CopilotToolBinding, ...]:
    """Build the explicit typed bindings consumed by ``CopilotTurnHandler``."""

    # The local import avoids making the bounded turn module depend on its
    # static tool module at import time, while preserving M1's public binding.
    from src.agent.copilot import CopilotToolBinding

    handlers = build_copilot_tool_handler_map(plan_edit_gateway)
    return (
        CopilotToolBinding(
            name="inspect_column",
            schema=COPILOT_TOOL_SCHEMAS["inspect_column"],
            handler=handlers["inspect_column"],
        ),
        CopilotToolBinding(
            name="inspect_snapshot",
            schema=COPILOT_TOOL_SCHEMAS["inspect_snapshot"],
            handler=handlers["inspect_snapshot"],
        ),
        CopilotToolBinding(
            name="inspect_results",
            schema=COPILOT_TOOL_SCHEMAS["inspect_results"],
            handler=handlers["inspect_results"],
        ),
        CopilotToolBinding(
            name="plan_edit",
            schema=COPILOT_TOOL_SCHEMAS["plan_edit"],
            handler=handlers["plan_edit"],
        ),
    )


# A descriptive alias is useful to API wiring and does not create another
# orchestration path.
default_copilot_tool_bindings = build_copilot_tool_bindings


def _workspace_mapping(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _visible_columns(workspace: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        item
        for item in _mapping_list(workspace.get("qualified_columns"))
        if _is_public_ref(item.get("ref"))
    ]


def _source_column(
    workspace: Mapping[str, object],
    column: Mapping[str, object],
) -> Mapping[str, object] | None:
    return _source_column_by_name(
        workspace,
        _optional_string(column.get("snapshot")),
        _optional_string(column.get("name")),
    )


def _source_column_by_name(
    workspace: Mapping[str, object],
    snapshot: str | None,
    name: str | None,
) -> Mapping[str, object] | None:
    if name is None:
        return None
    for source in _mapping_list(workspace.get("sources")):
        if snapshot is not None and source.get("snapshot") != snapshot:
            continue
        for column in _mapping_list(source.get("columns")):
            if column.get("name") == name:
                return column
    return None


def _legacy_source_column(
    workspace: Mapping[str, object],
    name: str,
) -> Mapping[str, object] | None:
    for source in _mapping_list(workspace.get("sources")):
        for column in _mapping_list(source.get("columns")):
            if column.get("name") == name:
                return column
    return None


def _source_snapshot(column: Mapping[str, object]) -> str | None:
    value = column.get("snapshot")
    return value if isinstance(value, str) and value else None


def _find_lineage(
    workspace: Mapping[str, object],
    ref: str,
) -> Mapping[str, object] | None:
    for item in _mapping_list(workspace.get("lineage")):
        if item.get("ref") == ref:
            return item
    return None


def _lineage_summary(value: Mapping[str, object]) -> LineageSummary | None:
    """Project the context lineage record onto the public result model."""

    try:
        source_column = value.get("source_column")
        return LineageSummary.model_validate(
            {
                "source_column": (
                    source_column if _is_public_ref(source_column) else None
                ),
                "origin_refs": [
                    ref
                    for ref in _string_list(value.get("origin_refs"))
                    if _is_public_ref(ref)
                ],
                "derived_from": [
                    ref
                    for ref in _string_list(value.get("derived_from"))
                    if _is_public_ref(ref)
                ],
                "created_by_unit_id": value.get("created_by_unit_id"),
            }
        )
    except ValidationError:
        return None


def _is_public_ref(value: object) -> bool:
    return isinstance(value, str) and "__di_row_id" not in value and not value.startswith("_")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [item for item in value if isinstance(item, str)]


def _object_list(value: object) -> list[object]:
    if not isinstance(value, list | tuple):
        return []
    return list(value)


def _mapping_or_empty(value: object) -> dict[str, object]:
    return {str(key): item for key, item in _mapping(value).items()}


def _json_object(value: str) -> Mapping[str, object] | None:
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, Mapping) else None


def _changed_unit_ids(current: object, proposed: Plan) -> list[int]:
    current_units: dict[int, object] = {}
    if isinstance(current, Mapping):
        raw_units = current.get("units")
        if isinstance(raw_units, list):
            for item in raw_units:
                if isinstance(item, Mapping) and isinstance(item.get("unit_id"), int):
                    current_units[item["unit_id"]] = dict(item)
    proposed_units = {
        unit.unit_id: unit.model_dump(mode="json", by_alias=True)
        for unit in proposed.units
    }
    changed: list[int] = []
    for unit_id in sorted(set(current_units) | set(proposed_units)):
        if current_units.get(unit_id) != proposed_units.get(unit_id):
            changed.append(unit_id)
    return changed


def _validation_summary(exc: ValidationError) -> str:
    errors = exc.errors()
    if not errors:
        return "validation failed"
    first = errors[0]
    location = ".".join(str(part) for part in first.get("loc", ()))
    message = str(first.get("msg", "validation failed"))
    return f"{location}: {message}" if location else message
