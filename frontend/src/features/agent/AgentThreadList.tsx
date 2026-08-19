import { AsyncStatus, AgentThreadSummary } from "../../domain/types";

interface AgentThreadListProps {
  threads: AgentThreadSummary[];
  selectedThreadId: string | null;
  listStatus: AsyncStatus;
  listError: string | null;
  createStatus: AsyncStatus;
  createError: string | null;
  onSelect: (threadId: string) => void;
  onCreate: () => void;
  onRetry: () => void;
}

function formatUpdatedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Recently";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function messageLabel(count: number): string {
  return `${count} ${count === 1 ? "message" : "messages"}`;
}

export function AgentThreadList({
  threads,
  selectedThreadId,
  listStatus,
  listError,
  createStatus,
  createError,
  onSelect,
  onCreate,
  onRetry,
}: AgentThreadListProps): JSX.Element {
  const loading = listStatus === "loading";
  const creating = createStatus === "loading";

  return (
    <section className="agent-thread-section" aria-label="Agent conversations">
      <div className="agent-section-heading">
        <div>
          <p className="eyebrow">Project chats</p>
          <strong>{loading ? "Loading conversations" : `${threads.length} conversations`}</strong>
        </div>
        <button
          className="small-button"
          type="button"
          aria-label="New Agent chat"
          onClick={onCreate}
          disabled={loading || creating}
        >
          + New
        </button>
      </div>

      {listStatus === "error" ? (
        <div className="agent-resource-error" role="alert">
          <span>{listError ?? "Conversations could not be loaded."}</span>
          <button className="text-button" type="button" onClick={onRetry}>
            Retry
          </button>
        </div>
      ) : null}

      {loading ? (
        <div className="agent-thread-skeletons" aria-label="Loading conversations" role="status">
          <span />
          <span />
          <span />
        </div>
      ) : null}

      {!loading && listStatus !== "error" && threads.length > 0 ? (
        <div className="agent-thread-list" role="list">
          {threads.map((thread) => {
            const selected = thread.threadId === selectedThreadId;
            return (
              <button
                className={`agent-thread-item${selected ? " selected" : ""}`}
                key={thread.threadId}
                type="button"
                role="listitem"
                aria-current={selected ? "true" : undefined}
                onClick={() => onSelect(thread.threadId)}
                disabled={creating}
              >
                <span className="agent-thread-item-topline">
                  <strong>{thread.title}</strong>
                  <time dateTime={thread.updatedAt}>{formatUpdatedAt(thread.updatedAt)}</time>
                </span>
                <span className="agent-thread-item-meta">{messageLabel(thread.messageCount)}</span>
                {thread.preview ? <span className="agent-thread-preview">{thread.preview}</span> : null}
              </button>
            );
          })}
        </div>
      ) : null}

      {!loading && listStatus !== "error" && threads.length === 0 ? (
        <div className="agent-thread-empty">
          <p>No conversations yet.</p>
          <button className="text-button" type="button" onClick={onCreate} disabled={creating}>
            {creating ? "Creating..." : "Create a chat"}
          </button>
        </div>
      ) : null}

      {createError ? (
        <div className="agent-resource-error compact" role="alert">
          <span>{createError}</span>
          <button className="text-button" type="button" onClick={onCreate} disabled={creating}>
            Retry
          </button>
        </div>
      ) : null}
    </section>
  );
}
