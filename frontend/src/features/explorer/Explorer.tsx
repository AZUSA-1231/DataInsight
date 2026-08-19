import { ChangeEvent, useCallback, useEffect, useRef, useState } from "react";

import {
  DataCatalog,
  getDataCatalog,
  getProfile,
  SourceProfile,
  uploadSource,
} from "../../api/dataApi";
import { ApiError } from "../../domain/types";
import { OperationKind } from "../workspace/operations/operationSchemas";
import { OperationPalette } from "./OperationPalette";
import { ProfilePanel } from "./ProfilePanel";
import { ExplorerSelection, SourceTree } from "./SourceTree";

interface ExplorerProps {
  projectId: string;
  refreshKey?: number;
  onCatalogChange: (catalog: DataCatalog | null) => void;
  onCreateOperation: (operation: OperationKind) => void;
}

type LoadPhase = "loading" | "ready" | "error";

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return error.message;
  }
  return error instanceof Error ? error.message : "The Explorer request failed.";
}

function uploadError(error: unknown): string {
  if (error instanceof ApiError && error.status === 413) {
    return "This file is larger than the 500 MB upload limit.";
  }
  if (error instanceof ApiError && error.status === 422) {
    return `This file could not be ingested: ${error.message}`;
  }
  return errorMessage(error);
}

