import { WorkspaceUnitPatch } from "../../../api/client";
import { DataCatalog } from "../../../api/dataApi";
import {
  isDeriveUnit,
  isFilterUnit,
  isJoinUnit,
  isTerminalUnit,
  KnownOperation,
  Plan,
  PlanUnit,
} from "../../../domain/plan";

export type OperationKind = KnownOperation;

export interface InitialUnitPayload extends WorkspaceUnitPatch {
  operation: OperationKind;
  purpose: string;
  execution_mode: "llm" | "template";
  depends_on: number[];
}

export interface InitialPayloadResult {
  payload: InitialUnitPayload | null;
  reason: string | null;
}

function snapshotColumns(catalog: DataCatalog, snapshot: string) {
  return catalog.columns.filter((column) => column.snapshot === snapshot);
}

function safeName(value: string): string {
  const normalized = value.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "");
  return normalized || "result";
}

function uniqueSnapshotName(catalog: DataCatalog, base: string, plan?: Plan | null): string {
  const existing = new Set(catalog.snapshots.map((snapshot) => snapshot.name));
  for (const unit of plan?.units ?? []) {
    if (isFilterUnit(unit)) {
      existing.add(unit.output_snapshot);
    } else if (isJoinUnit(unit)) {
      existing.add(unit.output_snapshot);
    }
  }
  const stem = safeName(base);
  let candidate = stem;
  let suffix = 2;
  while (existing.has(candidate)) {
    candidate = `${stem}_${suffix}`;
    suffix += 1;
  }
  return candidate;
}

function uniqueOutputRef(catalog: DataCatalog, snapshot: string, plan?: Plan | null): string {
  const existing = new Set(
    catalog.columns
      .filter((column) => column.snapshot === snapshot)
      .map((column) => column.name),
  );
  for (const unit of plan?.units ?? []) {
    if (isDeriveUnit(unit) && unit.input_snapshot === snapshot) {
      unit.output_columns.forEach((ref) => existing.add(ref.split(".").pop() ?? ref));
    }
  }
  const stem = "derived_value";
  let name = stem;
  let suffix = 2;
  while (existing.has(name)) {
    name = `${stem}_${suffix}`;
    suffix += 1;
  }
  return `${snapshot}.${name}`;
}

function selectedOrFirst(
  catalog: DataCatalog,
  snapshot: string,
  selectedRef: string | undefined,
): string | null {
  const columns = snapshotColumns(catalog, snapshot);
  if (selectedRef && columns.some((column) => column.ref === selectedRef)) {
    return selectedRef;
  }
  return columns[0]?.ref ?? null;
}

function planSnapshotProducers(plan: Plan | null | undefined): Map<string, number> {
  const producers = new Map<string, number>();
  for (const unit of plan?.units ?? []) {
    if (isDeriveUnit(unit)) {
      producers.set(unit.input_snapshot, unit.unit_id);
    } else if (isFilterUnit(unit)) {
      producers.set(unit.output_snapshot, unit.unit_id);
    } else if (isJoinUnit(unit)) {
      producers.set(unit.output_snapshot, unit.unit_id);
    }
  }
  return producers;
}

function dependenciesForSnapshots(
  catalog: DataCatalog,
  snapshotNames: string[],
  plan?: Plan | null,
): number[] {
  const planProducers = planSnapshotProducers(plan);
  const dependencies = new Set<number>();
  snapshotNames.forEach((snapshotName) => {
    const catalogSnapshot = catalog.snapshots.find((snapshot) => snapshot.name === snapshotName);
    if (catalogSnapshot?.createdByUnitId !== null && catalogSnapshot?.createdByUnitId !== undefined) {
      dependencies.add(catalogSnapshot.createdByUnitId);
    }
    const planProducer = planProducers.get(snapshotName);
    if (planProducer !== undefined) {
      dependencies.add(planProducer);
    }
  });
  return [...dependencies].sort((left, right) => left - right);
}

