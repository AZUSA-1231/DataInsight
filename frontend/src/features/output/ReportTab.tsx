import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../domain/types";
import { generateReport, getReport, ReportResponse } from "../../api/reportApi";

interface ReportTabProps {
  projectId: string;
  onProjectChanged: () => Promise<void> | void;
}

type LoadPhase = "loading" | "ready" | "error";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "The report request failed.";
}

export function ReportTab({ projectId, onProjectChanged }: ReportTabProps): JSX.Element {
  const [report, setReport] = useState<string | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestController = useRef<AbortController | null>(null);

  const applyReport = useCallback((response: ReportResponse): void => {
    setReport(response.report);
    setError(response.error);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    requestController.current?.abort();
    requestController.current = controller;
    setReport(null);
    setPhase("loading");
    setGenerating(false);
    setError(null);
    void getReport(projectId, controller.signal)
      .then((response) => {
        if (controller.signal.aborted) {
          return;
        }
        applyReport(response);
        setPhase("ready");
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setPhase("error");
          setError(errorMessage(requestError));
        }
      });
    return () => controller.abort();
  }, [applyReport, projectId]);

  const handleGenerate = async (): Promise<void> => {
    if (generating) {
      return;
    }
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setGenerating(true);
    setError(null);
    try {
      const response = await generateReport(projectId, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      applyReport(response);
      setPhase("ready");
      await onProjectChanged();
    } catch (requestError: unknown) {
      if (!controller.signal.aborted) {
        setError(errorMessage(requestError));
      }
    } finally {
      if (!controller.signal.aborted) {
        setGenerating(false);
      }
    }
  };

  return (
    <div className="output-tab report-tab">
      <div className="output-tab-heading">
        <div>
          <p className="eyebrow">Evidence</p>
          <h2>Report</h2>
        </div>
        <button
          className="primary-button output-action-button"
          disabled={generating}
          type="button"
          onClick={() => void handleGenerate()}
        >
          {generating ? "Generating..." : report ? "Regenerate" : "Generate report"}
        </button>
      </div>
      {error ? (
        <div className="output-inline-alert" role="alert">
          <span>{error}</span>
          <button className="text-button" type="button" onClick={() => setError(null)}>
            Dismiss
          </button>
        </div>
      ) : null}
      {phase === "loading" ? <p className="output-muted">Loading retained report...</p> : null}
      {phase === "error" && !report ? (
        <div className="output-empty-state">
          <strong>Report could not be loaded</strong>
          <p>Use Generate report to try again.</p>
        </div>
      ) : null}
      {phase === "ready" && !report ? (
        <div className="output-empty-state">
          <strong>No report retained</strong>
          <p>Generate a report after reviewing the execution evidence.</p>
        </div>
      ) : null}
      {report ? (
        <article className="report-document" aria-label="Retained Markdown report">
          <pre>{report}</pre>
        </article>
      ) : null}
    </div>
  );
}
