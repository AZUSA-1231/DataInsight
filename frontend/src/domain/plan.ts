export type KnownOperation = "derive_column" | "filter" | "join" | "terminal";

export interface PlanUnitBase {
  unit_id: number;
  operation: string;
  purpose: string;
  depends_on: number[];
  execution_mode?: string;
  model_hint?: string | null;
  cautious?: string;
  template_name?: string | null;
  template_params?: Record<string, unknown> | null;
}

export interface DeriveColumnUnit extends PlanUnitBase {
  operation: "derive_column";
  input_snapshot: string;
  input_columns: string[];
  output_columns: string[];
}

export interface FilterUnit extends PlanUnitBase {
  operation: "filter";
  input_snapshot: string;
  input_columns: string[];
  output_snapshot: string;
}

export interface JoinInput {
  role: "left" | "right";
  snapshot: string;
}

export interface JoinKey {
  left: string;
  right: string;
}

export interface JoinSelect {
  from: string;
  as: string;
}

export interface JoinUnit extends PlanUnitBase {
  operation: "join";
  inputs: JoinInput[];
  keys: JoinKey[];
  select: JoinSelect[];
  output_snapshot: string;
  how: string;
}

export interface TerminalUnit extends PlanUnitBase {
  operation: "terminal";
  input_snapshot: string;
  input_columns: string[];
}

export interface UnknownPlanUnit extends PlanUnitBase {
  operation: string;
  raw: Record<string, unknown>;
}

export type PlanUnit =
  | DeriveColumnUnit
  | FilterUnit
  | JoinUnit
  | TerminalUnit
  | UnknownPlanUnit;

export function isDeriveUnit(unit: PlanUnit): unit is DeriveColumnUnit {
  return unit.operation === "derive_column" && "input_snapshot" in unit;
}

export function isFilterUnit(unit: PlanUnit): unit is FilterUnit {
  return unit.operation === "filter" && "output_snapshot" in unit;
}

export function isJoinUnit(unit: PlanUnit): unit is JoinUnit {
  return unit.operation === "join" && "inputs" in unit;
}

export function isTerminalUnit(unit: PlanUnit): unit is TerminalUnit {
  return unit.operation === "terminal" && "input_snapshot" in unit;
}

export interface Plan {
  units: PlanUnit[];
  alignment_notes: string;
}

export interface WorkspaceNodeLayout {
  unit_id: number;
  x: number;
  y: number;
  collapsed: boolean;
}

export interface WorkspaceViewport {
  x: number;
  y: number;
  zoom: number;
}

export interface WorkspaceLayout {
  version: 1;
  viewport: WorkspaceViewport;
  nodes: WorkspaceNodeLayout[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function requiredRecord(value: unknown, field: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid API response: ${field} must be an object`);
  }
  return value;
}

function requiredString(value: unknown, field: string): string {
  if (typeof value !== "string") {
    throw new Error(`Invalid API response: ${field} must be a string`);
  }
  return value;
}

function optionalString(value: unknown, field: string): string | null | undefined {
  if (value === null || value === undefined) {
    return value === null ? null : undefined;
  }
  return requiredString(value, field);
}

function requiredPositiveInteger(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value <= 0) {
    throw new Error(`Invalid API response: ${field} must be a positive integer`);
  }
  return value;
}

function requiredStringArray(value: unknown, field: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`Invalid API response: ${field} must be an array of strings`);
  }
  return value as string[];
}

function requiredNumberArray(value: unknown, field: string): number[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "number" || !Number.isInteger(item) || item <= 0)
  ) {
    throw new Error(`Invalid API response: ${field} must be an array of positive integers`);
  }
  return value as number[];
}

function requiredFiniteNumber(value: unknown, field: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`Invalid API response: ${field} must be a finite number`);
  }
  return value;
}

function commonUnit(value: Record<string, unknown>, index: number): PlanUnitBase {
  return {
    unit_id: requiredPositiveInteger(value.unit_id, `units[${index}].unit_id`),
    operation: requiredString(value.operation, `units[${index}].operation`),
    purpose: requiredString(value.purpose, `units[${index}].purpose`),
    depends_on:
      value.depends_on === undefined
        ? []
        : requiredNumberArray(value.depends_on, `units[${index}].depends_on`),
    ...(value.execution_mode === undefined
      ? {}
      : {
          execution_mode: requiredString(
            value.execution_mode,
            `units[${index}].execution_mode`,
          ),
        }),
    ...(value.model_hint === undefined
      ? {}
      : { model_hint: optionalString(value.model_hint, `units[${index}].model_hint`) }),
    ...(value.cautious === undefined
      ? {}
      : { cautious: requiredString(value.cautious, `units[${index}].cautious`) }),
    ...(value.template_name === undefined
      ? {}
      : { template_name: optionalString(value.template_name, `units[${index}].template_name`) }),
    ...(value.template_params === undefined
      ? {}
      : {
          template_params:
            value.template_params === null
              ? null
              : isRecord(value.template_params)
                ? value.template_params
                : (() => {
                    throw new Error(
                      `Invalid API response: units[${index}].template_params must be an object`,
                    );
                  })(),
        }),
  };
}

function decodeJoinInputs(value: unknown, field: string): JoinInput[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid API response: ${field} must be an array`);
  }
  return value.map((item, index) => {
    const input = requiredRecord(item, `${field}[${index}]`);
    const role = requiredString(input.role, `${field}[${index}].role`);
    if (role !== "left" && role !== "right") {
      throw new Error(`Invalid API response: ${field}[${index}].role is invalid`);
    }
    return {
      role,
      snapshot: requiredString(input.snapshot, `${field}[${index}].snapshot`),
    };
  });
}

