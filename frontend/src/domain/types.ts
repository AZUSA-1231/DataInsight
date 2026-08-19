export type ProjectStatus = string | null;

export interface ProjectSummary {
  projectId: string;
  title: string;
  createdAt: string | null;
  persistedAt: string | null;
  sourceCount: number;
  unitCount: number;
  hasResults: boolean;
  hasReport: boolean;
  agentChatCount: number;
  status: ProjectStatus;
}

export interface ProjectStateSummary {
  sessionId: string;
  projectId: string;
  schemaVersion: number;
  title: string;
  createdAt: string | null;
  hasData: boolean;
  hasIntent: boolean;
  hasPlan: boolean;
  hasResults: boolean;
  hasReport: boolean;
  agentChatCount: number;
  status: ProjectStatus;
  error: string | null;
  persistedAt: string | null;
}

export interface ProjectsResponse {
  projects: ProjectSummary[];
}

export interface CreateProjectResponse {
  sessionId: string;
}

export interface ProjectCreateInput {
  title?: string;
  userRequirement?: string;
}

export type AgentMessageRole = "user" | "assistant";

export interface AgentChatMessage {
  role: AgentMessageRole;
  content: string;
  createdAt: string;
}

export interface AgentThreadSummary {
  threadId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  messageCount: number;
  preview: string | null;
}

export interface AgentThread extends AgentThreadSummary {
  messages: AgentChatMessage[];
}

export type CopilotTurnStatus = "complete" | "incomplete" | "error";

export interface CopilotToolResult {
  name: string;
  callId: string;
  status: "success" | "error";
  content: string;
}

export interface CopilotTurnResult {
  status: CopilotTurnStatus;
  message: string;
  skill: string | null;
  toolResults: CopilotToolResult[];
  toolRounds: number;
  modelCalls: number;
  error: string | null;
}

export interface ApiErrorDetail {
  code?: string;
  message?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: unknown;

  constructor(message: string, status: number, detail: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type AsyncStatus = "idle" | "loading" | "ready" | "error";

export interface AsyncResource<T> {
  status: AsyncStatus;
  value: T | null;
  error: ApiError | Error | null;
}
