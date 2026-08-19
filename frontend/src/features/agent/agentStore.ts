import {
  AgentThread,
  AgentThreadSummary,
  AsyncStatus,
  CopilotTurnResult,
} from "../../domain/types";

export interface ThreadDetailState {
  status: AsyncStatus;
  thread: AgentThread | null;
  error: string | null;
}

export interface AgentPanelState {
  projectId: string;
  listStatus: AsyncStatus;
  listError: string | null;
  threads: AgentThreadSummary[];
  selectedThreadId: string | null;
  details: Record<string, ThreadDetailState>;
  createStatus: AsyncStatus;
  createError: string | null;
  sendStatus: AsyncStatus;
  sendError: string | null;
  pendingMessage: string | null;
  retryMessage: string | null;
  lastTurn: CopilotTurnResult | null;
}

const emptyDetail = (status: AsyncStatus = "idle"): ThreadDetailState => ({
  status,
  thread: null,
  error: null,
});

export function createAgentPanelState(projectId: string): AgentPanelState {
  return {
    projectId,
    listStatus: "idle",
    listError: null,
    threads: [],
    selectedThreadId: null,
    details: {},
    createStatus: "idle",
    createError: null,
    sendStatus: "idle",
    sendError: null,
    pendingMessage: null,
    retryMessage: null,
    lastTurn: null,
  };
}

export type AgentPanelAction =
  | { type: "reset"; projectId: string }
  | { type: "list-loading" }
  | { type: "list-loaded"; threads: AgentThreadSummary[]; selectedThreadId: string | null }
  | { type: "list-refreshed"; threads: AgentThreadSummary[]; selectedThreadId: string | null }
  | { type: "list-failed"; error: string }
  | { type: "create-started" }
  | { type: "thread-created"; thread: AgentThread }
  | { type: "create-failed"; error: string }
  | { type: "thread-selected"; threadId: string }
  | { type: "detail-loading"; threadId: string }
  | { type: "detail-loaded"; thread: AgentThread }
  | { type: "detail-failed"; threadId: string; error: string }
  | { type: "send-started"; message: string }
  | { type: "send-finished"; result: CopilotTurnResult }
  | { type: "send-failed"; message: string; error: string }
  | { type: "send-cancelled" };

function replaceSummary(
  threads: AgentThreadSummary[],
  summary: AgentThreadSummary,
): AgentThreadSummary[] {
  const index = threads.findIndex((thread) => thread.threadId === summary.threadId);
  if (index === -1) {
    return [...threads, summary];
  }
  return threads.map((thread, itemIndex) => (itemIndex === index ? summary : thread));
}

export function agentReducer(
  state: AgentPanelState,
  action: AgentPanelAction,
): AgentPanelState {
  switch (action.type) {
    case "reset":
      return createAgentPanelState(action.projectId);
    case "list-loading":
      return {
        ...state,
        listStatus: "loading",
        listError: null,
        createError: null,
      };
    case "list-loaded":
      return {
        ...state,
        listStatus: "ready",
        listError: null,
        threads: action.threads,
        selectedThreadId: action.selectedThreadId,
        details: {},
        createStatus: "idle",
        createError: null,
        sendStatus: "idle",
        sendError: null,
        pendingMessage: null,
        retryMessage: null,
        lastTurn: null,
      };
    case "list-refreshed":
      return {
        ...state,
        listStatus: "ready",
        listError: null,
        threads: action.threads,
        selectedThreadId: action.selectedThreadId,
      };
    case "list-failed":
      return {
        ...state,
        listStatus: "error",
        listError: action.error,
      };
    case "create-started":
      return {
        ...state,
        createStatus: "loading",
        createError: null,
        selectedThreadId: null,
        details: {},
        sendStatus: "idle",
        sendError: null,
        pendingMessage: null,
        retryMessage: null,
        lastTurn: null,
      };
    case "thread-created":
      return {
        ...state,
        listStatus: "ready",
        listError: null,
        threads: replaceSummary(state.threads, action.thread),
        selectedThreadId: action.thread.threadId,
        details: {
          ...state.details,
          [action.thread.threadId]: {
            status: "ready",
            thread: action.thread,
            error: null,
          },
        },
        createStatus: "ready",
        createError: null,
        sendStatus: "idle",
        sendError: null,
        pendingMessage: null,
        retryMessage: null,
        lastTurn: null,
      };
    case "create-failed":
      return {
        ...state,
        createStatus: "error",
        createError: action.error,
      };
    case "thread-selected":
      return {
        ...state,
        selectedThreadId: action.threadId,
        details: {
          ...state.details,
          [action.threadId]: emptyDetail("loading"),
        },
        sendStatus: "idle",
        sendError: null,
        pendingMessage: null,
        retryMessage: null,
        lastTurn: null,
      };
    case "detail-loading":
      return {
        ...state,
        details: {
          ...state.details,
          [action.threadId]: emptyDetail("loading"),
        },
      };
    case "detail-loaded":
      return {
        ...state,
        details: {
          ...state.details,
          [action.thread.threadId]: {
            status: "ready",
            thread: action.thread,
            error: null,
          },
        },
        threads: replaceSummary(state.threads, action.thread),
      };
    case "detail-failed":
      return {
        ...state,
        details: {
          ...state.details,
          [action.threadId]: {
            status: "error",
            thread: null,
            error: action.error,
          },
        },
      };
    case "send-started":
      return {
        ...state,
        sendStatus: "loading",
        sendError: null,
        pendingMessage: action.message,
        retryMessage: null,
        lastTurn: null,
      };
    case "send-finished":
      return {
        ...state,
        sendStatus: "ready",
        sendError: null,
        pendingMessage: null,
        retryMessage: action.result.status === "error" ? state.pendingMessage : null,
        lastTurn: action.result,
      };
    case "send-failed":
      return {
        ...state,
        sendStatus: "error",
        sendError: action.error,
        pendingMessage: null,
        retryMessage: action.message,
      };
    case "send-cancelled":
      return {
        ...state,
        sendStatus: "idle",
        pendingMessage: null,
      };
    default:
      return state;
  }
}
