import { useEffect, useRef } from "react";

import { AgentChatMessage, CopilotTurnResult } from "../../domain/types";
import { ThreadDetailState } from "./agentStore";

interface MessageHistoryProps {
  detail: ThreadDetailState | undefined;
  lastTurn: CopilotTurnResult | null;
  onRetry: () => void;
}

function formatMessageTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return new Intl.DateTimeFormat(undefined, {
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function TurnMarker({ turn }: { turn: CopilotTurnResult }): JSX.Element {
  const statusLabel =
    turn.status === "complete"
      ? "Turn complete"
      : turn.status === "incomplete"
        ? "Turn reached the bounded limit"
        : "Turn returned an error";
  const toolLabel =
    turn.toolRounds > 0
      ? `${turn.toolRounds} tool ${turn.toolRounds === 1 ? "round" : "rounds"}`
      : null;

  return (
    <div className={`agent-turn-marker ${turn.status}`} role="status">
      <div className="agent-turn-marker-heading">
        <strong>{statusLabel}</strong>
        {turn.skill ? <span>/{turn.skill}</span> : null}
      </div>
      <span>
        {[toolLabel, turn.modelCalls > 0 ? `${turn.modelCalls} model calls` : null]
          .filter(Boolean)
          .join(" · ") || "Informational response"}
      </span>
      {turn.status === "error" && turn.error ? <small>{turn.error}</small> : null}
    </div>
  );
}

function MessageItem({ message }: { message: AgentChatMessage }): JSX.Element {
  const isUser = message.role === "user";
  return (
    <li className={`agent-message ${message.role}`}>
      <div className="agent-message-meta">
        <strong>{isUser ? "You" : "Agent"}</strong>
        {formatMessageTime(message.createdAt) ? (
          <time dateTime={message.createdAt}>{formatMessageTime(message.createdAt)}</time>
        ) : null}
      </div>
      <p>{message.content}</p>
    </li>
  );
}

export function MessageHistory({ detail, lastTurn, onRetry }: MessageHistoryProps): JSX.Element {
  const historyRef = useRef<HTMLDivElement | null>(null);
  const threadId = detail?.thread?.threadId ?? null;
  const messageCount = detail?.thread?.messages.length ?? 0;

  useEffect(() => {
    const element = historyRef.current;
    if (element) {
      element.scrollTop = element.scrollHeight;
    }
  }, [threadId, messageCount, detail?.status]);

  return (
    <div className="agent-history" ref={historyRef} aria-live="polite">
      {!detail || detail.status === "idle" || detail.status === "loading" ? (
        <div className="agent-history-loading" role="status">
          <span />
          <span />
          <span />
          <p>Loading Thread history...</p>
        </div>
      ) : null}

      {detail?.status === "error" ? (
        <div className="agent-history-error" role="alert">
          <strong>Thread history unavailable</strong>
          <p>{detail.error ?? "This conversation could not be reloaded."}</p>
          <button className="secondary-button" type="button" onClick={onRetry}>
            Retry history
          </button>
        </div>
      ) : null}

      {detail?.status === "ready" && detail.thread ? (
        detail.thread.messages.length > 0 ? (
          <ol className="agent-message-list">
            {detail.thread.messages.map((message, index) => (
              <MessageItem key={`${message.createdAt}-${index}`} message={message} />
            ))}
          </ol>
        ) : (
          <div className="agent-history-empty">
            <div className="agent-avatar" aria-hidden="true">
              AI
            </div>
            <strong>Start a conversation</strong>
            <p>Ask about the data or the current Plan.</p>
          </div>
        )
      ) : null}

      {lastTurn ? <TurnMarker turn={lastTurn} /> : null}
    </div>
  );
}
