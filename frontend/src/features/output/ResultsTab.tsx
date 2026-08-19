import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  chartUrl,
  ExecutionResultsResponse,
  getExecutionResults,
  getExecutionStatus,
  isTerminalExecutionStatus,
  rerunUnit,
  startExecution,
  UnitResult,
} from "../../api/executionApi";
import { ApiError } from "../../domain/types";

interface ResultsTabProps {
  projectId: string;
  onWorkspaceChanged: () => Promise<void> | void;
}

type LoadPhase = "loading" | "ready" | "error";
type ResultViewStatus = "idle" | "running" | "completed" | "partial" | "failed" | "stale";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "The execution request failed.";
}

function viewStatus(
  serverStatus: string,
  results: ExecutionResultsResponse | null,
): ResultViewStatus {
  if (serverStatus === "running" || results?.status === "running") {
    return "running";
  }
  if (serverStatus === "failed" || results?.status === "failed") {
    return "failed";
  }
  if (results?.staleUnitIds.length || results?.units.some((unit) => unit.stale)) {
    return "stale";
  }
  if (results?.status === "partial") {
    return "partial";
  }
  if (serverStatus === "completed" || results?.status === "complete") {
    return "completed";
  }
  return "idle";
}

function statusLabel(status: ResultViewStatus): string {
  switch (status) {
    case "running":
      return "Running";
    case "completed":
      return "Completed";
    case "partial":
      return "Partial";
    case "failed":
      return "Failed";
    case "stale":
      return "Stale outputs";
    default:
      return "Idle";
  }
}

function warningCode(warning: Record<string, unknown>): string {
  return typeof warning.code === "string" ? warning.code : "Execution warning";
}

function warningMessage(warning: Record<string, unknown>): string {
  if (typeof warning.message === "string") {
    return warning.message;
  }
  if (typeof warning.detail === "string") {
    return warning.detail;
  }
  return Object.entries(warning)
    .filter(([key]) => key !== "code")
    .map(([key, value]) => `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`)
    .join("; ");
}

function rowSummary(unit: UnitResult): string | null {
  if (unit.rowCountBefore === null && unit.rowCountAfter === null) {
    return null;
  }
  const before = unit.rowCountBefore === null ? "-" : unit.rowCountBefore.toLocaleString();
  const after = unit.rowCountAfter === null ? "-" : unit.rowCountAfter.toLocaleString();
  const delta = unit.rowCountDelta === null ? "" : ` (${unit.rowCountDelta >= 0 ? "+" : ""}${unit.rowCountDelta.toLocaleString()})`;
  return `${before} -> ${after}${delta}`;
}

function checkpointLabel(value: string | null): string | null {
  return value ? value : null;
}

function sortUnits(units: UnitResult[]): UnitResult[] {
  return [...units].sort((left, right) => left.unitId - right.unitId);
}

