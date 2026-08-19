import { ProjectStateSummary } from "../../domain/types";

interface WorkspacePlaceholderProps {
  project: ProjectStateSummary;
}

export function WorkspacePlaceholder({ project }: WorkspacePlaceholderProps): JSX.Element {
  return (
    <div className="placeholder-panel workspace-placeholder">
      <div className="workspace-topline">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>Plan Canvas</h1>
          <p className="workspace-subtitle">
            The visual Plan editor will be mounted here in M3. This Project remains
            backed by the validated Plan v2 API.
          </p>
        </div>
        <div className="canvas-controls" aria-label="Canvas controls">
          <button type="button" disabled>
            −
          </button>
          <span>100%</span>
          <button type="button" disabled>
            +
          </button>
          <button type="button" disabled>
            Fit
          </button>
        </div>
      </div>

      <div className="canvas-empty-state">
        <div className="canvas-orbit" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
        <h2>{project.hasPlan ? "Plan ready for Canvas" : "Start with a visible Plan"}</h2>
        <p>
          {project.hasPlan
            ? "The server-confirmed operation graph will appear here in the next milestone."
            : "Create or inspect a Project Plan after the shell is in place."}
        </p>
        <div className="canvas-facts">
          <span>
            <strong>{project.hasPlan ? "Plan" : "No Plan"}</strong>
            {project.hasPlan ? " available" : " yet"}
          </span>
          <span>
            <strong>{project.agentChatCount}</strong> Agent chats
          </span>
          <span>
            <strong>{project.hasResults ? "Evidence" : "Evidence pending"}</strong>
          </span>
        </div>
      </div>
    </div>
  );
}
