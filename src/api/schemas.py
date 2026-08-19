from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from src.agent.state import AgentChatMessage, Plan, WorkspaceLayout


# --- Session ---
class SessionCreateRequest(BaseModel):
    user_requirement: str = ""
    title: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value.strip() if value is not None else None


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionStateResponse(BaseModel):
    session_id: str
    project_id: str
    schema_version: int = 2
    title: str
    created_at: str | None = None
    has_data: bool
    has_intent: bool
    has_plan: bool
    has_results: bool
    has_report: bool
    agent_chat_count: int = 0
    status: str | None = None
    error: str | None = None
    persisted_at: str | None = None


class ProjectSummaryResponse(BaseModel):
    project_id: str
    title: str
    created_at: str | None = None
    persisted_at: str | None = None
    source_count: int = 0
    unit_count: int = 0
    has_results: bool = False
    has_report: bool = False
    agent_chat_count: int = 0
    status: str | None = None


class ProjectsResponse(BaseModel):
    projects: list[ProjectSummaryResponse] = Field(default_factory=list)


class ProjectRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def _title_must_not_be_blank(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("title must not be blank")
        return title


class AgentChatMessageResponse(BaseModel):
    role: str
    content: str
    created_at: str

    @classmethod
    def from_message(cls, message: AgentChatMessage) -> AgentChatMessageResponse:
        return cls(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )


class AgentThreadSummaryResponse(BaseModel):
    thread_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int = 0
    preview: str | None = None


class AgentThreadsResponse(BaseModel):
    threads: list[AgentThreadSummaryResponse] = Field(default_factory=list)


class AgentThreadResponse(AgentThreadSummaryResponse):
    messages: list[AgentChatMessageResponse] = Field(default_factory=list)


class AgentThreadCreateRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)

    @field_validator("title")
    @classmethod
    def _thread_title_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("title must not be blank")
        return value.strip() if value is not None else None


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


class WorkspaceSnapshotViewResponse(BaseModel):
    """One materialized or Plan-derived logical Snapshot view."""

    view_id: str
    snapshot_id: str | None = None
    name: str
    display_name: str
    row_count: int | None = None
    column_refs: list[str] = Field(default_factory=list)
    source_id: str | None = None
    created_by_unit_id: int | None = None
    parent_snapshot_names: list[str] = Field(default_factory=list)
    availability: Literal["materialized", "planned"]
    profile_available: bool


class WorkspaceColumnViewResponse(BaseModel):
    """One public column fact, including nullable Plan-time facts."""

    ref: str
    name: str
    snapshot: str
    dtype: str | None = None
    null_count: int | None = None
    null_pct: float | None = None
    source_column: str | None = None
    created_by_unit_id: int | None = None
    availability: Literal["materialized", "planned"]


class WorkspaceDataProjectionResponse(BaseModel):
    """One coherent Explorer catalog projection."""

    sources: list[SourceResponse] = Field(default_factory=list)
    snapshots: list[WorkspaceSnapshotViewResponse] = Field(default_factory=list)
    columns: list[WorkspaceColumnViewResponse] = Field(default_factory=list)
    lineage: list[LineageColumnResponse] = Field(default_factory=list)
    compatibility_warning: str | None = None


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


class WorkspaceLayoutResponse(WorkspaceLayout):
    """Presentation-only layout returned by the Project workspace API."""


class GeneratePlanRequest(BaseModel):
    instruction: dict[str, object] | None = None


# --- Dialogue ---
class DialogueRequest(BaseModel):
    message: str


class CopilotTurnRequest(BaseModel):
    """One bounded Copilot request from the active chat surface."""

    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator("message")
    @classmethod
    def _message_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


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
