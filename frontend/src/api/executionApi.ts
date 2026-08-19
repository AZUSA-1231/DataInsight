import { apiFetch } from "./client";

export interface ExecutionStatusResponse {
  status: string;
  progress: string | null;
  error: string | null;
}

export interface UnitResult {
  unitId: number;
  status: string;
  stdout: string;
  stderr: string;
  charts: string[];
  insights: string[];
  error: string | null;
  stale: boolean;
  runId: string | null;
  inputCheckpointIds: string[];
  outputCheckpointId: string | null;
  rowCountBefore: number | null;
  rowCountAfter: number | null;
  rowCountDelta: number | null;
  inputRowCounts: number[];
  statistics: Record<string, unknown>;
  warnings: Record<string, unknown>[];
}

export interface ExecutionResultsResponse {
  units: UnitResult[];
  status: string;
  runId: string | null;
  staleUnitIds: number[];
}

export interface RerunUnitResponse {
  unitId: number;
  status: string;
  staleUnits: number[];
  inputCheckpointIds: string[];
  outputCheckpointId: string | null;
  charts: string[];
  insights: string[];
  error: string | null;
  runId: string | null;
  rowCountBefore: number | null;
  rowCountAfter: number | null;
  rowCountDelta: number | null;
  warnings: Record<string, unknown>[];
}

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function objectValue(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid API response: ${field} must be an object`);
  }
  return value;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid API response: ${field} must be a string`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return stringValue(value, field);
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid API response: ${field} must be a finite number`);
  }
  return value;
}

function optionalNumber(value: unknown, field: string): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  return numberValue(value, field);
}

function booleanValue(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid API response: ${field} must be a boolean`);
  }
  return value;
}

function optionalBoolean(value: unknown, field: string, fallback: boolean): boolean {
  if (value === null || value === undefined) {
    return fallback;
  }
  return booleanValue(value, field);
}

function stringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid API response: ${field} must be an array of strings`);
  }
  return [...value];
}

function numberArray(value: unknown, field: string): number[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid API response: ${field} must be an array of numbers`);
  }
  return value.map((item, index) => numberValue(item, `${field}[${index}]`));
}

function objectArray(value: unknown, field: string): Record<string, unknown>[] {
  if (!Array.isArray(value) || value.some((item) => !isRecord(item))) {
    throw new Error(`Invalid API response: ${field} must be an array of objects`);
  }
  return value.map((item) => ({ ...item as Record<string, unknown> }));
}

function objectMap(value: unknown, field: string): Record<string, unknown> {
  return { ...objectValue(value, field) };
}

function decodeStatus(payload: unknown): ExecutionStatusResponse {
  const value = objectValue(payload, "execution status");
  return {
    status: stringValue(value.status, "status"),
    progress: optionalString(value.progress, "progress"),
    error: optionalString(value.error, "error"),
  };
}

function decodeUnitResult(payload: unknown, index: number): UnitResult {
  const value = objectValue(payload, `units[${index}]`);
  return {
    unitId: numberValue(value.unit_id, `units[${index}].unit_id`),
    status: stringValue(value.status, `units[${index}].status`),
    stdout: stringValue(value.stdout ?? "", `units[${index}].stdout`),
    stderr: stringValue(value.stderr ?? "", `units[${index}].stderr`),
    charts: stringArray(value.charts ?? [], `units[${index}].charts`),
    insights: stringArray(value.insights ?? [], `units[${index}].insights`),
    error: optionalString(value.error, `units[${index}].error`),
    stale: optionalBoolean(value.stale, `units[${index}].stale`, false),
    runId: optionalString(value.run_id, `units[${index}].run_id`),
    inputCheckpointIds: stringArray(
      value.input_checkpoint_ids ?? [],
      `units[${index}].input_checkpoint_ids`,
    ),
    outputCheckpointId: optionalString(
      value.output_checkpoint_id,
      `units[${index}].output_checkpoint_id`,
    ),
    rowCountBefore: optionalNumber(value.row_count_before, `units[${index}].row_count_before`),
    rowCountAfter: optionalNumber(value.row_count_after, `units[${index}].row_count_after`),
    rowCountDelta: optionalNumber(value.row_count_delta, `units[${index}].row_count_delta`),
    inputRowCounts: numberArray(
      value.input_row_counts ?? [],
      `units[${index}].input_row_counts`,
    ),
    statistics: objectMap(value.statistics ?? {}, `units[${index}].statistics`),
    warnings: objectArray(value.warnings ?? [], `units[${index}].warnings`),
  };
}

