import { useEffect, useState } from "react";

import { MAX_AGENT_MESSAGE_LENGTH } from "./agentConstants";

interface ComposerProps {
  resetKey: string;
  disabled: boolean;
  busy: boolean;
  error: string | null;
  canRetry: boolean;
  onSubmit: (message: string) => void;
  onCancel: () => void;
  onRetry: () => void;
}

export function Composer({
  resetKey,
  disabled,
  busy,
  error,
  canRetry,
  onSubmit,
  onCancel,
  onRetry,
}: ComposerProps): JSX.Element {
  const [draft, setDraft] = useState("");

  useEffect(() => {
    setDraft("");
  }, [resetKey]);

  const normalized = draft.trim();
  const tooLong = draft.length > MAX_AGENT_MESSAGE_LENGTH;
  const submitDisabled = disabled || busy || !normalized || tooLong;

  const submit = (): void => {
    if (submitDisabled) {
      return;
    }
    onSubmit(normalized);
    setDraft("");
  };

  return (
    <div className="agent-composer">
      {error ? (
        <div className="agent-send-error" role="alert">
          <span>{error}</span>
          {canRetry ? (
            <button className="text-button" type="button" onClick={onRetry} disabled={busy}>
              Retry
            </button>
          ) : null}
        </div>
      ) : null}
      {canRetry && !error ? (
        <div className="agent-retry-row">
          <span>The last turn did not complete.</span>
          <button className="text-button" type="button" onClick={onRetry} disabled={busy}>
            Retry
          </button>
        </div>
      ) : null}
      <textarea
        aria-label="Message Agent"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault();
            submit();
          }
        }}
        placeholder={disabled ? "Select a Thread to start" : "Ask about this Project..."}
        rows={3}
        maxLength={MAX_AGENT_MESSAGE_LENGTH}
        disabled={disabled || busy}
      />
      <div className="agent-composer-footer">
        <span className={tooLong ? "over-limit" : ""}>
          {draft.length}/{MAX_AGENT_MESSAGE_LENGTH}
        </span>
        {busy ? (
          <button className="secondary-button" type="button" onClick={onCancel}>
            Cancel
          </button>
        ) : (
          <button className="primary-button" type="button" onClick={submit} disabled={submitDisabled}>
            Send
          </button>
        )}
      </div>
    </div>
  );
}
