import { useCallback, useEffect, useReducer, useRef } from "react";

import {
  createAgentThread,
  getAgentThread,
  listAgentThreads,
  sendCopilotTurn,
} from "../../api/agentApi";
import { ApiError, AgentThread, AgentThreadSummary } from "../../domain/types";
import { MAX_AGENT_MESSAGE_LENGTH } from "./agentConstants";
import { Composer } from "./Composer";
import { AgentThreadList } from "./AgentThreadList";
import {
  agentReducer,
  createAgentPanelState,
  AgentPanelState,
} from "./agentStore";
import { MessageHistory } from "./MessageHistory";

interface AgentPanelProps {
  projectId: string;
}

type ThreadRequest = (projectId: string, threadId: string, generation: number) => void;

function describeAgentError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) {
      return "This Agent Thread is no longer available.";
    }
    if (error.status === 422) {
      return "The message was rejected by the local workspace.";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "The Agent request failed.";
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

export function AgentPanel({ projectId }: AgentPanelProps): JSX.Element {
  const [state, dispatch] = useReducer(
    agentReducer,
    projectId,
    createAgentPanelState,
  );
  const projectRef = useRef(projectId);
  const selectedThreadRef = useRef<string | null>(null);
  const generationRef = useRef(0);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const createController = useRef<AbortController | null>(null);
  const sendController = useRef<AbortController | null>(null);
  const loadDetailRef = useRef<ThreadRequest>(() => undefined);
  const reloadProjectRef = useRef<(projectId: string) => void>(() => undefined);

  projectRef.current = projectId;

  const nextGeneration = useCallback((): number => {
    generationRef.current += 1;
    return generationRef.current;
  }, []);

  const abortRequests = useCallback((): void => {
    listController.current?.abort();
    detailController.current?.abort();
    createController.current?.abort();
    sendController.current?.abort();
    listController.current = null;
    detailController.current = null;
    createController.current = null;
    sendController.current = null;
  }, []);

  const isCurrentProjectGeneration = useCallback(
    (targetProjectId: string, generation: number): boolean =>
      projectRef.current === targetProjectId && generationRef.current === generation,
    [],
  );

  const isCurrentResource = useCallback(
    (targetProjectId: string, threadId: string, generation: number): boolean =>
      isCurrentProjectGeneration(targetProjectId, generation) &&
      selectedThreadRef.current === threadId,
    [isCurrentProjectGeneration],
  );

  const loadThreadDetail = useCallback(
    async (targetProjectId: string, threadId: string, generation: number): Promise<void> => {
      detailController.current?.abort();
      const controller = new AbortController();
      detailController.current = controller;
      dispatch({ type: "detail-loading", threadId });
      try {
        const thread = await getAgentThread(targetProjectId, threadId, controller.signal);
        if (
          controller.signal.aborted ||
          !isCurrentResource(targetProjectId, threadId, generation)
        ) {
          return;
        }
        dispatch({ type: "detail-loaded", thread });
      } catch (error) {
        if (
          controller.signal.aborted ||
          isAbortError(error) ||
          !isCurrentResource(targetProjectId, threadId, generation)
        ) {
          return;
        }
        if (error instanceof ApiError && error.status === 404) {
          reloadProjectRef.current(targetProjectId);
          return;
        }
        dispatch({
          type: "detail-failed",
          threadId,
          error: describeAgentError(error),
        });
      }
    },
    [isCurrentResource],
  );

  loadDetailRef.current = (targetProjectId, threadId, generation) => {
    void loadThreadDetail(targetProjectId, threadId, generation);
  };

  const loadProjectThreads = useCallback(
    async (targetProjectId: string, generation: number): Promise<void> => {
      const controller = new AbortController();
      listController.current = controller;
      dispatch({ type: "list-loading" });

      let threads: AgentThreadSummary[];
      try {
        threads = await listAgentThreads(targetProjectId, controller.signal);
      } catch (error) {
        if (
          controller.signal.aborted ||
          isAbortError(error) ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        dispatch({ type: "list-failed", error: describeAgentError(error) });
        return;
      }

      if (
        controller.signal.aborted ||
        !isCurrentProjectGeneration(targetProjectId, generation)
      ) {
        return;
      }

      if (threads.length > 0) {
        const firstThreadId = threads[0].threadId;
        selectedThreadRef.current = firstThreadId;
        dispatch({
          type: "list-loaded",
          threads,
          selectedThreadId: firstThreadId,
        });
        loadDetailRef.current(targetProjectId, firstThreadId, generation);
        return;
      }

      dispatch({ type: "list-loaded", threads: [], selectedThreadId: null });
      dispatch({ type: "create-started" });
      try {
        const created = await createAgentThread(targetProjectId, undefined, controller.signal);
        if (
          controller.signal.aborted ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        selectedThreadRef.current = created.threadId;
        dispatch({ type: "thread-created", thread: created });
      } catch (error) {
        if (
          controller.signal.aborted ||
          isAbortError(error) ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        dispatch({ type: "create-failed", error: describeAgentError(error) });
      }
    },
    [isCurrentProjectGeneration],
  );

  const startProjectLoad = useCallback(
    (targetProjectId: string): void => {
      const generation = nextGeneration();
      abortRequests();
      selectedThreadRef.current = null;
      dispatch({ type: "reset", projectId: targetProjectId });
      void loadProjectThreads(targetProjectId, generation);
    },
    [abortRequests, loadProjectThreads, nextGeneration],
  );

  reloadProjectRef.current = startProjectLoad;

  const refreshThreadSummaries = useCallback(
    async (targetProjectId: string, generation: number): Promise<void> => {
      listController.current?.abort();
      const controller = new AbortController();
      listController.current = controller;
      try {
        const threads = await listAgentThreads(targetProjectId, controller.signal);
        if (
          controller.signal.aborted ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        const currentThreadId = selectedThreadRef.current;
        const selectedThread = currentThreadId
          ? threads.find((thread) => thread.threadId === currentThreadId)
          : undefined;
        if (selectedThread) {
          dispatch({
            type: "list-refreshed",
            threads,
            selectedThreadId: selectedThread.threadId,
          });
          return;
        }
        const fallback = threads[0];
        if (!fallback) {
          startProjectLoad(targetProjectId);
          return;
        }
        selectedThreadRef.current = fallback.threadId;
        dispatch({
          type: "list-refreshed",
          threads,
          selectedThreadId: fallback.threadId,
        });
        loadDetailRef.current(targetProjectId, fallback.threadId, generation);
      } catch (error) {
        if (
          controller.signal.aborted ||
          isAbortError(error) ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        dispatch({ type: "list-failed", error: describeAgentError(error) });
      }
    },
    [isCurrentProjectGeneration, startProjectLoad],
  );

  useEffect(() => {
    startProjectLoad(projectId);
    return () => {
      nextGeneration();
      abortRequests();
    };
  }, [abortRequests, nextGeneration, projectId, startProjectLoad]);

  const handleSelectThread = useCallback(
    (threadId: string): void => {
      if (selectedThreadRef.current === threadId) {
        return;
      }
      const generation = nextGeneration();
      abortRequests();
      selectedThreadRef.current = threadId;
      dispatch({ type: "thread-selected", threadId });
      loadDetailRef.current(projectRef.current, threadId, generation);
    },
    [abortRequests, nextGeneration],
  );

  const handleRetryDetail = useCallback((): void => {
    const threadId = selectedThreadRef.current;
    if (!threadId) {
      return;
    }
    const generation = nextGeneration();
    abortRequests();
    dispatch({ type: "thread-selected", threadId });
    loadDetailRef.current(projectRef.current, threadId, generation);
  }, [abortRequests, nextGeneration]);

  const handleCreateThread = useCallback((): void => {
    if (createController.current || state.createStatus === "loading") {
      return;
    }
    const targetProjectId = projectRef.current;
    const generation = nextGeneration();
    abortRequests();
    selectedThreadRef.current = null;
    dispatch({ type: "create-started" });
    const controller = new AbortController();
    createController.current = controller;
    void createAgentThread(targetProjectId, undefined, controller.signal)
      .then((thread: AgentThread) => {
        if (
          controller.signal.aborted ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        createController.current = null;
        selectedThreadRef.current = thread.threadId;
        dispatch({ type: "thread-created", thread });
      })
      .catch((error: unknown) => {
        if (
          controller.signal.aborted ||
          isAbortError(error) ||
          !isCurrentProjectGeneration(targetProjectId, generation)
        ) {
          return;
        }
        createController.current = null;
        dispatch({ type: "create-failed", error: describeAgentError(error) });
      });
  }, [abortRequests, isCurrentProjectGeneration, nextGeneration, state.createStatus]);

  const handleCancelSend = useCallback((): void => {
    if (!sendController.current) {
      return;
    }
    nextGeneration();
    abortRequests();
    dispatch({ type: "send-cancelled" });
  }, [abortRequests, nextGeneration]);

  const handleSubmit = useCallback(
    (message: string): void => {
      const targetProjectId = projectRef.current;
      const threadId = selectedThreadRef.current;
      if (
        !threadId ||
        sendController.current ||
        !message.trim() ||
        message.length > MAX_AGENT_MESSAGE_LENGTH
      ) {
        return;
      }

      const generation = nextGeneration();
      abortRequests();
      const controller = new AbortController();
      sendController.current = controller;
      dispatch({ type: "send-started", message });
      void sendCopilotTurn(targetProjectId, threadId, message, controller.signal)
        .then((result) => {
          if (
            controller.signal.aborted ||
            !isCurrentResource(targetProjectId, threadId, generation)
          ) {
            return;
          }
          sendController.current = null;
          dispatch({ type: "send-finished", result });
          loadDetailRef.current(targetProjectId, threadId, generation);
          void refreshThreadSummaries(targetProjectId, generation);
        })
        .catch((error: unknown) => {
          if (
            controller.signal.aborted ||
            isAbortError(error) ||
            !isCurrentResource(targetProjectId, threadId, generation)
          ) {
            return;
          }
          sendController.current = null;
          dispatch({
            type: "send-failed",
            message,
            error: describeAgentError(error),
          });
          if (error instanceof ApiError && error.status === 404) {
            startProjectLoad(targetProjectId);
          }
        });
    },
    [
      abortRequests,
      isCurrentResource,
      nextGeneration,
      refreshThreadSummaries,
      startProjectLoad,
    ],
  );

  const handleRetrySend = useCallback((): void => {
    if (state.retryMessage) {
      handleSubmit(state.retryMessage);
    }
  }, [handleSubmit, state.retryMessage]);

  const viewState: AgentPanelState =
    state.projectId === projectId ? state : createAgentPanelState(projectId);
  const selectedThreadId = viewState.selectedThreadId;
  const detail = selectedThreadId ? viewState.details[selectedThreadId] : undefined;
  const composerDisabled =
    !selectedThreadId || viewState.listStatus !== "ready" || detail?.status !== "ready";

  return (
    <section className="agent-panel" aria-label="Project Agent">
      <header className="agent-panel-header">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Agent</p>
            <h2>Conversations</h2>
          </div>
          <span className="count-badge">{viewState.threads.length}</span>
        </div>
        <p className="agent-panel-subtitle">Project-local Threads</p>
      </header>
      <AgentThreadList
        threads={viewState.threads}
        selectedThreadId={selectedThreadId}
        listStatus={viewState.listStatus}
        listError={viewState.listError}
        createStatus={viewState.createStatus}
        createError={viewState.createError}
        onSelect={handleSelectThread}
        onCreate={handleCreateThread}
        onRetry={() => startProjectLoad(projectRef.current)}
      />
      <div className="agent-conversation">
        <MessageHistory
          detail={detail}
          lastTurn={viewState.lastTurn}
          onRetry={handleRetryDetail}
        />
        <Composer
          resetKey={`${projectId}:${selectedThreadId ?? "none"}`}
          disabled={composerDisabled}
          busy={viewState.sendStatus === "loading"}
          error={viewState.sendError}
          canRetry={Boolean(viewState.retryMessage)}
          onSubmit={handleSubmit}
          onCancel={handleCancelSend}
          onRetry={handleRetrySend}
        />
      </div>
    </section>
  );
}
