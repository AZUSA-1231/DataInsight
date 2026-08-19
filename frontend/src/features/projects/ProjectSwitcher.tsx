import { useEffect, useRef, useState } from "react";

import { ProjectSummary } from "../../domain/types";

interface ProjectSwitcherProps {
  projects: ProjectSummary[];
  activeProject: ProjectSummary | null;
  disabled?: boolean;
  onSelect: (projectId: string) => void;
  onCreate: () => void;
  onRename: (projectId: string, title: string) => Promise<void>;
}

function formatActivity(value: string | null): string {
  if (!value) {
    return "No activity yet";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown activity";
  }
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}

function ProjectMeta({ project }: { project: ProjectSummary }): JSX.Element {
  return (
    <span className="project-meta">
      <span>{project.sourceCount} sources</span>
      <span>{project.unitCount} units</span>
      {project.hasResults ? <span className="meta-positive">results</span> : null}
      {project.hasReport ? <span className="meta-positive">report</span> : null}
    </span>
  );
}

export function ProjectSwitcher({
  projects,
  activeProject,
  disabled = false,
  onSelect,
  onCreate,
  onRename,
}: ProjectSwitcherProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(activeProject?.title ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!editing) {
      setDraft(activeProject?.title ?? "");
    }
  }, [activeProject, editing]);

  useEffect(() => {
    if (!open) {
      return undefined;
    }
    const closeOnOutsideClick = (event: MouseEvent): void => {
      if (
        containerRef.current &&
        event.target instanceof Node &&
        !containerRef.current.contains(event.target)
      ) {
        setOpen(false);
        setEditing(false);
        setError(null);
      }
    };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, [open]);

  const saveRename = async (): Promise<void> => {
    if (!activeProject || !draft.trim()) {
      setError("Project title must not be blank.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await onRename(activeProject.projectId, draft.trim());
      setEditing(false);
    } catch (renameError) {
      setError(renameError instanceof Error ? renameError.message : "Rename failed.");
    } finally {
      setBusy(false);
    }
  };

  const handleRenameKeyDown = (event: React.KeyboardEvent<HTMLInputElement>): void => {
    if (event.key === "Enter") {
      event.preventDefault();
      void saveRename();
    }
    if (event.key === "Escape") {
      setEditing(false);
      setDraft(activeProject?.title ?? "");
      setError(null);
    }
  };

  return (
    <div className="project-switcher" ref={containerRef}>
      <button
        className="project-current-button"
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        disabled={disabled}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="project-current-label">Project</span>
        <span className="project-current-title">
          {activeProject?.title ?? "No Project selected"}
        </span>
        <span className="project-chevron" aria-hidden="true">
          {open ? "▴" : "▾"}
        </span>
      </button>

      {open ? (
        <div className="project-menu" role="dialog" aria-label="Project history">
          <div className="project-menu-header">
            <div>
              <p className="eyebrow">Project history</p>
              <p className="menu-description">Persisted local analysis workspaces</p>
            </div>
            <button className="text-button" type="button" onClick={onCreate}>
              + New Project
            </button>
          </div>

          {projects.length === 0 ? (
            <p className="menu-empty">No Projects yet.</p>
          ) : (
            <div className="project-list" role="listbox" aria-label="Projects">
              {projects.map((project) => {
                const unavailable = project.status === "incompatible_schema";
                return (
                  <button
                    className={`project-entry ${
                      project.projectId === activeProject?.projectId ? "selected" : ""
                    } ${unavailable ? "unavailable" : ""}`}
                    type="button"
                    role="option"
                    aria-selected={project.projectId === activeProject?.projectId}
                    key={project.projectId}
                    onClick={() => {
                      onSelect(project.projectId);
                      setOpen(false);
                      setError(null);
                    }}
                  >
                    <span className="project-entry-main">
                      <strong>{project.title}</strong>
                      <span>{formatActivity(project.persistedAt ?? project.createdAt)}</span>
                    </span>
                    <ProjectMeta project={project} />
                    {unavailable ? <span className="status-chip error">Unavailable</span> : null}
                  </button>
                );
              })}
            </div>
          )}

          {activeProject ? (
            <div className="project-rename-area">
              {editing ? (
                <div className="rename-form">
                  <label htmlFor="project-title-input">Rename active Project</label>
                  <div className="rename-controls">
                    <input
                      id="project-title-input"
                      value={draft}
                      maxLength={120}
                      autoFocus
                      onChange={(event) => setDraft(event.target.value)}
                      onKeyDown={handleRenameKeyDown}
                      disabled={busy}
                    />
                    <button
                      className="small-button primary"
                      type="button"
                      disabled={busy}
                      onClick={() => void saveRename()}
                    >
                      Save
                    </button>
                    <button
                      className="small-button"
                      type="button"
                      disabled={busy}
                      onClick={() => {
                        setEditing(false);
                        setError(null);
                      }}
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  className="text-button"
                  type="button"
                  onClick={() => {
                    setEditing(true);
                    setError(null);
                  }}
                >
                  Rename active Project
                </button>
              )}
              {error ? <p className="inline-error">{error}</p> : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
