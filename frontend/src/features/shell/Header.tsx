import { ProjectSummary } from "../../domain/types";
import { ProjectSwitcher } from "../projects/ProjectSwitcher";

interface HeaderProps {
  projects: ProjectSummary[];
  activeProject: ProjectSummary | null;
  disabled?: boolean;
  onSelectProject: (projectId: string) => void;
  onCreateProject: () => void;
  onRenameProject: (projectId: string, title: string) => Promise<void>;
}

export function Header({
  projects,
  activeProject,
  disabled,
  onSelectProject,
  onCreateProject,
  onRenameProject,
}: HeaderProps): JSX.Element {
  return (
    <header className="app-header">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">
          DI
        </div>
        <div>
          <strong>DataInsight</strong>
          <span>Analysis workspace</span>
        </div>
      </div>

      <ProjectSwitcher
        projects={projects}
        activeProject={activeProject}
        disabled={disabled}
        onSelect={onSelectProject}
        onCreate={onCreateProject}
        onRename={onRenameProject}
      />

      <div className="local-user" aria-label="Current user">
        <span className="online-dot" aria-hidden="true" />
        <span>Local user</span>
      </div>
    </header>
  );
}
