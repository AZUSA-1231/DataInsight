import { WorkspaceUnitPatch } from "../../../api/client";
import {
  isDeriveUnit,
  isFilterUnit,
  isJoinUnit,
  isTerminalUnit,
  PlanUnit,
} from "../../../domain/plan";

export interface QualifiedColumnDrag {
  kind: "qualified-column";
  ref: string;
  snapshot: string;
}

export type DragPayload = QualifiedColumnDrag;

export type ColumnDropSlot =
  | "input_columns"
  | "join_left_key"
  | "join_right_key"
  | "join_selected_output";

export type DropIntent =
  | { kind: "patch"; patch: WorkspaceUnitPatch; message: string }
  | { kind: "rejected"; reason: string };

export function serializeDragPayload(payload: DragPayload): string {
  return JSON.stringify(payload);
}

export function parseDragPayload(value: string | null): DragPayload | null {
  if (!value) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") {
      return null;
    }
    const item = parsed as Record<string, unknown>;
    if (
      item.kind === "qualified-column" &&
      typeof item.ref === "string" &&
      typeof item.snapshot === "string" &&
      item.ref.startsWith(`${item.snapshot}.`)
    ) {
      return { kind: "qualified-column", ref: item.ref, snapshot: item.snapshot };
    }
  } catch {
    return null;
  }
  return null;
}

function appendUnique(values: string[], value: string): string[] | null {
  if (values.includes(value)) {
    return null;
  }
  return [...values, value];
}

function joinRoleSnapshot(unit: PlanUnit, role: "left" | "right"): string | null {
  if (!isJoinUnit(unit)) {
    return null;
  }
  return unit.inputs.find((input) => input.role === role)?.snapshot ?? null;
}

function aliasFor(ref: string, existing: string[]): string {
  const base = ref.split(".").at(-1) || "column";
  let alias = base;
  let suffix = 2;
  while (existing.includes(alias)) {
    alias = `${base}_${suffix}`;
    suffix += 1;
  }
  return alias;
}

export function resolveColumnDrop(
  payload: QualifiedColumnDrag,
  slot: ColumnDropSlot,
  unit: PlanUnit,
): DropIntent {
  if (slot === "input_columns") {
    if (!isDeriveUnit(unit) && !isFilterUnit(unit) && !isTerminalUnit(unit)) {
      return { kind: "rejected", reason: "This operation has no generic input-column slot." };
    }
    const snapshot = unit.input_snapshot;
    if (payload.snapshot !== snapshot) {
      return {
        kind: "rejected",
        reason: `Use a column from Snapshot '${snapshot}' for this slot.`,
      };
    }
    const next = appendUnique(unit.input_columns, payload.ref);
    if (!next) {
      return { kind: "rejected", reason: "That column is already in this input list." };
    }
    return {
      kind: "patch",
      patch: { input_columns: next },
      message: `Added ${payload.ref} to input columns`,
    };
  }

  if (slot === "join_selected_output") {
    if (!isJoinUnit(unit)) {
      return { kind: "rejected", reason: "Selected outputs are available only on Join." };
    }
    const roleSnapshot = unit.inputs.some((input) => input.snapshot === payload.snapshot);
    if (!roleSnapshot) {
      return { kind: "rejected", reason: "The selected column is not from a Join input Snapshot." };
    }
    if ((unit.how === "semi" || unit.how === "anti") && payload.snapshot !== joinRoleSnapshot(unit, "left")) {
      return { kind: "rejected", reason: `${unit.how} joins may select columns only from the left Snapshot.` };
    }
    if (unit.select.some((selected) => selected.from === payload.ref)) {
      return { kind: "rejected", reason: "That column is already selected by this Join." };
    }
    const alias = aliasFor(payload.ref, unit.select.map((selected) => selected.as));
    return {
      kind: "patch",
      patch: { select: [...unit.select, { from: payload.ref, as: alias }] },
      message: `Added ${payload.ref} as ${alias}`,
    };
  }

  if (slot === "join_left_key" || slot === "join_right_key") {
    if (!isJoinUnit(unit)) {
      return { kind: "rejected", reason: "Join key slots are available only on Join." };
    }
    const role = slot === "join_left_key" ? "left" : "right";
    const expectedSnapshot = joinRoleSnapshot(unit, role);
    if (payload.snapshot !== expectedSnapshot) {
      return { kind: "rejected", reason: `Use a column from the Join ${role} Snapshot.` };
    }
    const keys = unit.keys.length === 0
      ? [{ left: role === "left" ? payload.ref : "", right: role === "right" ? payload.ref : "" }]
      : unit.keys.map((key, index) =>
          index === 0 ? { ...key, [role]: payload.ref } : { ...key },
        );
    return {
      kind: "patch",
      patch: { keys },
      message: `Updated the Join ${role} key`,
    };
  }

  return { kind: "rejected", reason: "This drop target is not available." };
}

export function resolveColumnRemove(
  slot: ColumnDropSlot,
  unit: PlanUnit,
  ref: string,
): DropIntent {
  if (slot === "input_columns") {
    if (!isDeriveUnit(unit) && !isFilterUnit(unit) && !isTerminalUnit(unit)) {
      return { kind: "rejected", reason: "This operation has no generic input-column slot." };
    }
    if (!unit.input_columns.includes(ref)) {
      return { kind: "rejected", reason: "That column is not in this input list." };
    }
    return {
      kind: "patch",
      patch: { input_columns: unit.input_columns.filter((value) => value !== ref) },
      message: `Removed ${ref} from input columns`,
    };
  }

  if (slot === "join_selected_output") {
    if (!isJoinUnit(unit)) {
      return { kind: "rejected", reason: "Selected outputs are available only on Join." };
    }
    if (!unit.select.some((selected) => selected.from === ref)) {
      return { kind: "rejected", reason: "That column is not selected by this Join." };
    }
    return {
      kind: "patch",
      patch: { select: unit.select.filter((selected) => selected.from !== ref) },
      message: `Removed ${ref} from selected outputs`,
    };
  }

  if (slot === "join_left_key" || slot === "join_right_key") {
    if (!isJoinUnit(unit)) {
      return { kind: "rejected", reason: "Join key slots are available only on Join." };
    }
    const role = slot === "join_left_key" ? "left" : "right";
    if (!unit.keys.some((key) => key[role] === ref)) {
      return { kind: "rejected", reason: "That column is not used by this Join key." };
    }
    return {
      kind: "patch",
      patch: { keys: unit.keys.filter((key) => key[role] !== ref) },
      message: `Removed the Join ${role} key`,
    };
  }

  return { kind: "rejected", reason: "This drop target is not available." };
}

export function resolveEmptyCanvasDrop(payload: QualifiedColumnDrag): DropIntent {
  return {
    kind: "rejected",
    reason: `Drop ${payload.ref} onto a Unit slot to add it.`,
  };
}
