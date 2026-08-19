import { apiFetch } from "./client";

export interface PublicColumn {
  name: string;
  dtype: string | null;
  nullCount: number | null;
  nullPct: number | null;
  ref: string;
  snapshot: string;
  sourceColumn: string | null;
  createdByUnitId: number | null;
  availability: "materialized" | "planned";
}

export interface SourceSummary {
  sourceId: string;
  displayName: string;
  snapshotId: string;
  snapshotName: string;
  rowCount: number;
  columnCount: number;
}

export interface SnapshotSummary {
  viewId: string;
  snapshotId: string | null;
  name: string;
  displayName: string;
  rowCount: number | null;
  columnRefs: string[];
  sourceId: string | null;
  createdByUnitId: number | null;
  parentSnapshotNames: string[];
  availability: "materialized" | "planned";
  profileAvailable: boolean;
}

export interface LineageColumn {
  ref: string;
  snapshot: string;
  name: string;
  dtype: string;
  sourceColumn: string | null;
  originRefs: string[];
  derivedFrom: string[];
  createdByUnitId: number | null;
}

export interface SourceProfile {
  sourceId: string;
  snapshotId: string;
  snapshotName: string;
  displayName: string;
  shape: [number, number];
  columns: PublicColumn[];
  encoding: string | null;
  statistics: Record<string, Record<string, unknown>>;
  headSample: Record<string, unknown>[];
}

export interface DataCatalog {
  sources: SourceSummary[];
  snapshots: SnapshotSummary[];
  columns: PublicColumn[];
  lineage: LineageColumn[];
  compatibilityWarning: string | null;
}

