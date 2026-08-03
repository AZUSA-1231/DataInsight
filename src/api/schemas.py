from __future__ import annotations

from pydantic import BaseModel, Field

from src.agent.state import Plan


# --- Session ---
class SessionCreateRequest(BaseModel):
    user_requirement: str = ""


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionStateResponse(BaseModel):
    session_id: str
    schema_version: int = 2
    has_data: bool
    has_intent: bool
    has_plan: bool
    has_results: bool
    has_report: bool
    error: str | None = None
    persisted_at: str | None = None


# --- Data Pool ---
class ColumnInfoResponse(BaseModel):
    name: str
    dtype: str
    null_count: int
    null_pct: float
    ref: str | None = None
    snapshot: str | None = None
    source_column: str | None = None


class DataProfileResponse(BaseModel):
    file_path: str
    shape: tuple[int, int]
    columns: list[ColumnInfoResponse]
    encoding: str | None = None
    statistics: dict[str, dict[str, object]] = Field(default_factory=dict)
    head_sample: list[dict[str, object]] = Field(default_factory=list)


class SourceProfileResponse(BaseModel):
    source_id: str
    snapshot_id: str
    snapshot_name: str
    display_name: str
    profile: DataProfileResponse


class ProfilesResponse(BaseModel):
    profiles: list[SourceProfileResponse]


class DataUploadResponse(BaseModel):
    file_name: str
    row_count: int
    col_count: int
    unified_columns: list[str] = Field(default_factory=list)
    source_id: str | None = None
    snapshot_id: str | None = None
    snapshot_name: str | None = None
    checkpoint_id: str | None = None
    columns: list[ColumnInfoResponse] = Field(default_factory=list)


class SourceResponse(BaseModel):
    source_id: str
    display_name: str
    snapshot_id: str
    snapshot_name: str
    row_count: int
    col_count: int
    checkpoint_id: str


class SourcesResponse(BaseModel):
    sources: list[SourceResponse]


class SnapshotResponse(BaseModel):
    snapshot_id: str
    name: str
    display_name: str
    current_checkpoint_id: str
    row_count: int
    column_refs: list[str] = Field(default_factory=list)
    source_id: str | None = None
    created_by_unit_id: int | None = None
    parent_snapshot_ids: list[str] = Field(default_factory=list)


class SnapshotsResponse(BaseModel):
    snapshots: list[SnapshotResponse]


class LineageColumnResponse(BaseModel):
    ref: str
    snapshot: str
    name: str
    dtype: str
    source_column: str | None = None
    origin_refs: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    created_by_unit_id: int | None = None


class LineageResponse(BaseModel):
    columns: list[LineageColumnResponse]


class ColumnsResponse(BaseModel):
    columns: list[ColumnInfoResponse]
    unified_columns: list[str] = Field(default_factory=list)


# --- Workspace ---
class UnitCreateRequest(BaseModel):
    purpose: str = ""
    model: str | None = None
    cautious: str = ""
    related_fields: list[str] = Field(default_factory=list)
    operation: str | None = None
    execution_mode: str | None = None
    depends_on: list[int] = Field(default_factory=list)
    input_snapshot: str | None = None
    input_columns: list[str] | None = None
    output_columns: list[str] | None = None
    output_snapshot: str | None = None
    inputs: list[dict[str, str]] | None = None
    keys: list[dict[str, str]] | None = None
    select: list[dict[str, str]] | None = None
    how: str | None = None
    template_name: str | None = None
    template_params: dict[str, object] | None = None
    params: dict[str, object] | None = None


class UnitUpdateRequest(BaseModel):
    purpose: str | None = None
    model: str | None = None
    cautious: str | None = None
    related_fields: list[str] | None = None
    operation: str | None = None
    execution_mode: str | None = None
    depends_on: list[int] | None = None
    input_snapshot: str | None = None
    input_columns: list[str] | None = None
    output_columns: list[str] | None = None
    output_snapshot: str | None = None
    inputs: list[dict[str, str]] | None = None
    keys: list[dict[str, str]] | None = None
    select: list[dict[str, str]] | None = None
    how: str | None = None
    template_name: str | None = None
    template_params: dict[str, object] | None = None
    params: dict[str, object] | None = None


class WorkspacePlanResponse(BaseModel):
    plan: Plan | None


class GeneratePlanRequest(BaseModel):
    instruction: dict[str, object] | None = None


# --- Dialogue ---
class DialogueRequest(BaseModel):
    message: str


class DialogueResponse(BaseModel):
    action: str  # "chat" | "confirm"
    message: str  # BT's conversational text
    instruction: dict[str, object] | None = None  # Present when action=confirm
    is_contextualized: bool = False


# --- Execution ---
class ExecutionStatusResponse(BaseModel):
    status: str
    progress: str | None = None
    error: str | None = None


class UnitResultResponse(BaseModel):
    unit_id: int
    status: str
    stdout: str
    stderr: str
    charts: list[str]
    insights: list[str]
    error: str | None = None
    stale: bool = False
    run_id: str | None = None
    input_checkpoint_ids: list[str] = Field(default_factory=list)
    output_checkpoint_id: str | None = None
    row_count_before: int | None = None
    row_count_after: int | None = None
    row_count_delta: int | None = None
    input_row_counts: list[int] = Field(default_factory=list)
    statistics: dict[str, object] = Field(default_factory=dict)
    warnings: list[dict[str, object]] = Field(default_factory=list)


class ExecutionResultResponse(BaseModel):
    units: list[UnitResultResponse]
    status: str = "idle"
    run_id: str | None = None
    stale_unit_ids: list[int] = Field(default_factory=list)


class RerunUnitResponse(BaseModel):
    unit_id: int
    status: str
    stale_units: list[int] = []
    input_checkpoint_ids: list[str] = []
    output_checkpoint_id: str | None = None
    charts: list[str] = []
    insights: list[str] = []
    error: str | None = None
    run_id: str | None = None
    row_count_before: int | None = None
    row_count_after: int | None = None
    row_count_delta: int | None = None
    warnings: list[dict[str, object]] = Field(default_factory=list)


# --- Dashboard ---
class PinChartRequest(BaseModel):
    unit_id: int
    chart_path: str
    label: str


class PinChartResponse(BaseModel):
    pin_id: str
    unit_id: int
    chart_path: str
    label: str
    pinned_at: str


class DashboardResponse(BaseModel):
    pins: list[PinChartResponse]


# --- Report ---
class ReportResponse(BaseModel):
    report: str | None
    error: str | None = None
