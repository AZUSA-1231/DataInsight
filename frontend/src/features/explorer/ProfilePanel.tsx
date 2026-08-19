import { DataCatalog, SourceProfile } from "../../api/dataApi";
import { ExplorerSelection } from "./SourceTree";

interface ProfilePanelProps {
  catalog: DataCatalog;
  selection: ExplorerSelection | null;
  profile: SourceProfile | null;
  loading: boolean;
  error: string | null;
}

function publicSampleRow(row: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(row).filter(([key]) => !key.startsWith("__di_")));
}

export function ProfilePanel({
  catalog,
  selection,
  profile,
  loading,
  error,
}: ProfilePanelProps): JSX.Element {
  if (!selection) {
    return (
      <div className="profile-panel profile-empty">
        <p className="eyebrow">Inspect</p>
        <p className="muted-copy">Select a Source or Snapshot to inspect its public facts.</p>
      </div>
    );
  }

  const snapshot =
    selection.kind === "snapshot"
      ? catalog.snapshots.find((item) => item.viewId === selection.id)
      : catalog.snapshots.find(
          (item) =>
            item.snapshotId ===
            catalog.sources.find((source) => source.sourceId === selection.id)?.snapshotId,
        );
  const columns = profile?.columns ?? catalog.columns.filter((column) => column.snapshot === snapshot?.name);
  const planned = snapshot?.availability === "planned";
  const rowCount = profile?.shape[0] ?? snapshot?.rowCount ?? null;
  const columnCount = profile?.shape[1] ?? columns.length;
  const sample = planned ? [] : profile?.headSample.map(publicSampleRow) ?? [];
  const title = profile?.displayName ?? snapshot?.displayName ?? "Snapshot";

  return (
    <div className="profile-panel">
      <div className="profile-heading">
        <div>
          <p className="eyebrow">{selection.kind === "source" ? "Source profile" : "Snapshot facts"}</p>
          <h3 title={title}>{title}</h3>
        </div>
        <span className={`profile-kind ${planned ? "planned" : ""}`}>
          {planned ? "planned" : selection.kind}
        </span>
      </div>
      {loading ? <p className="profile-status">Loading public profile...</p> : null}
      {error ? <p className="profile-status profile-error">{error}</p> : null}
      {planned ? (
        <p className="profile-status profile-planned">
          Planned schema only. Execution facts and samples will be available after a successful run.
        </p>
      ) : null}
      <div className="profile-facts">
        <span><strong>{rowCount === null ? "Pending" : rowCount.toLocaleString()}</strong> rows</span>
        <span><strong>{columnCount}</strong> columns</span>
      </div>
      {snapshot?.parentSnapshotNames.length ? (
        <p className="profile-lineage-hint">
          Derived from {snapshot.parentSnapshotNames.length} upstream Snapshot{snapshot.parentSnapshotNames.length === 1 ? "" : "s"}:
          {" "}{snapshot.parentSnapshotNames.join(", ")}.
        </p>
      ) : null}
      <div className="profile-columns">
        <p className="tree-group-label">Visible columns</p>
        {columns.length === 0 ? (
          <p className="tree-empty-note">No public column facts available.</p>
        ) : (
          columns.map((column) => {
            const lineage = catalog.lineage.find((item) => item.ref === column.ref);
            const nullFacts =
              column.nullPct === null
                ? "Pending facts"
                : column.nullPct > 0
                  ? `${Math.round(column.nullPct)}% null`
                  : "No nulls";
            return (
              <div className={`profile-column ${column.availability === "planned" ? "planned" : ""}`} key={column.ref}>
                <div>
                  <strong>{column.name}</strong>
                  <small>{column.dtype ?? "Pending type"}</small>
                </div>
                <span>{nullFacts}</span>
                {lineage && lineage.originRefs.length > 0 && column.availability !== "planned" ? (
                  <small className="profile-origin">From {lineage.originRefs.join(", ")}</small>
                ) : null}
              </div>
            );
          })
        )}
      </div>
      {sample.length > 0 ? (
        <div className="profile-sample">
          <p className="tree-group-label">Sample</p>
          <div className="profile-sample-scroll">
            {sample.slice(0, 3).map((row, index) => (
              <pre key={index}>{JSON.stringify(row, null, 0)}</pre>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
