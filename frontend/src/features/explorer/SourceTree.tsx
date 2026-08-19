import { DataCatalog, PublicColumn, SnapshotSummary } from "../../api/dataApi";
import { serializeDragPayload } from "../workspace/operations/dropIntents";

export type ExplorerSelection =
  | { kind: "source"; id: string }
  | { kind: "snapshot"; id: string };

interface SourceTreeProps {
  catalog: DataCatalog;
  selection: ExplorerSelection | null;
  onSelect: (selection: ExplorerSelection) => void;
}

function startColumnDrag(event: React.DragEvent<HTMLButtonElement>, column: PublicColumn): void {
  const payload = serializeDragPayload({
    kind: "qualified-column",
    ref: column.ref,
    snapshot: column.snapshot,
  });
  event.dataTransfer.setData("application/x-datainsight", payload);
  event.dataTransfer.setData("text/plain", payload);
  event.dataTransfer.effectAllowed = "copy";
}

function snapshotColumns(catalog: DataCatalog, snapshot: SnapshotSummary): PublicColumn[] {
  const refs = new Set(snapshot.columnRefs);
  return catalog.columns.filter(
    (column) => column.snapshot === snapshot.name && (refs.size === 0 || refs.has(column.ref)),
  );
}

function plannedLabel(availability: "materialized" | "planned"): JSX.Element | null {
  return availability === "planned" ? (
    <span className="tree-planned-badge">Planned</span>
  ) : null;
}

function ColumnRows({
  catalog,
  snapshot,
}: {
  catalog: DataCatalog;
  snapshot: SnapshotSummary;
}): JSX.Element {
  const columns = snapshotColumns(catalog, snapshot);
  if (columns.length === 0) {
    return <span className="tree-empty-note">No visible columns</span>;
  }
  return (
    <div className="tree-columns">
      {columns.map((column) => {
        const dtype = column.dtype ?? "Pending type";
        const nullFacts =
          column.nullPct === null
            ? "Pending facts"
            : column.nullPct > 0
              ? `${Math.round(column.nullPct)}% null`
              : "No nulls";
        return (
          <button
            className={`tree-column-row ${column.availability === "planned" ? "planned" : ""}`}
            draggable
            key={column.ref}
            title={`Drag ${column.ref}`}
            type="button"
            onDragStart={(event) => startColumnDrag(event, column)}
          >
            <span className="tree-column-name">{column.name}</span>
            <span className="tree-column-meta">
              {dtype} · {nullFacts}
            </span>
          </button>
        );
      })}
    </div>
  );
}

function SnapshotRow({
  catalog,
  snapshot,
  selection,
  onSelect,
}: {
  catalog: DataCatalog;
  snapshot: SnapshotSummary;
  selection: ExplorerSelection | null;
  onSelect: (selection: ExplorerSelection) => void;
}): JSX.Element {
  const selected = selection?.kind === "snapshot" && selection.id === snapshot.viewId;
  const rowCount = snapshot.rowCount === null ? "Pending" : snapshot.rowCount.toLocaleString();
  return (
    <div className={`tree-snapshot-group ${snapshot.availability === "planned" ? "planned" : ""}`}>
      <button
        className={`tree-row tree-snapshot-row ${selected ? "active" : ""}`}
        type="button"
        onClick={() => onSelect({ kind: "snapshot", id: snapshot.viewId })}
      >
        <span className="tree-icon" aria-hidden="true">
          S
        </span>
        <span className="tree-row-label">{snapshot.displayName || snapshot.name}</span>
        {plannedLabel(snapshot.availability)}
        <span className="tree-row-count">{rowCount} rows</span>
      </button>
      <ColumnRows catalog={catalog} snapshot={snapshot} />
    </div>
  );
}

export function SourceTree({ catalog, selection, onSelect }: SourceTreeProps): JSX.Element {
  const snapshotsByViewId = new Map(catalog.snapshots.map((snapshot) => [snapshot.viewId, snapshot]));
  const sourceSnapshotIds = new Set(catalog.sources.map((source) => source.snapshotId));
  const derivedSnapshots = catalog.snapshots.filter(
    (snapshot) => snapshot.snapshotId === null || !sourceSnapshotIds.has(snapshot.snapshotId),
  );

  return (
    <div className="source-tree" aria-label="Sources and Snapshots">
      {catalog.sources.map((source) => {
        const snapshot = snapshotsByViewId.get(source.snapshotId);
        const selected = selection?.kind === "source" && selection.id === source.sourceId;
        return (
          <div className="tree-source-group" key={source.sourceId}>
            <button
              className={`tree-row tree-source-row ${selected ? "active" : ""}`}
              type="button"
              onClick={() => onSelect({ kind: "source", id: source.sourceId })}
            >
              <span className="tree-icon" aria-hidden="true">
                F
              </span>
              <span className="tree-row-label">{source.displayName}</span>
              <span className="tree-row-count">{source.columnCount} col</span>
            </button>
            {snapshot ? (
              <SnapshotRow
                catalog={catalog}
                onSelect={onSelect}
                selection={selection}
                snapshot={snapshot}
              />
            ) : null}
          </div>
        );
      })}
      {derivedSnapshots.length > 0 ? (
        <div className="tree-derived-group">
          <p className="tree-group-label">Derived Snapshots</p>
          {derivedSnapshots.map((snapshot) => (
            <SnapshotRow
              catalog={catalog}
              key={snapshot.viewId}
              onSelect={onSelect}
              selection={selection}
              snapshot={snapshot}
            />
          ))}
        </div>
      ) : null}
      {catalog.sources.length === 0 && catalog.snapshots.length === 0 ? (
        <p className="muted-copy">No Sources in this Project yet.</p>
      ) : null}
    </div>
  );
}