function decodeJoinKeys(value: unknown, field: string): JoinKey[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid API response: ${field} must be an array`);
  }
  return value.map((item, index) => {
    const key = requiredRecord(item, `${field}[${index}]`);
    return {
      left: requiredString(key.left, `${field}[${index}].left`),
      right: requiredString(key.right, `${field}[${index}].right`),
    };
  });
}

function decodeJoinSelect(value: unknown, field: string): JoinSelect[] {
  if (!Array.isArray(value)) {
    throw new Error(`Invalid API response: ${field} must be an array`);
  }
  return value.map((item, index) => {
    const selected = requiredRecord(item, `${field}[${index}]`);
    return {
      from: requiredString(selected.from, `${field}[${index}].from`),
      as: requiredString(selected.as, `${field}[${index}].as`),
    };
  });
}

function decodeUnit(value: unknown, index: number): PlanUnit {
  const raw = requiredRecord(value, `units[${index}]`);
  const common = commonUnit(raw, index);
  switch (common.operation) {
    case "derive_column":
      return {
        ...common,
        operation: "derive_column",
        input_snapshot: requiredString(raw.input_snapshot, `units[${index}].input_snapshot`),
        input_columns: requiredStringArray(raw.input_columns, `units[${index}].input_columns`),
        output_columns: requiredStringArray(raw.output_columns, `units[${index}].output_columns`),
      };
    case "filter":
      return {
        ...common,
        operation: "filter",
        input_snapshot: requiredString(raw.input_snapshot, `units[${index}].input_snapshot`),
        input_columns: requiredStringArray(raw.input_columns, `units[${index}].input_columns`),
        output_snapshot: requiredString(raw.output_snapshot, `units[${index}].output_snapshot`),
      };
    case "join":
      return {
        ...common,
        operation: "join",
        inputs: decodeJoinInputs(raw.inputs, `units[${index}].inputs`),
        keys: decodeJoinKeys(raw.keys, `units[${index}].keys`),
        select: decodeJoinSelect(raw.select, `units[${index}].select`),
        output_snapshot: requiredString(raw.output_snapshot, `units[${index}].output_snapshot`),
        how: requiredString(raw.how, `units[${index}].how`),
      };
    case "terminal":
      return {
        ...common,
        operation: "terminal",
        input_snapshot: requiredString(raw.input_snapshot, `units[${index}].input_snapshot`),
        input_columns: requiredStringArray(raw.input_columns, `units[${index}].input_columns`),
      };
    default:
      return { ...common, raw };
  }
}

export function decodePlan(payload: unknown): Plan | null {
  if (payload === null) {
    return null;
  }
  const value = requiredRecord(payload, "plan");
  if (!Array.isArray(value.units)) {
    throw new Error("Invalid API response: plan.units must be an array");
  }
  return {
    units: value.units.map(decodeUnit),
    alignment_notes:
      value.alignment_notes === undefined
        ? ""
        : requiredString(value.alignment_notes, "plan.alignment_notes"),
  };
}

export function decodeWorkspaceLayout(payload: unknown): WorkspaceLayout {
  const value = requiredRecord(payload, "workspace layout");
  if (value.version !== 1) {
    throw new Error("Invalid API response: workspace layout version must be 1");
  }
  const viewport = requiredRecord(value.viewport, "workspace layout.viewport");
  const nodesValue = value.nodes;
  if (!Array.isArray(nodesValue)) {
    throw new Error("Invalid API response: workspace layout.nodes must be an array");
  }
  return {
    version: 1,
    viewport: {
      x: requiredFiniteNumber(viewport.x, "workspace layout.viewport.x"),
      y: requiredFiniteNumber(viewport.y, "workspace layout.viewport.y"),
      zoom: requiredFiniteNumber(viewport.zoom, "workspace layout.viewport.zoom"),
    },
    nodes: nodesValue.map((nodeValue, index) => {
      const node = requiredRecord(nodeValue, `workspace layout.nodes[${index}]`);
      if (typeof node.collapsed !== "boolean") {
        throw new Error(
          `Invalid API response: workspace layout.nodes[${index}].collapsed must be a boolean`,
        );
      }
      return {
        unit_id: requiredPositiveInteger(
          node.unit_id,
          `workspace layout.nodes[${index}].unit_id`,
        ),
        x: requiredFiniteNumber(node.x, `workspace layout.nodes[${index}].x`),
        y: requiredFiniteNumber(node.y, `workspace layout.nodes[${index}].y`),
        collapsed: node.collapsed,
      };
    }),
  };
}