export function buildInitialUnitPayload(
  operation: OperationKind,
  catalog: DataCatalog,
  selectedRef?: string,
  plan?: Plan | null,
): InitialPayloadResult {
  if (catalog.snapshots.length === 0) {
    return { payload: null, reason: "Upload at least one Source before adding an operation." };
  }
  const firstSnapshot = catalog.snapshots[0].name;
  const firstColumn = selectedOrFirst(catalog, firstSnapshot, selectedRef);
  if (!firstColumn) {
    return { payload: null, reason: "The selected Snapshot has no visible columns." };
  }

  if (operation === "join") {
    if (catalog.snapshots.length < 2) {
      return { payload: null, reason: "Join requires two Sources or Snapshots." };
    }
    const leftSnapshot = catalog.snapshots[0].name;
    const rightSnapshot = catalog.snapshots[1].name;
    const leftColumn = selectedOrFirst(catalog, leftSnapshot, selectedRef) ?? firstColumn;
    const rightColumn = snapshotColumns(catalog, rightSnapshot)[0]?.ref;
    if (!rightColumn) {
      return { payload: null, reason: "The right Snapshot has no visible columns." };
    }
    return {
      payload: {
        operation,
        purpose: "Combine related records from two Snapshots",
        execution_mode: "llm",
        depends_on: dependenciesForSnapshots(catalog, [leftSnapshot, rightSnapshot], plan),
        inputs: [
          { role: "left", snapshot: leftSnapshot },
          { role: "right", snapshot: rightSnapshot },
        ],
        keys: [{ left: leftColumn, right: rightColumn }],
        select: [
          { from: leftColumn, as: `${safeName(leftColumn.split(".").at(-1) ?? "left")}_left` },
          { from: rightColumn, as: `${safeName(rightColumn.split(".").at(-1) ?? "right")}_right` },
        ],
        how: "left",
          output_snapshot: uniqueSnapshotName(catalog, `${leftSnapshot}_${rightSnapshot}_joined`, plan),
      },
      reason: null,
    };
  }

  if (operation === "derive_column") {
    return {
      payload: {
        operation,
        purpose: "Derive a declared column",
        execution_mode: "llm",
        depends_on: dependenciesForSnapshots(catalog, [firstSnapshot], plan),
        input_snapshot: firstSnapshot,
        input_columns: [firstColumn],
        output_columns: [uniqueOutputRef(catalog, firstSnapshot, plan)],
      },
      reason: null,
    };
  }

  if (operation === "filter") {
    return {
      payload: {
        operation,
        purpose: "Filter a Snapshot into a named subset",
        execution_mode: "llm",
        depends_on: dependenciesForSnapshots(catalog, [firstSnapshot], plan),
        input_snapshot: firstSnapshot,
        input_columns: [firstColumn],
        output_snapshot: uniqueSnapshotName(catalog, `${firstSnapshot}_filtered`, plan),
      },
      reason: null,
    };
  }

  return {
    payload: {
      operation,
      purpose: "Produce terminal analysis evidence",
      execution_mode: "llm",
      depends_on: dependenciesForSnapshots(catalog, [firstSnapshot], plan),
      input_snapshot: firstSnapshot,
      input_columns: [firstColumn],
    },
    reason: null,
  };
}

export function unitToPayload(unit: PlanUnit): WorkspaceUnitPatch | null {
  const common: WorkspaceUnitPatch = {
    operation: unit.operation,
    purpose: unit.purpose,
    model: unit.model_hint ?? null,
    cautious: unit.cautious ?? "",
    execution_mode: unit.execution_mode ?? "llm",
    depends_on: [...unit.depends_on],
    template_name: unit.template_name ?? null,
    template_params: unit.template_params ?? null,
  };
  if (isDeriveUnit(unit)) {
    return {
      ...common,
      input_snapshot: unit.input_snapshot,
      input_columns: [...unit.input_columns],
      output_columns: [...unit.output_columns],
    };
  }
  if (isFilterUnit(unit)) {
    return {
      ...common,
      input_snapshot: unit.input_snapshot,
      input_columns: [...unit.input_columns],
      output_snapshot: unit.output_snapshot,
    };
  }
  if (isJoinUnit(unit)) {
    return {
      ...common,
      inputs: unit.inputs.map((input) => ({ ...input })),
      keys: unit.keys.map((key) => ({ ...key })),
      select: unit.select.map((selected) => ({ ...selected })),
      how: unit.how,
      output_snapshot: unit.output_snapshot,
    };
  }
  if (isTerminalUnit(unit)) {
    return {
      ...common,
      input_snapshot: unit.input_snapshot,
      input_columns: [...unit.input_columns],
    };
  }
  return null;
}
