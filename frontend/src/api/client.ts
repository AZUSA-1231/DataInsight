import {
  ApiError,
  CreateProjectResponse,
  ProjectCreateInput,
  ProjectStateSummary,
  ProjectSummary,
  ProjectsResponse,
} from "../domain/types";
import { decodePlan, Plan } from "../domain/plan";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
const LAST_PROJECT_STORAGE_KEY = "datainsight:last-project-id";

type Decoder<T> = (payload: unknown) => T;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid API response: ${field} must be a string`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return requiredString(value, field);
}

function requiredNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid API response: ${field} must be a finite number`);
  }
  return value;
}

function requiredBoolean(value: unknown, field: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`Invalid API response: ${field} must be a boolean`);
  }
  return value;
}

function requiredObject(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid API response: ${field} must be an object`);
  }
  return value;
}

function decodeProjectSummary(payload: unknown): ProjectSummary {
  const value = requiredObject(payload, "project");
  return {
    projectId: requiredString(value.project_id, "project_id"),
    title: requiredString(value.title, "title"),
    createdAt: optionalString(value.created_at, "created_at"),
    persistedAt: optionalString(value.persisted_at, "persisted_at"),
    sourceCount: requiredNumber(value.source_count, "source_count"),
    unitCount: requiredNumber(value.unit_count, "unit_count"),
    hasResults: requiredBoolean(value.has_results, "has_results"),
    hasReport: requiredBoolean(value.has_report, "has_report"),
    agentChatCount: requiredNumber(value.agent_chat_count, "agent_chat_count"),
    status: optionalString(value.status, "status"),
  };
}

function decodeProjects(payload: unknown): ProjectsResponse {
  const value = requiredObject(payload, "projects response");
  if (!Array.isArray(value.projects)) {
    throw new Error("Invalid API response: projects must be an array");
  }
  return { projects: value.projects.map(decodeProjectSummary) };
}

function decodeCreateProject(payload: unknown): CreateProjectResponse {
  const value = requiredObject(payload, "create project response");
  return { sessionId: requiredString(value.session_id, "session_id") };
}

function decodeProjectState(payload: unknown): ProjectStateSummary {
  const value = requiredObject(payload, "project state");
  return {
    sessionId: requiredString(value.session_id, "session_id"),
    projectId: requiredString(value.project_id, "project_id"),
    schemaVersion: requiredNumber(value.schema_version, "schema_version"),
    title: requiredString(value.title, "title"),
    createdAt: optionalString(value.created_at, "created_at"),
    hasData: requiredBoolean(value.has_data, "has_data"),
    hasIntent: requiredBoolean(value.has_intent, "has_intent"),
    hasPlan: requiredBoolean(value.has_plan, "has_plan"),
    hasResults: requiredBoolean(value.has_results, "has_results"),
    hasReport: requiredBoolean(value.has_report, "has_report"),
    agentChatCount: requiredNumber(value.agent_chat_count, "agent_chat_count"),
    status: optionalString(value.status, "status"),
    error: optionalString(value.error, "error"),
    persistedAt: optionalString(value.persisted_at, "persisted_at"),
  };
}

export interface WorkspacePlanResponse {
  plan: Plan | null;
}

export interface WorkspaceUnitPatch {
  operation?: string;
  purpose?: string;
  model?: string | null;
  cautious?: string;
  execution_mode?: string;
  depends_on?: number[];
  input_snapshot?: string;
  input_columns?: string[];
  output_columns?: string[];
  output_snapshot?: string;
  inputs?: { role: "left" | "right"; snapshot: string }[];
  keys?: { left: string; right: string }[];
  select?: { from: string; as: string }[];
  how?: string;
  template_name?: string | null;
  template_params?: Record<string, unknown> | null;
  [key: string]: unknown;
}

function decodeWorkspacePlan(payload: unknown): WorkspacePlanResponse {
  const value = requiredObject(payload, "workspace plan");
  return { plan: decodePlan(value.plan) };
}

function detailMessage(payload: unknown, fallback: string): string {
  if (!isRecord(payload)) {
    return fallback;
  }
  const detail = payload.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (isRecord(detail) && typeof detail.message === "string") {
    return detail.message;
  }
  return fallback;
}

export async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
  decode: Decoder<T>,
): Promise<T> {
  const headers = new Headers(init.headers);
  const isFormDataBody =
    typeof FormData !== "undefined" && init.body instanceof FormData;
  if (init.body !== undefined && !isFormDataBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  const text = await response.text();
  let payload: unknown = null;
  if (text.trim()) {
    try {
      payload = JSON.parse(text) as unknown;
    } catch {
      payload = text;
    }
  }
  if (!response.ok) {
    throw new ApiError(
      detailMessage(payload, `Request failed with status ${response.status}`),
      response.status,
      isRecord(payload) ? payload.detail : payload,
    );
  }
  return decode(payload);
}

function jsonBody(value: unknown): string {
  return JSON.stringify(value);
}

export function listProjects(signal?: AbortSignal): Promise<ProjectsResponse> {
  return apiFetch("/api/sessions", { signal }, decodeProjects);
}

export function getProject(
  projectId: string,
  signal?: AbortSignal,
): Promise<ProjectStateSummary> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}`,
    { signal },
    decodeProjectState,
  );
}

export function createProject(
  input: ProjectCreateInput = {},
  signal?: AbortSignal,
): Promise<CreateProjectResponse> {
  return apiFetch(
    "/api/sessions",
    {
      method: "POST",
      body: jsonBody({
        title: input.title,
        user_requirement: input.userRequirement ?? "",
      }),
      signal,
    },
    decodeCreateProject,
  );
}

export function renameProject(
  projectId: string,
  title: string,
  signal?: AbortSignal,
): Promise<ProjectSummary> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}`,
    { method: "PATCH", body: jsonBody({ title }), signal },
    decodeProjectSummary,
  );
}

export function getWorkspace(
  projectId: string,
  signal?: AbortSignal,
): Promise<WorkspacePlanResponse> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace`,
    { signal },
    decodeWorkspacePlan,
  );
}

export function updateWorkspaceUnit(
  projectId: string,
  unitId: number,
  patch: WorkspaceUnitPatch,
  signal?: AbortSignal,
): Promise<WorkspacePlanResponse> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace/units/${unitId}`,
    { method: "PUT", body: jsonBody(patch), signal },
    decodeWorkspacePlan,
  );
}

export function createWorkspaceUnit(
  projectId: string,
  payload: WorkspaceUnitPatch,
  signal?: AbortSignal,
): Promise<WorkspacePlanResponse> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace/units`,
    { method: "POST", body: jsonBody(payload), signal },
    decodeWorkspacePlan,
  );
}

export function deleteWorkspaceUnit(
  projectId: string,
  unitId: number,
  cascade = false,
  signal?: AbortSignal,
): Promise<WorkspacePlanResponse> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace/units/${unitId}?cascade=${cascade ? "true" : "false"}`,
    { method: "DELETE", signal },
    decodeWorkspacePlan,
  );
}

export function readLastProjectId(): string | null {
  try {
    return window.localStorage.getItem(LAST_PROJECT_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function writeLastProjectId(projectId: string): void {
  try {
    window.localStorage.setItem(LAST_PROJECT_STORAGE_KEY, projectId);
  } catch {
    // Browser storage is only a convenience; the server remains authoritative.
  }
}

export function projectPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

export function projectIdFromPath(pathname: string): string | null {
  const match = /^\/projects\/([0-9a-f]{32})\/?$/i.exec(pathname);
  return match?.[1] ?? null;
}