function decodeResults(payload: unknown): ExecutionResultsResponse {
  const value = objectValue(payload, "execution results");
  if (!Array.isArray(value.units)) {
    throw new Error("Invalid API response: units must be an array");
  }
  if (!Array.isArray(value.stale_unit_ids ?? [])) {
    throw new Error("Invalid API response: stale_unit_ids must be an array");
  }
  return {
    units: value.units.map((item, index) => decodeUnitResult(item, index)),
    status: stringValue(value.status ?? "idle", "status"),
    runId: optionalString(value.run_id, "run_id"),
    staleUnitIds: numberArray(value.stale_unit_ids ?? [], "stale_unit_ids"),
  };
}

function decodeRerun(payload: unknown): RerunUnitResponse {
  const value = objectValue(payload, "rerun response");
  return {
    unitId: numberValue(value.unit_id, "unit_id"),
    status: stringValue(value.status, "status"),
    staleUnits: numberArray(value.stale_units ?? [], "stale_units"),
    inputCheckpointIds: stringArray(value.input_checkpoint_ids ?? [], "input_checkpoint_ids"),
    outputCheckpointId: optionalString(value.output_checkpoint_id, "output_checkpoint_id"),
    charts: stringArray(value.charts ?? [], "charts"),
    insights: stringArray(value.insights ?? [], "insights"),
    error: optionalString(value.error, "error"),
    runId: optionalString(value.run_id, "run_id"),
    rowCountBefore: optionalNumber(value.row_count_before, "row_count_before"),
    rowCountAfter: optionalNumber(value.row_count_after, "row_count_after"),
    rowCountDelta: optionalNumber(value.row_count_delta, "row_count_delta"),
    warnings: objectArray(value.warnings ?? [], "warnings"),
  };
}

function projectPath(projectId: string, suffix: string): string {
  return `/api/sessions/${encodeURIComponent(projectId)}/execution${suffix}`;
}

export function startExecution(
  projectId: string,
  signal?: AbortSignal,
): Promise<{ status: string }> {
  return apiFetch(
    projectPath(projectId, "/run"),
    { method: "POST", signal },
    (payload) => {
      const value = objectValue(payload, "execution start response");
      return { status: stringValue(value.status, "status") };
    },
  );
}

export function getExecutionStatus(
  projectId: string,
  signal?: AbortSignal,
): Promise<ExecutionStatusResponse> {
  return apiFetch(projectPath(projectId, "/status"), { signal }, decodeStatus);
}

export function getExecutionResults(
  projectId: string,
  signal?: AbortSignal,
): Promise<ExecutionResultsResponse> {
  return apiFetch(projectPath(projectId, "/results"), { signal }, decodeResults);
}

export function rerunUnit(
  projectId: string,
  unitId: number,
  cascade = false,
  signal?: AbortSignal,
): Promise<RerunUnitResponse> {
  const query = cascade ? "?cascade=true" : "";
  return apiFetch(
    projectPath(projectId, `/units/${encodeURIComponent(String(unitId))}/rerun${query}`),
    { method: "POST", signal },
    decodeRerun,
  );
}

export function chartUrl(projectId: string, chartPath: string): string {
  const normalized = chartPath.trim();
  const segments = normalized.split("/");
  if (
    !normalized ||
    normalized.startsWith("/") ||
    segments.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    throw new Error("Chart reference must be a non-empty session-relative path");
  }
  const encodedPath = segments.map((segment) => encodeURIComponent(segment)).join("/");
  return `${API_BASE_URL}/api/sessions/${encodeURIComponent(projectId)}/execution/charts/${encodedPath}`;
}

export function isTerminalExecutionStatus(status: string): boolean {
  return (
    status === "idle" ||
    status === "complete" ||
    status === "completed" ||
    status === "partial" ||
    status === "failed"
  );
}
