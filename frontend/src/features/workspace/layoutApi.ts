import { apiFetch } from "../../api/client";
import { decodeWorkspaceLayout, WorkspaceLayout } from "../../domain/plan";

export function getWorkspaceLayout(
  projectId: string,
  signal?: AbortSignal,
): Promise<WorkspaceLayout> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace/layout`,
    { signal },
    decodeWorkspaceLayout,
  );
}

export function putWorkspaceLayout(
  projectId: string,
  layout: WorkspaceLayout,
  signal?: AbortSignal,
): Promise<WorkspaceLayout> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/workspace/layout`,
    { method: "PUT", body: JSON.stringify(layout), signal },
    decodeWorkspaceLayout,
  );
}