export function ResultsTab({ projectId, onWorkspaceChanged }: ResultsTabProps): JSX.Element {
  const [results, setResults] = useState<ExecutionResultsResponse | null>(null);
  const [serverStatus, setServerStatus] = useState("idle");
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [expandedUnitIds, setExpandedUnitIds] = useState<Set<number>>(new Set());
  const [actionKey, setActionKey] = useState<string | null>(null);
  const loadController = useRef<AbortController | null>(null);
  const actionController = useRef<AbortController | null>(null);

  const loadCurrentResults = useCallback(
    async (signal: AbortSignal): Promise<ExecutionResultsResponse> => {
      const [status, nextResults] = await Promise.all([
        getExecutionStatus(projectId, signal),
        getExecutionResults(projectId, signal),
      ]);
      if (signal.aborted) {
        return nextResults;
      }
      setServerStatus(status.status);
      if (status.error) {
        setError(status.error);
      }
      setResults(nextResults);
      return nextResults;
    },
    [projectId],
  );

  useEffect(() => {
    const controller = new AbortController();
    loadController.current?.abort();
    actionController.current?.abort();
    loadController.current = controller;
    setResults(null);
    setServerStatus("idle");
    setPhase("loading");
    setError(null);
    setNotice(null);
    setExpandedUnitIds(new Set());
    setActionKey(null);
    void loadCurrentResults(controller.signal)
      .then(() => {
        if (!controller.signal.aborted) {
          setPhase("ready");
        }
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setPhase("error");
          setError(errorMessage(requestError));
        }
      });
    return () => {
      controller.abort();
      actionController.current?.abort();
    };
  }, [loadCurrentResults, projectId]);

  const currentStatus = viewStatus(serverStatus, results);

  useEffect(() => {
    if (serverStatus !== "running") {
      return;
    }
    const controller = new AbortController();
    let timer: number | null = null;
    let delay = 350;
    let notified = false;

    const poll = async (): Promise<void> => {
      try {
        const status = await getExecutionStatus(projectId, controller.signal);
        if (controller.signal.aborted) {
          return;
        }
        setServerStatus(status.status);
        if (status.error) {
          setError(status.error);
        }
        if (isTerminalExecutionStatus(status.status)) {
          const nextResults = await getExecutionResults(projectId, controller.signal);
          if (controller.signal.aborted) {
            return;
          }
          setResults(nextResults);
          setPhase("ready");
          if (!notified) {
            notified = true;
            await onWorkspaceChanged();
          }
          return;
        }
        delay = Math.min(1600, Math.round(delay * 1.35));
        timer = window.setTimeout(() => void poll(), delay);
      } catch (requestError: unknown) {
        if (!controller.signal.aborted) {
          setError(errorMessage(requestError));
          setPhase("error");
        }
      }
    };

    void poll();
    return () => {
      controller.abort();
      if (timer !== null) {
        window.clearTimeout(timer);
      }
    };
  }, [onWorkspaceChanged, projectId, serverStatus]);

  const orderedUnits = useMemo(() => sortUnits(results?.units ?? []), [results?.units]);

  const handleRun = async (): Promise<void> => {
    if (actionKey || currentStatus === "running") {
      return;
    }
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setActionKey("run");
    setError(null);
    setNotice(null);
    try {
      await startExecution(projectId, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      setServerStatus("running");
      setResults((current) => (current ? { ...current, status: "running" } : null));
      setPhase("ready");
    } catch (requestError: unknown) {
      if (!controller.signal.aborted) {
        setError(errorMessage(requestError));
      }
    } finally {
      if (!controller.signal.aborted) {
        setActionKey(null);
      }
    }
  };

  const handleRerun = async (unitId: number, cascade: boolean): Promise<void> => {
    if (actionKey) {
      return;
    }
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    const key = `${unitId}:${cascade ? "cascade" : "unit"}`;
    setActionKey(key);
    setError(null);
    setNotice(null);
    try {
      const response = await rerunUnit(projectId, unitId, cascade, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      const nextResults = await loadCurrentResults(controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      setResults(nextResults);
      const staleCount = response.staleUnits.length;
      setNotice(
        staleCount > 0
          ? `Unit ${unitId} reran. ${staleCount} dependent Unit${staleCount === 1 ? "" : "s"} remain stale.`
          : `Unit ${unitId} reran successfully.`,
      );
      await onWorkspaceChanged();
    } catch (requestError: unknown) {
      if (!controller.signal.aborted) {
        setError(errorMessage(requestError));
      }
    } finally {
      if (!controller.signal.aborted) {
        setActionKey(null);
      }
    }
  };

  const toggleExpanded = (unitId: number): void => {
    setExpandedUnitIds((current) => {
      const next = new Set(current);
      if (next.has(unitId)) {
        next.delete(unitId);
      } else {
        next.add(unitId);
      }
      return next;
    });
  };

  return (
    <div className="output-tab results-tab">
      <div className="output-tab-heading">
        <div>
          <p className="eyebrow">Execution</p>
          <h2>Results</h2>
        </div>
        <div className="output-heading-actions">
          <button
            className="secondary-button output-action-button"
            disabled={!!actionKey || currentStatus === "running"}
            type="button"
            onClick={() => void handleRun()}
          >
            {actionKey === "run" ? "Starting..." : "Run Plan"}
          </button>
          <button
            aria-label="Refresh execution results"
            className="icon-button"
            disabled={!!actionKey}
            title="Refresh results"
            type="button"
            onClick={() => {
              const controller = new AbortController();
              loadController.current?.abort();
              loadController.current = controller;
              setPhase("loading");
              setError(null);
              void loadCurrentResults(controller.signal)
                .then(() => {
                  if (!controller.signal.aborted) {
                    setPhase("ready");
                  }
                })
                .catch((requestError: unknown) => {
                  if (!controller.signal.aborted) {
                    setPhase("error");
                    setError(errorMessage(requestError));
                  }
                });
            }}
          >
            R
          </button>
        </div>
      </div>
      <div className="output-status-row">
        <span className={`output-status-pill ${currentStatus}`}>{statusLabel(currentStatus)}</span>
        {results?.runId ? <span className="output-meta">Run {results.runId}</span> : null}
        {results?.staleUnitIds.length ? (
          <span className="output-meta warning-text">{results.staleUnitIds.length} stale</span>
        ) : null}
      </div>
      {error ? (
        <div className="output-inline-alert" role="alert">
          <span>{error}</span>
          <button className="text-button" type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}
      {notice ? <p className="output-notice" role="status">{notice}</p> : null}
      {phase === "loading" ? <p className="output-muted">Loading execution evidence...</p> : null}
      {phase === "error" && !results ? (
        <div className="output-empty-state">
          <strong>Results could not be loaded</strong>
          <p>Refresh this Project to try again.</p>
        </div>
      ) : null}
      {phase === "ready" && orderedUnits.length === 0 && currentStatus === "idle" ? (
        <div className="output-empty-state">
          <strong>No execution yet</strong>
          <p>Review the Plan, then run it to retain unit results and charts here.</p>
        </div>
      ) : null}
      {currentStatus === "running" ? (
        <div className="output-running" role="status">
          <span className="state-dot running" aria-hidden="true" />
          <div>
            <strong>Executing the current Plan</strong>
            <p>Results will appear here when the server reaches a terminal state.</p>
          </div>
        </div>
      ) : null}
      {orderedUnits.length > 0 ? (
        <div className="result-unit-list">
          {orderedUnits.map((unit) => {
            const expanded = expandedUnitIds.has(unit.unitId);
            const busyUnit = actionKey?.startsWith(`${unit.unitId}:`) ?? false;
            const summary = rowSummary(unit);
            return (
              <article className={`result-unit ${unit.stale ? "stale" : ""}`} key={unit.unitId}>
                <div className="result-unit-header">
                  <button
                    className="result-unit-link"
                    type="button"
                    onClick={() => {
                      document.getElementById(`plan-unit-${unit.unitId}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
                      toggleExpanded(unit.unitId);
                    }}
                  >
                    <span className="result-unit-number">Unit {unit.unitId}</span>
                    <span className={`result-unit-status ${unit.status}`}>{unit.status}</span>
                    {unit.stale ? <span className="result-unit-stale">stale</span> : null}
                  </button>
                  <div className="result-unit-actions">
                    <button
                      className="text-button"
                      disabled={!!actionKey}
                      type="button"
                      onClick={() => void handleRerun(unit.unitId, false)}
                    >
                      {busyUnit && actionKey?.endsWith(":unit") ? "Rerunning..." : "Rerun"}
                    </button>
                    <button
                      className="text-button"
                      disabled={!!actionKey}
                      type="button"
                      onClick={() => void handleRerun(unit.unitId, true)}
                    >
                      {busyUnit && actionKey?.endsWith(":cascade") ? "Cascading..." : "Cascade"}
                    </button>
                    <button
                      aria-expanded={expanded}
                      className="icon-button"
                      title={expanded ? "Collapse Unit details" : "Expand Unit details"}
                      type="button"
                      onClick={() => toggleExpanded(unit.unitId)}
                    >
                      {expanded ? "-" : "+"}
                    </button>
                  </div>
                </div>
                <div className="result-unit-summary">
                  {summary ? <span>Rows {summary}</span> : null}
                  {unit.outputCheckpointId ? <span>Output {checkpointLabel(unit.outputCheckpointId)}</span> : null}
                  {unit.inputCheckpointIds.length ? (
                    <span>{unit.inputCheckpointIds.length} input checkpoint{unit.inputCheckpointIds.length === 1 ? "" : "s"}</span>
                  ) : null}
                  {unit.warnings.length ? <span className="warning-text">{unit.warnings.length} warning{unit.warnings.length === 1 ? "" : "s"}</span> : null}
                </div>
                {expanded ? (
                  <div className="result-unit-details">
                    {unit.insights.length ? (
                      <section>
                        <h3>Insights</h3>
                        <ul>{unit.insights.map((insight) => <li key={insight}>{insight}</li>)}</ul>
                      </section>
                    ) : null}
                    {unit.warnings.length ? (
                      <section className="result-warnings">
                        <h3>Warnings</h3>
                        {unit.warnings.map((warning, index) => (
                          <div className="result-warning" key={`${warningCode(warning)}-${index}`}>
                            <strong>{warningCode(warning)}</strong>
                            <span>{warningMessage(warning)}</span>
                          </div>
                        ))}
                      </section>
                    ) : null}
                    {unit.charts.length ? (
                      <section>
                        <h3>Charts</h3>
                        <div className="result-charts">
                          {unit.charts.map((path) => (
                            <a href={chartUrl(projectId, path)} key={path} rel="noreferrer" target="_blank">
                              <img alt={`Chart from Unit ${unit.unitId}`} src={chartUrl(projectId, path)} />
                              <span>{path.split("/").pop() ?? "Chart"}</span>
                            </a>
                          ))}
                        </div>
                      </section>
                    ) : null}
                    {unit.stdout || unit.stderr ? (
                      <details className="result-logs">
                        <summary>Logs</summary>
                        {unit.stdout ? <pre>{unit.stdout}</pre> : null}
                        {unit.stderr ? <pre className="stderr">{unit.stderr}</pre> : null}
                      </details>
                    ) : null}
                    {Object.keys(unit.statistics).length ? (
                      <details className="result-logs">
                        <summary>Statistics</summary>
                        <pre>{JSON.stringify(unit.statistics, null, 2)}</pre>
                      </details>
                    ) : null}
                    {unit.error ? <p className="result-unit-error">{unit.error}</p> : null}
                    {unit.runId ? <p className="output-meta">Unit run {unit.runId}</p> : null}
                  </div>
                ) : null}
              </article>
            );
          })}
        </div>
      ) : null}
    </div>
  );
}