export function Explorer({
  projectId,
  refreshKey = 0,
  onCatalogChange,
  onCreateOperation,
}: ExplorerProps): JSX.Element {
  const [catalog, setCatalog] = useState<DataCatalog | null>(null);
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [error, setError] = useState<string | null>(null);
  const [selection, setSelection] = useState<ExplorerSelection | null>(null);
  const [profile, setProfile] = useState<SourceProfile | null>(null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [profileError, setProfileError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState<string | null>(null);
  const uploadInput = useRef<HTMLInputElement | null>(null);
  const uploadController = useRef<AbortController | null>(null);

  const publishCatalog = useCallback(
    (nextCatalog: DataCatalog | null): void => {
      setCatalog(nextCatalog);
      onCatalogChange(nextCatalog);
    },
    [onCatalogChange],
  );

  const loadCatalog = useCallback(
    async (signal?: AbortSignal): Promise<DataCatalog | null> => {
      try {
        const nextCatalog = await getDataCatalog(projectId, signal);
        if (!signal?.aborted) {
          publishCatalog(nextCatalog);
        }
        return nextCatalog;
      } catch (requestError: unknown) {
        if (!signal?.aborted) {
          setPhase("error");
          setError(errorMessage(requestError));
          publishCatalog(null);
        }
        return null;
      }
    },
    [projectId, publishCatalog],
  );

  useEffect(() => {
    const controller = new AbortController();
    setPhase("loading");
    setError(null);
    setSelection(null);
    setProfile(null);
    setProfileError(null);
    publishCatalog(null);
    void loadCatalog(controller.signal).then((nextCatalog) => {
      if (!controller.signal.aborted) {
        setPhase(nextCatalog ? "ready" : "error");
      }
    });
    return () => {
      controller.abort();
      uploadController.current?.abort();
    };
  }, [loadCatalog, publishCatalog, projectId, refreshKey]);

  useEffect(() => {
    if (!selection || !catalog) {
      setProfileLoading(false);
      setProfile(null);
      setProfileError(null);
      return;
    }
    const selectedSnapshot =
      selection.kind === "snapshot"
        ? catalog.snapshots.find((item) => item.viewId === selection.id)
        : catalog.snapshots.find(
            (item) =>
              item.snapshotId ===
              catalog.sources.find((source) => source.sourceId === selection.id)?.snapshotId,
          );
    const source =
      selection.kind === "source"
        ? catalog.sources.find((item) => item.sourceId === selection.id)
        : selectedSnapshot?.snapshotId
          ? catalog.sources.find((item) => item.snapshotId === selectedSnapshot.snapshotId)
          : undefined;
    if (!source || selectedSnapshot?.availability === "planned") {
      setProfileLoading(false);
      setProfile(null);
      setProfileError(null);
      return;
    }
    const controller = new AbortController();
    setProfileLoading(true);
    setProfileError(null);
    void getProfile(projectId, source.sourceId, controller.signal)
      .then((nextProfile) => {
        if (!controller.signal.aborted) {
          setProfile(nextProfile);
        }
      })
      .catch((requestError: unknown) => {
        if (!controller.signal.aborted) {
          setProfile(null);
          setProfileError(errorMessage(requestError));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setProfileLoading(false);
        }
      });
    return () => controller.abort();
  }, [catalog, projectId, selection]);

  const handleUpload = async (event: ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    const lowerName = file.name.toLowerCase();
    if (!lowerName.endsWith(".csv") && !lowerName.endsWith(".xlsx") && !lowerName.endsWith(".xls")) {
      setUploadMessage("Choose a CSV or Excel file.");
      return;
    }
    if (file.size > 500 * 1024 * 1024) {
      setUploadMessage("This file is larger than the 500 MB upload limit.");
      return;
    }
    setUploading(true);
    setUploadMessage(`Uploading ${file.name}...`);
    setError(null);
    uploadController.current?.abort();
    const controller = new AbortController();
    uploadController.current = controller;
    try {
      const result = await uploadSource(projectId, file, controller.signal);
      const nextCatalog = await loadCatalog(controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      if (nextCatalog && result.sourceId) {
        setSelection({ kind: "source", id: result.sourceId });
      }
      setUploadMessage(
        nextCatalog
          ? `${file.name} uploaded. ${result.rowCount.toLocaleString()} rows available.`
          : `${file.name} uploaded, but the catalog refresh failed.`,
      );
    } catch (requestError: unknown) {
      if (!controller.signal.aborted) {
        setUploadMessage(uploadError(requestError));
      }
    } finally {
      if (!controller.signal.aborted) {
        setUploading(false);
      }
    }
  };

  return (
    <div className="placeholder-panel explorer-placeholder">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Explorer</p>
          <h2>Sources</h2>
        </div>
        <span className="count-badge">{catalog?.sources.length ?? 0}</span>
      </div>
      <input
        ref={uploadInput}
        accept=".csv,.xlsx,.xls,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        className="visually-hidden"
        type="file"
        onChange={(event) => void handleUpload(event)}
      />
      <button
        className="upload-placeholder"
        disabled={uploading}
        type="button"
        onClick={() => uploadInput.current?.click()}
      >
        <span className="upload-placeholder-icon" aria-hidden="true">↑</span>
        <span>
          <strong>{uploading ? "Uploading data" : "Upload data"}</strong>
          <small>CSV or Excel · up to 500 MB</small>
        </span>
      </button>
      {uploadMessage ? <p className={`explorer-message ${uploadMessage.includes("could not") || uploadMessage.includes("larger") || uploadMessage.includes("Choose") ? "error" : ""}`}>{uploadMessage}</p> : null}
      {phase === "loading" ? <p className="muted-copy">Loading public data catalog...</p> : null}
      {phase === "error" ? (
        <div className="explorer-error" role="alert">
          <span>{error}</span>
          <button type="button" onClick={() => void loadCatalog()}>Retry</button>
        </div>
      ) : null}
      {catalog ? (
        <SourceTree catalog={catalog} onSelect={setSelection} selection={selection} />
      ) : null}
      <div className="explorer-divider" />
      <div className="panel-heading compact">
        <div>
          <p className="eyebrow">Operations</p>
          <h2>Palette</h2>
        </div>
      </div>
      <OperationPalette
        catalog={catalog ?? { sources: [], snapshots: [], columns: [], lineage: [], compatibilityWarning: null }}
        onCreate={onCreateOperation}
      />
      {catalog?.compatibilityWarning ? <p className="explorer-warning">{catalog.compatibilityWarning}</p> : null}
      {catalog && selection ? (
        <ProfilePanel
          catalog={catalog}
          error={profileError}
          loading={profileLoading}
          profile={profile}
          selection={selection}
        />
      ) : null}
    </div>
  );
}
