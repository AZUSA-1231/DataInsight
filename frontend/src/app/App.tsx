import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  createProject,
  getProject,
  listProjects,
  projectIdFromPath,
  projectPath,
  readLastProjectId,
  renameProject,
  writeLastProjectId,
} from "../api/client";
import {
  ApiError,
  ProjectStateSummary,
  ProjectSummary,
} from "../domain/types";
import { AgentPanel } from "../features/agent/AgentPanel";
import { DataCatalog } from "../api/dataApi";
import { Explorer } from "../features/explorer/Explorer";
import { OutputDock } from "../features/output/OutputDock";
import { Header } from "../features/shell/Header";
import { ThreePaneLayout } from "../features/shell/ThreePaneLayout";
import { PlanCanvas } from "../features/workspace/canvas/PlanCanvas";
import { OperationKind } from "../features/workspace/operations/operationSchemas";

type LoadPhase = "idle" | "loading" | "ready" | "error";

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return "This Project uses an incompatible saved schema. It was not changed.";
    }
    if (error.status === 404) {
      return "This Project no longer exists in the local workspace.";
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "The local workspace request failed.";
}

function EmptyProjects({ onCreate }: { onCreate: () => void }): JSX.Element {
  return (
    <div className="full-page-state">
      <div className="state-illustration" aria-hidden="true">
        <span>DI</span>
      </div>
      <p className="eyebrow">Local workspace</p>
      <h1>Create your first Project</h1>
      <p>
        A Project keeps data, the reviewed Plan, execution evidence, and Agent
        conversations together so the analysis can be reopened later.
      </p>
      <button className="primary-button" type="button" onClick={onCreate}>
        + New Project
      </button>
    </div>
  );
}

function ProjectUnavailable({
  message,
  onBack,
  onCreate,
}: {
  message: string;
  onBack: () => void;
  onCreate: () => void;
}): JSX.Element {
  return (
    <div className="full-page-state compact-state">
      <div className="warning-mark" aria-hidden="true">
        !
      </div>
      <p className="eyebrow">Project unavailable</p>
      <h1>We kept the workspace safe</h1>
      <p>{message}</p>
      <div className="state-actions">
        <button className="secondary-button" type="button" onClick={onBack}>
          Open Project history
        </button>
        <button className="primary-button" type="button" onClick={onCreate}>
          + New Project
        </button>
      </div>
    </div>
  );
}