export interface UploadResult {
  fileName: string;
  rowCount: number;
  columnCount: number;
  sourceId: string | null;
  snapshotId: string | null;
  snapshotName: string | null;
  columns: PublicColumn[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function objectValue(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid API response: ${field} must be an object`);
  }
  return value;
}

function stringValue(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid API response: ${field} must be a string`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | null {
  if (value === null || value === undefined) {
    return null;
  }
  return stringValue(value, field);
}

function numberValue(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid API response: ${field} must be a finite number`);
  }
  return value;
}

function nullableNumber(value: unknown, field: string): number | null {
  if (value === null || value === undefined) {
    return null;
  }
  return numberValue(value, field);
}

function availabilityValue(
  value: unknown,
  field: string,
): "materialized" | "planned" {
  if (value !== "materialized" && value !== "planned") {
    throw new Error(`Invalid API response: ${field} must be materialized or planned`);
  }
  return value;
}

function stringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid API response: ${field} must be an array of strings`);
  }
  return value as string[];
}

function recordArray(value: unknown, field: string): Record<string, unknown>[] {
  if (!Array.isArray(value) || value.some((item) => !isRecord(item))) {
    throw new Error(`Invalid API response: ${field} must be an array of objects`);
  }
  return (value as Record<string, unknown>[]).map((record) =>
    Object.fromEntries(Object.entries(record).filter(([key]) => !key.startsWith("__di_"))),
  );
}

function decodeColumn(value: unknown, index: number): PublicColumn {
  const item = objectValue(value, `columns[${index}]`);
  const ref = optionalString(item.ref, `columns[${index}].ref`);
  const snapshot = optionalString(item.snapshot, `columns[${index}].snapshot`);
  if (!ref || !snapshot) {
    throw new Error(`Invalid API response: columns[${index}] must be qualified`);
  }
  return {
    name: stringValue(item.name, `columns[${index}].name`),
    dtype: stringValue(item.dtype, `columns[${index}].dtype`),
    nullCount: numberValue(item.null_count, `columns[${index}].null_count`),
    nullPct: numberValue(item.null_pct, `columns[${index}].null_pct`),
    ref,
    snapshot,
    sourceColumn: optionalString(item.source_column, `columns[${index}].source_column`),
    createdByUnitId: null,
    availability: "materialized",
  };
}

function decodeSources(payload: unknown): SourceSummary[] {
  const value = objectValue(payload, "sources response");
  const sources = value.sources;
  if (!Array.isArray(sources)) {
    throw new Error("Invalid API response: sources must be an array");
  }
  return sources.map((item, index) => {
    const source = objectValue(item, `sources[${index}]`);
    return {
      sourceId: stringValue(source.source_id, `sources[${index}].source_id`),
      displayName: stringValue(source.display_name, `sources[${index}].display_name`),
      snapshotId: stringValue(source.snapshot_id, `sources[${index}].snapshot_id`),
      snapshotName: stringValue(source.snapshot_name, `sources[${index}].snapshot_name`),
      rowCount: numberValue(source.row_count, `sources[${index}].row_count`),
      columnCount: numberValue(source.col_count, `sources[${index}].col_count`),
    };
  });
}

function decodeSnapshots(payload: unknown): SnapshotSummary[] {
  const value = objectValue(payload, "snapshots response");
  const snapshots = value.snapshots;
  if (!Array.isArray(snapshots)) {
    throw new Error("Invalid API response: snapshots must be an array");
  }
  return snapshots.map((item, index) => {
    const snapshot = objectValue(item, `snapshots[${index}]`);
    return {
      viewId: stringValue(snapshot.snapshot_id, `snapshots[${index}].snapshot_id`),
      snapshotId: stringValue(snapshot.snapshot_id, `snapshots[${index}].snapshot_id`),
      name: stringValue(snapshot.name, `snapshots[${index}].name`),
      displayName: stringValue(snapshot.display_name, `snapshots[${index}].display_name`),
      rowCount: numberValue(snapshot.row_count, `snapshots[${index}].row_count`),
      columnRefs: stringArray(snapshot.column_refs, `snapshots[${index}].column_refs`),
      sourceId: optionalString(snapshot.source_id, `snapshots[${index}].source_id`),
      createdByUnitId:
        snapshot.created_by_unit_id === null || snapshot.created_by_unit_id === undefined
          ? null
          : numberValue(snapshot.created_by_unit_id, `snapshots[${index}].created_by_unit_id`),
      parentSnapshotNames: stringArray(
        snapshot.parent_snapshot_ids,
        `snapshots[${index}].parent_snapshot_ids`,
      ),
      availability: "materialized",
      profileAvailable: snapshot.source_id !== null && snapshot.source_id !== undefined,
    };
  });
}

interface ColumnsProjection {
  columns: PublicColumn[];
  compatibilityWarning: string | null;
}

function decodeColumnsProjection(payload: unknown): ColumnsProjection {
  const value = objectValue(payload, "columns response");
  if (!Array.isArray(value.columns)) {
    throw new Error("Invalid API response: columns must be an array");
  }
  const columns = value.columns.map(decodeColumn);
  const legacyRefs = Array.isArray(value.unified_columns)
    ? value.unified_columns.filter((item): item is string => typeof item === "string")
    : [];
  return {
    columns,
    compatibilityWarning:
      columns.length === 0 && legacyRefs.length > 0
        ? "This Project exposes a legacy column projection. Upload a new Source to enable typed column facts."
        : null,
  };
}

function decodeLineage(payload: unknown): LineageColumn[] {
  const value = objectValue(payload, "lineage response");
  if (!Array.isArray(value.columns)) {
    throw new Error("Invalid API response: lineage columns must be an array");
  }
  return value.columns.map((item, index) => {
    const column = objectValue(item, `lineage.columns[${index}]`);
    return {
      ref: stringValue(column.ref, `lineage.columns[${index}].ref`),
      snapshot: stringValue(column.snapshot, `lineage.columns[${index}].snapshot`),
      name: stringValue(column.name, `lineage.columns[${index}].name`),
      dtype: stringValue(column.dtype, `lineage.columns[${index}].dtype`),
      sourceColumn: optionalString(column.source_column, `lineage.columns[${index}].source_column`),
      originRefs: stringArray(column.origin_refs, `lineage.columns[${index}].origin_refs`),
      derivedFrom: stringArray(column.derived_from, `lineage.columns[${index}].derived_from`),
      createdByUnitId:
        column.created_by_unit_id === null || column.created_by_unit_id === undefined
          ? null
          : numberValue(column.created_by_unit_id, `lineage.columns[${index}].created_by_unit_id`),
    };
  });
}

function decodeWorkspaceColumn(value: unknown, index: number): PublicColumn {
  const item = objectValue(value, `workspace projection columns[${index}]`);
  return {
    name: stringValue(item.name, `workspace projection columns[${index}].name`),
    dtype: optionalString(item.dtype, `workspace projection columns[${index}].dtype`),
    nullCount: nullableNumber(
      item.null_count,
      `workspace projection columns[${index}].null_count`,
    ),
    nullPct: nullableNumber(
      item.null_pct,
      `workspace projection columns[${index}].null_pct`,
    ),
    ref: stringValue(item.ref, `workspace projection columns[${index}].ref`),
    snapshot: stringValue(
      item.snapshot,
      `workspace projection columns[${index}].snapshot`,
    ),
    sourceColumn: optionalString(
      item.source_column,
      `workspace projection columns[${index}].source_column`,
    ),
    createdByUnitId:
      item.created_by_unit_id === null || item.created_by_unit_id === undefined
        ? null
        : numberValue(
            item.created_by_unit_id,
            `workspace projection columns[${index}].created_by_unit_id`,
          ),
    availability: availabilityValue(
      item.availability,
      `workspace projection columns[${index}].availability`,
    ),
  };
}

function decodeWorkspaceSnapshots(payload: unknown): SnapshotSummary[] {
  const value = objectValue(payload, "workspace projection response");
  if (!Array.isArray(value.snapshots)) {
    throw new Error("Invalid API response: workspace projection snapshots must be an array");
  }
  return value.snapshots.map((item, index) => {
    const snapshot = objectValue(item, `workspace projection snapshots[${index}]`);
    return {
      viewId: stringValue(
        snapshot.view_id,
        `workspace projection snapshots[${index}].view_id`,
      ),
      snapshotId: optionalString(
        snapshot.snapshot_id,
        `workspace projection snapshots[${index}].snapshot_id`,
      ),
      name: stringValue(snapshot.name, `workspace projection snapshots[${index}].name`),
      displayName: stringValue(
        snapshot.display_name,
        `workspace projection snapshots[${index}].display_name`,
      ),
      rowCount: nullableNumber(
        snapshot.row_count,
        `workspace projection snapshots[${index}].row_count`,
      ),
      columnRefs: stringArray(
        snapshot.column_refs,
        `workspace projection snapshots[${index}].column_refs`,
      ),
      sourceId: optionalString(
        snapshot.source_id,
        `workspace projection snapshots[${index}].source_id`,
      ),
      createdByUnitId:
        snapshot.created_by_unit_id === null || snapshot.created_by_unit_id === undefined
          ? null
          : numberValue(
              snapshot.created_by_unit_id,
              `workspace projection snapshots[${index}].created_by_unit_id`,
            ),
      parentSnapshotNames: stringArray(
        snapshot.parent_snapshot_names,
        `workspace projection snapshots[${index}].parent_snapshot_names`,
      ),
      availability: availabilityValue(
        snapshot.availability,
        `workspace projection snapshots[${index}].availability`,
      ),
      profileAvailable:
        typeof snapshot.profile_available === "boolean"
          ? snapshot.profile_available
          : (() => {
              throw new Error(
                `Invalid API response: workspace projection snapshots[${index}].profile_available must be a boolean`,
              );
            })(),
    };
  });
}

function decodeWorkspaceProjection(payload: unknown): DataCatalog {
  const value = objectValue(payload, "workspace projection response");
  return {
    sources: decodeSources({ sources: value.sources }),
    snapshots: decodeWorkspaceSnapshots(payload),
    columns: Array.isArray(value.columns)
      ? value.columns.map(decodeWorkspaceColumn)
      : (() => {
          throw new Error("Invalid API response: workspace projection columns must be an array");
        })(),
    lineage: decodeLineage({ columns: value.lineage }),
    compatibilityWarning: optionalString(
      value.compatibility_warning,
      "workspace projection compatibility_warning",
    ),
  };
}

function decodeProfile(payload: unknown): SourceProfile {
  const value = objectValue(payload, "profile response");
  const profile = objectValue(value.profile ?? payload, "profile");
  const shapeValue = profile.shape;
  if (
    !Array.isArray(shapeValue) ||
    shapeValue.length !== 2 ||
    shapeValue.some((item) => typeof item !== "number")
  ) {
    throw new Error("Invalid API response: profile.shape must contain two numbers");
  }
  const columns = profile.columns;
  if (!Array.isArray(columns)) {
    throw new Error("Invalid API response: profile.columns must be an array");
  }
  return {
    sourceId: stringValue(value.source_id, "profile.source_id"),
    snapshotId: stringValue(value.snapshot_id, "profile.snapshot_id"),
    snapshotName: stringValue(value.snapshot_name, "profile.snapshot_name"),
    displayName: stringValue(value.display_name, "profile.display_name"),
    shape: [shapeValue[0] as number, shapeValue[1] as number],
    columns: columns.map(decodeColumn),
    encoding: optionalString(profile.encoding, "profile.encoding"),
    statistics: objectValue(profile.statistics, "profile.statistics") as Record<
      string,
      Record<string, unknown>
    >,
    headSample: recordArray(profile.head_sample, "profile.head_sample"),
  };
}

function decodeUpload(payload: unknown): UploadResult {
  const value = objectValue(payload, "upload response");
  return {
    fileName: stringValue(value.file_name, "upload.file_name"),
    rowCount: numberValue(value.row_count, "upload.row_count"),
    columnCount: numberValue(value.col_count, "upload.col_count"),
    sourceId: optionalString(value.source_id, "upload.source_id"),
    snapshotId: optionalString(value.snapshot_id, "upload.snapshot_id"),
    snapshotName: optionalString(value.snapshot_name, "upload.snapshot_name"),
    columns: Array.isArray(value.columns) ? value.columns.map(decodeColumn) : [],
  };
}

export function getSources(projectId: string, signal?: AbortSignal): Promise<SourceSummary[]> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/sources`,
    { signal },
    decodeSources,
  );
}

export function getSnapshots(
  projectId: string,
  signal?: AbortSignal,
): Promise<SnapshotSummary[]> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/snapshots`,
    { signal },
    decodeSnapshots,
  );
}

export function getColumns(projectId: string, signal?: AbortSignal): Promise<PublicColumn[]> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/columns`,
    { signal },
    (payload) => decodeColumnsProjection(payload).columns,
  );
}

export function getLineage(projectId: string, signal?: AbortSignal): Promise<LineageColumn[]> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/lineage`,
    { signal },
    decodeLineage,
  );
}

export function getProfile(
  projectId: string,
  sourceId: string,
  signal?: AbortSignal,
): Promise<SourceProfile> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/profile?source_id=${encodeURIComponent(sourceId)}`,
    { signal },
    decodeProfile,
  );
}

export function uploadSource(
  projectId: string,
  file: File,
  signal?: AbortSignal,
): Promise<UploadResult> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/upload`,
    { method: "POST", body: form, signal },
    decodeUpload,
  );
}

export async function getDataCatalog(
  projectId: string,
  signal?: AbortSignal,
): Promise<DataCatalog> {
  return apiFetch(
    `/api/sessions/${encodeURIComponent(projectId)}/data/workspace-projection`,
    { signal },
    decodeWorkspaceProjection,
  );
}
