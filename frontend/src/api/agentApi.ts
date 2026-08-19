import { apiFetch } from "./client";
import {
  AgentChatMessage,
  AgentMessageRole,
  AgentThread,
  AgentThreadSummary,
  CopilotToolResult,
  CopilotTurnResult,
} from "../domain/types";

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

function arrayValue(value: unknown, field: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid API response: ${field} must be an array`);
  }
  return value;
}

function decodeMessage(value: unknown, index: number): AgentChatMessage {
  const item = objectValue(value, `messages[${index}]`);
  const role = stringValue(item.role, `messages[${index}].role`);
  if (role !== "user" && role !== "assistant") {
    throw new Error(`Invalid API response: messages[${index}].role is unsupported`);
  }
  return {
    role: role as AgentMessageRole,
    content: stringValue(item.content, `messages[${index}].content`),
    createdAt: stringValue(item.created_at, `messages[${index}].created_at`),
  };
}

function decodeThreadSummary(value: unknown, field: string): AgentThreadSummary {
  const item = objectValue(value, field);
  return {
    threadId: stringValue(item.thread_id, `${field}.thread_id`),
    title: stringValue(item.title, `${field}.title`),
    createdAt: stringValue(item.created_at, `${field}.created_at`),
    updatedAt: stringValue(item.updated_at, `${field}.updated_at`),
    messageCount: numberValue(item.message_count, `${field}.message_count`),
    preview: optionalString(item.preview, `${field}.preview`),
  };
}

function decodeThread(value: unknown, field = "thread"): AgentThread {
  const item = objectValue(value, field);
  const summary = decodeThreadSummary(item, field);
  const messages = arrayValue(item.messages, `${field}.messages`).map(decodeMessage);
  return { ...summary, messages };
}

function decodeThreadList(payload: unknown): AgentThreadSummary[] {
  const value = objectValue(payload, "agent threads response");
  return arrayValue(value.threads, "threads").map((item, index) =>
    decodeThreadSummary(item, `threads[${index}]`),
  );
}

function decodeToolResult(value: unknown, index: number): CopilotToolResult {
  const item = objectValue(value, `tool_results[${index}]`);
  const status = stringValue(item.status, `tool_results[${index}].status`);
  if (status !== "success" && status !== "error") {
    throw new Error(`Invalid API response: tool_results[${index}].status is unsupported`);
  }
  return {
    name: stringValue(item.name, `tool_results[${index}].name`),
    callId: stringValue(item.call_id, `tool_results[${index}].call_id`),
    status,
    content: stringValue(item.content, `tool_results[${index}].content`),
  };
}

function decodeCopilotTurn(payload: unknown): CopilotTurnResult {
  const value = objectValue(payload, "copilot response");
  const status = stringValue(value.status, "status");
  if (status !== "complete" && status !== "incomplete" && status !== "error") {
    throw new Error("Invalid API response: status is unsupported");
  }
  const rawTools = arrayValue(value.tool_results, "tool_results");
  return {
    status,
    message: stringValue(value.message, "message"),
    skill: optionalString(value.skill, "skill"),
    toolResults: rawTools.map(decodeToolResult),
    toolRounds: numberValue(value.tool_rounds, "tool_rounds"),
    modelCalls: numberValue(value.model_calls, "model_calls"),
    error: optionalString(value.error, "error"),
  };
}

function projectAgentPath(projectId: string): string {
  return `/api/sessions/${encodeURIComponent(projectId)}/agent-chats`;
}

export function listAgentThreads(
  projectId: string,
  signal?: AbortSignal,
): Promise<AgentThreadSummary[]> {
  return apiFetch(projectAgentPath(projectId), { signal }, decodeThreadList);
}

export function createAgentThread(
  projectId: string,
  title?: string,
  signal?: AbortSignal,
): Promise<AgentThread> {
  const body = title === undefined ? {} : { title };
  return apiFetch(
    projectAgentPath(projectId),
    { method: "POST", body: JSON.stringify(body), signal },
    (payload) => decodeThread(payload, "created thread"),
  );
}

export function getAgentThread(
  projectId: string,
  threadId: string,
  signal?: AbortSignal,
): Promise<AgentThread> {
  return apiFetch(
    `${projectAgentPath(projectId)}/${encodeURIComponent(threadId)}`,
    { signal },
    (payload) => decodeThread(payload),
  );
}

export function sendCopilotTurn(
  projectId: string,
  threadId: string,
  message: string,
  signal?: AbortSignal,
): Promise<CopilotTurnResult> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/copilot`,
    {
      method: "POST",
      body: JSON.stringify({ thread_id: threadId, message }),
      signal,
    },
    decodeCopilotTurn,
  );
}
