from __future__ import annotations

from pydantic import BaseModel

from src.agent.state import Plan


# --- Session ---
class SessionCreateRequest(BaseModel):
    user_requirement: str = ""


class SessionCreateResponse(BaseModel):
    session_id: str


class SessionStateResponse(BaseModel):
    session_id: str
    has_data: bool
    has_intent: bool
    has_plan: bool
    has_results: bool
    has_report: bool
    error: str | None = None


# --- Data Pool ---
class ColumnInfoResponse(BaseModel):
    name: str
    dtype: str
    null_count: int
    null_pct: float


class DataProfileResponse(BaseModel):
    file_path: str
    shape: tuple[int, int]
    columns: list[ColumnInfoResponse]
    encoding: str | None = None


class DataUploadResponse(BaseModel):
    file_name: str
    row_count: int
    col_count: int
    unified_columns: list[str]


# --- Workspace ---
class UnitCreateRequest(BaseModel):
    purpose: str = ""
    model: str | None = None
    cautious: str = ""
    related_fields: list[str] = []


class UnitUpdateRequest(BaseModel):
    purpose: str | None = None
    model: str | None = None
    cautious: str | None = None
    related_fields: list[str] | None = None


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


class ExecutionResultResponse(BaseModel):
    units: list[UnitResultResponse]


class RerunUnitResponse(BaseModel):
    unit_id: int
    status: str
    stale_units: list[int] = []
    charts: list[str] = []
    insights: list[str] = []
    error: str | None = None


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