export function App(): JSX.Element {
  const requestedProjectId = useRef(projectIdFromPath(window.location.pathname));
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [listPhase, setListPhase] = useState<LoadPhase>("loading");
  const [listError, setListError] = useState<string | null>(null);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(
    requestedProjectId.current ?? readLastProjectId(),
  );
  const [activeProject, setActiveProject] = useState<ProjectStateSummary | null>(null);
  const [projectPhase, setProjectPhase] = useState<LoadPhase>("idle");
  const [projectError, setProjectError] = useState<string | null>(null);
  const [operationError, setOperationError] = useState<string | null>(null);
  const [dataCatalog, setDataCatalog] = useState<DataCatalog | null>(null);
  const [requestedOperation, setRequestedOperation] = useState<OperationKind | null>(null);
  const [workspaceRefreshKey, setWorkspaceRefreshKey] = useState(0);
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);
  const [creating, setCreating] = useState(false);
  const loadGeneration = useRef(0);
  const projectController = useRef<AbortController | null>(null);
  const listController = useRef<AbortController | null>(null);
  const projectRefreshController = useRef<AbortController | null>(null);

  const activeProjectSummary = useMemo(
    () => projects.find((project) => project.projectId === activeProjectId) ?? null,
    [activeProjectId, projects],
  );

  const navigateToProject = useCallback((projectId: string, replace = false): void => {
    const nextPath = projectPath(projectId);
    if (window.location.pathname !== nextPath) {
      if (replace) {
        window.history.replaceState({}, "", nextPath);
      } else {
        window.history.pushState({}, "", nextPath);
      }
    }
    writeLastProjectId(projectId);
  }, []);

  const loadProject = useCallback(
    async (projectId: string, options: { replaceUrl?: boolean; updateUrl?: boolean } = {}): Promise<void> => {
      const generation = loadGeneration.current + 1;
      loadGeneration.current = generation;
      projectController.current?.abort();
      projectRefreshController.current?.abort();
      const controller = new AbortController();
      projectController.current = controller;
      setActiveProjectId(projectId);
      setActiveProject(null);
      setDataCatalog(null);
      setRequestedOperation(null);
      setProjectError(null);
      setProjectPhase("loading");
      if (options.updateUrl !== false) {
        navigateToProject(projectId, options.replaceUrl ?? false);
      } else {
        writeLastProjectId(projectId);
      }
      try {
        const state = await getProject(projectId, controller.signal);
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        setActiveProject(state);
        setProjectPhase("ready");
      } catch (error) {
        if (controller.signal.aborted || generation !== loadGeneration.current) {
          return;
        }
        setProjectPhase("error");
        setProjectError(describeError(error));
      }
    },
    [navigateToProject],
  );

  const refreshProjectList = useCallback(async (): Promise<ProjectSummary[]> => {
    listController.current?.abort();
    const controller = new AbortController();
    listController.current = controller;
    setListPhase("loading");
    setListError(null);
    try {
      const response = await listProjects(controller.signal);
      if (controller.signal.aborted) {
        return [];
      }
      setProjects(response.projects);
      setListPhase("ready");
      return response.projects;
    } catch (error) {
      if (controller.signal.aborted) {
        return [];
      }
      setListPhase("error");
      setListError(describeError(error));
      return [];
    }
  }, []);

  const refreshActiveProject = useCallback(async (): Promise<void> => {
    const projectId = activeProjectId;
    if (!projectId) {
      return;
    }
    projectRefreshController.current?.abort();
    const controller = new AbortController();
    projectRefreshController.current = controller;
    try {
      const state = await getProject(projectId, controller.signal);
      if (controller.signal.aborted || projectId !== activeProjectId) {
        return;
      }
      setActiveProject(state);
      setWorkspaceRefreshKey((current) => current + 1);
      setCatalogRefreshKey((current) => current + 1);
      void refreshProjectList();
    } catch (error) {
      if (!controller.signal.aborted && projectId === activeProjectId) {
        setOperationError(describeError(error));
      }
    }
  }, [activeProjectId, refreshProjectList]);

  const handlePlanChanged = useCallback((): void => {
    setCatalogRefreshKey((current) => current + 1);
  }, []);

  useEffect(() => {
    let mounted = true;
    void refreshProjectList().then((availableProjects) => {
      if (!mounted) {
        return;
      }
      if (availableProjects.length === 0) {
        setActiveProjectId(null);
        setActiveProject(null);
        setProjectPhase("idle");
        if (requestedProjectId.current) {
          setProjectError("No saved Project matches this URL.");
        }
        return;
      }

      const requestedId = requestedProjectId.current;
      const requestedExists = requestedId
        ? availableProjects.some((project) => project.projectId === requestedId)
        : false;
      if (requestedId && !requestedExists) {
        setActiveProjectId(null);
        setActiveProject(null);
        setProjectPhase("error");
        setProjectError("No saved Project matches this URL.");
        return;
      }

      const rememberedId = requestedId ?? readLastProjectId();
      const selected =
        (rememberedId &&
          availableProjects.find((project) => project.projectId === rememberedId)?.projectId) ??
        availableProjects[0].projectId;
      void loadProject(selected, { replaceUrl: true });
    });
    return () => {
      mounted = false;
      listController.current?.abort();
      projectController.current?.abort();
      projectRefreshController.current?.abort();
    };
  }, [loadProject, refreshProjectList]);

  useEffect(() => {
    const onPopState = (): void => {
      const projectId = projectIdFromPath(window.location.pathname);
      if (!projectId) {
        setProjectError("Choose a Project from history to continue.");
        return;
      }
      if (!projects.some((project) => project.projectId === projectId)) {
        setActiveProjectId(null);
        setActiveProject(null);
        setProjectPhase("error");
        setProjectError("No saved Project matches this URL.");
        return;
      }
      void loadProject(projectId, { updateUrl: false });
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [loadProject, projects]);

  const handleCreateProject = async (): Promise<void> => {
    if (creating) {
      return;
    }
    setCreating(true);
    setOperationError(null);
    try {
      const created = await createProject();
      const availableProjects = await refreshProjectList();
      if (!availableProjects.some((project) => project.projectId === created.sessionId)) {
        throw new Error("The new Project was not returned by Project history.");
      }
      requestedProjectId.current = null;
      await loadProject(created.sessionId);
    } catch (error) {
      setOperationError(describeError(error));
    } finally {
      setCreating(false);
    }
  };

  const handleRenameProject = async (projectId: string, title: string): Promise<void> => {
    const updated = await renameProject(projectId, title);
    setProjects((current) =>
      current.map((project) => (project.projectId === projectId ? updated : project)),
    );
    setActiveProject((current) =>
      current && current.projectId === projectId
        ? { ...current, title: updated.title, persistedAt: updated.persistedAt }
        : current,
    );
  };

  const handleSelectProject = (projectId: string): void => {
    setOperationError(null);
    void loadProject(projectId);
  };

  const showUnavailable = projectPhase === "error" || (projectPhase === "idle" && !!projectError);

  return (
    <div className="app-root">
      <Header
        projects={projects}
        activeProject={activeProjectSummary}
        disabled={listPhase === "loading" || creating}
        onSelectProject={handleSelectProject}
        onCreateProject={() => void handleCreateProject()}
        onRenameProject={handleRenameProject}
      />

      {listPhase === "error" ? (
        <div className="global-alert error" role="alert">
          <strong>Project history unavailable.</strong> {listError}
          <button type="button" onClick={() => void refreshProjectList()}>
            Retry
          </button>
        </div>
      ) : null}
      {operationError ? (
        <div className="global-alert error" role="alert">
          {operationError}
          <button type="button" onClick={() => setOperationError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}

      {listPhase === "loading" && projects.length === 0 ? (
        <div className="loading-state" role="status">
          Loading Project history…
        </div>
      ) : null}

      {listPhase === "ready" && projects.length === 0 ? (
        <EmptyProjects onCreate={() => void handleCreateProject()} />
      ) : null}

      {showUnavailable ? (
        <ProjectUnavailable
          message={projectError ?? "The active Project could not be loaded."}
          onBack={() => {
            const first = projects[0];
            if (first) {
              void loadProject(first.projectId, { replaceUrl: true });
            }
          }}
          onCreate={() => void handleCreateProject()}
        />
      ) : null}

      {projectPhase === "loading" && projects.length > 0 ? (
        <div className="loading-state" role="status">
          Loading <strong>{activeProjectSummary?.title ?? "Project"}</strong>…
        </div>
      ) : null}

      {projectPhase === "ready" && activeProject ? (
        <ThreePaneLayout
          explorer={
            <Explorer
              onCatalogChange={setDataCatalog}
              onCreateOperation={setRequestedOperation}
              projectId={activeProject.projectId}
              refreshKey={catalogRefreshKey}
            />
          }
          workspace={
            <PlanCanvas
              catalog={dataCatalog}
              onPlanChanged={handlePlanChanged}
              onRequestedOperationHandled={() => setRequestedOperation(null)}
              projectId={activeProject.projectId}
              refreshKey={workspaceRefreshKey}
              requestedOperation={requestedOperation}
            />
          }
          agent={
            <AgentPanel key={activeProject.projectId} projectId={activeProject.projectId} />
          }
          output={
            <OutputDock
              onWorkspaceChanged={refreshActiveProject}
              projectId={activeProject.projectId}
            />
          }
        />
      ) : null}

      {creating ? <div className="busy-indicator">Creating Project…</div> : null}
    </div>
  );
}
