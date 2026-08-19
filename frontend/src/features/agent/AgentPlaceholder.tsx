interface AgentPlaceholderProps {
  threadCount: number;
}

export function AgentPlaceholder({ threadCount }: AgentPlaceholderProps): JSX.Element {
  return (
    <div className="placeholder-panel agent-placeholder">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Agent</p>
          <h2>Conversations</h2>
        </div>
        <span className="count-badge">{threadCount}</span>
      </div>
      <div className="agent-preview-card">
        <div className="agent-avatar" aria-hidden="true">
          AI
        </div>
        <div>
          <strong>Thread-aware Agent panel</strong>
          <p>Conversation resources arrive in M5.</p>
        </div>
      </div>
      <div className="thread-skeletons" aria-hidden="true">
        <span />
        <span />
        <span />
      </div>
      <div className="agent-empty-copy">
        <p>Project facts will be shared here while conversation messages stay isolated per Thread.</p>
        <button type="button" disabled>
          + New Agent chat
        </button>
      </div>
    </div>
  );
}
