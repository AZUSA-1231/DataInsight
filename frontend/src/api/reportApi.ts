import { apiFetch } from "./client";

export interface ReportResponse {
  report: string | null;
  error: string | null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function decodeReport(payload: unknown): ReportResponse {
  if (!isRecord(payload)) {
    throw new Error("Invalid API response: report must be an object");
  }
  const report = payload.report;
  const error = payload.error;
  if (report !== null && report !== undefined && typeof report !== "string") {
    throw new Error("Invalid API response: report must be a string or null");
  }
  if (error !== null && error !== undefined && typeof error !== "string") {
    throw new Error("Invalid API response: error must be a string or null");
  }
  return {
    report: report === undefined ? null : report,
    error: error === undefined ? null : error,
  };
}

function reportPath(projectId: string): string {
  return `/api/sessions/${encodeURIComponent(projectId)}/report`;
}

export function getReport(projectId: string, signal?: AbortSignal): Promise<ReportResponse> {
  return apiFetch(reportPath(projectId), { signal }, decodeReport);
}

export function generateReport(projectId: string, signal?: AbortSignal): Promise<ReportResponse> {
  return apiFetch(
    `${reportPath(projectId)}/generate`,
    { method: "POST", signal },
    decodeReport,
  );
}
