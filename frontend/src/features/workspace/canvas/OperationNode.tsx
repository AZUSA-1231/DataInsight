import { Handle, NodeToolbar, Position } from "@xyflow/react";
import type { NodeProps } from "@xyflow/react";

import {
  isDeriveUnit,
  isFilterUnit,
  isJoinUnit,
  isTerminalUnit,
  PlanUnit,
} from "../../../domain/plan";
import { parseDragPayload } from "../operations/dropIntents";
import type { ColumnDropSlot, QualifiedColumnDrag } from "../operations/dropIntents";
import { PlanCanvasNode } from "./planMapper";

function operationLabel(unit: PlanUnit): string {
  switch (unit.operation) {
    case "derive_column":
      return "Derive column";
    case "filter":
      return "Filter rows";
    case "join":
      return "Join snapshots";
    case "terminal":
      return "Terminal analysis";
    default:
      return unit.operation || "Unknown operation";
  }
}

function operationClass(operation: string): string {
  switch (operation) {
    case "derive_column":
      return "canvas-node-derive";
    case "filter":
      return "canvas-node-filter";
    case "join":
      return "canvas-node-join";
    case "terminal":
      return "canvas-node-terminal";
    default:
      return "canvas-node-unknown";
  }
}

function unitSummary(unit: PlanUnit): string {
  if (isDeriveUnit(unit)) {
    return `${unit.input_snapshot} -> ${unit.output_columns.join(", ")}`;
  }
  if (isFilterUnit(unit)) {
    return `${unit.input_snapshot} -> ${unit.output_snapshot}`;
  }
  if (isJoinUnit(unit)) {
    return `${unit.inputs.map((input) => input.snapshot).join(" + ")} -> ${unit.output_snapshot}`;
  }
  if (isTerminalUnit(unit)) {
    return `${unit.input_snapshot} · ${unit.input_columns.length} columns`;
  }
  return "Legacy or unsupported unit shape";
}

function detailItems(unit: PlanUnit): string[] {
  if (isJoinUnit(unit)) {
    return [
      `${unit.how} join`,
      `${unit.keys.length} key pair${unit.keys.length === 1 ? "" : "s"}`,
      `${unit.select.length} selected output${unit.select.length === 1 ? "" : "s"}`,
    ];
  }
  if (isDeriveUnit(unit)) {
    return [`${unit.input_columns.length} input column${unit.input_columns.length === 1 ? "" : "s"}`];
  }
  if (isFilterUnit(unit)) {
    return [`${unit.input_columns.length} predicate column${unit.input_columns.length === 1 ? "" : "s"}`];
  }
  if (isTerminalUnit(unit)) {
    return [`${unit.input_columns.length} selected column${unit.input_columns.length === 1 ? "" : "s"}`];
  }
  return ["Rendered read-only until its operation contract is supported"];
}

function DropSlot({
  label,
  values,
  slot,
  unitId,
  onDropColumn,
  onRemoveColumn,
  removeValues,
}: {
  label: string;
  values: string[];
  slot: ColumnDropSlot;
  unitId: number;
  onDropColumn?: (unitId: number, slot: ColumnDropSlot, payload: QualifiedColumnDrag) => void;
  onRemoveColumn?: (unitId: number, slot: ColumnDropSlot, ref: string) => void;
  removeValues?: string[];
}): JSX.Element {
  const handleDrop = (event: React.DragEvent<HTMLDivElement>): void => {
    event.preventDefault();
    event.stopPropagation();
    const payload = parseDragPayload(
      event.dataTransfer.getData("application/x-datainsight") || event.dataTransfer.getData("text/plain"),
    );
    if (payload?.kind === "qualified-column") {
      onDropColumn?.(unitId, slot, payload);
    }
  };
  return (
    <div
      aria-label={label}
      className={`canvas-drop-slot canvas-drop-slot-${slot}`}
      role="group"
      tabIndex={0}
      onDragOver={(event) => {
        event.preventDefault();
        event.stopPropagation();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDrop={handleDrop}
    >
      <span className="canvas-slot-label">{label}</span>
      <div className="canvas-slot-values">
        {values.length > 0 ? values.map((value, index) => {
          const ref = removeValues?.[index] ?? value;
          return (
            <span className="canvas-slot-value" key={`${value}-${index}`} title={value}>
              {value || "Unassigned"}
              {ref ? (
                <button
                  aria-label={`Remove ${value}`}
                  className="canvas-slot-remove"
                  title={`Remove ${value}`}
                  type="button"
                  onClick={(event) => {
                    event.stopPropagation();
                    onRemoveColumn?.(unitId, slot, ref);
                  }}
                >
                  x
                </button>
              ) : null}
            </span>
          );
        }) : <em>Drop a column</em>}
      </div>
    </div>
  );
}

export function OperationNode({ data }: NodeProps<PlanCanvasNode>): JSX.Element {
  const { unit, collapsed, readOnly, onToggle, onDropColumn, onRemoveColumn, inspector, inspectorPosition } = data;
  return (
    <div
      id={`plan-unit-${unit.unit_id}`}
      className={`canvas-operation-node ${operationClass(unit.operation)} ${collapsed ? "collapsed" : ""}`}
      onDragOver={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
      onDrop={(event) => {
        event.preventDefault();
        event.stopPropagation();
      }}
    >
      <NodeToolbar
        className="unit-inspector-toolbar"
        isVisible={Boolean(inspector)}
        position={inspectorPosition === "left" ? Position.Left : Position.Right}
        align="start"
        offset={14}
      >
        {inspector}
      </NodeToolbar>
      <Handle className="canvas-handle" position={Position.Top} type="target" />
      <div className="canvas-node-header">
        <span className="canvas-node-kind">{operationLabel(unit)}</span>
        <span className="canvas-node-id">#{unit.unit_id}</span>
        <button
          aria-label={`${collapsed ? "Expand" : "Collapse"} Unit ${unit.unit_id}`}
          className="canvas-node-collapse"
          title={collapsed ? "Expand unit" : "Collapse unit"}
          type="button"
          onClick={() => onToggle?.(unit.unit_id)}
        >
          {collapsed ? "+" : "-"}
        </button>
      </div>
      <div className="canvas-node-body">
        <strong>{unit.purpose || "Untitled operation"}</strong>
        {readOnly ? <span className="canvas-node-warning">Read-only legacy unit</span> : null}
        <span className="canvas-node-summary">{unitSummary(unit)}</span>
        {!collapsed ? (
          <>
            <div className="canvas-node-details">
              {detailItems(unit).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
            {isDeriveUnit(unit) ? (
              <>
                <DropSlot
                  label="Input columns"
                  onDropColumn={onDropColumn}
                  onRemoveColumn={onRemoveColumn}
                  slot="input_columns"
                  unitId={unit.unit_id}
                  values={unit.input_columns}
                />
              </>
            ) : null}
            {isFilterUnit(unit) ? (
              <DropSlot
                label="Predicate columns"
                onDropColumn={onDropColumn}
                onRemoveColumn={onRemoveColumn}
                slot="input_columns"
                unitId={unit.unit_id}
                values={unit.input_columns}
              />
            ) : null}
            {isTerminalUnit(unit) ? (
              <DropSlot
                label="Analysis columns"
                onDropColumn={onDropColumn}
                onRemoveColumn={onRemoveColumn}
                slot="input_columns"
                unitId={unit.unit_id}
                values={unit.input_columns}
              />
            ) : null}
            {isJoinUnit(unit) ? (
              <>
                <DropSlot
                  label="Left key"
                  onDropColumn={onDropColumn}
                  onRemoveColumn={onRemoveColumn}
                  removeValues={unit.keys.map((key) => key.left)}
                  slot="join_left_key"
                  unitId={unit.unit_id}
                  values={unit.keys.map((key) => key.left)}
                />
                <DropSlot
                  label="Right key"
                  onDropColumn={onDropColumn}
                  onRemoveColumn={onRemoveColumn}
                  removeValues={unit.keys.map((key) => key.right)}
                  slot="join_right_key"
                  unitId={unit.unit_id}
                  values={unit.keys.map((key) => key.right)}
                />
                <DropSlot
                  label="Selected outputs"
                  onDropColumn={onDropColumn}
                  onRemoveColumn={onRemoveColumn}
                  removeValues={unit.select.map((selected) => selected.from)}
                  slot="join_selected_output"
                  unitId={unit.unit_id}
                  values={unit.select.map((selected) => `${selected.from} as ${selected.as}`)}
                />
              </>
            ) : null}
          </>
        ) : null}
      </div>
      <div className="canvas-node-footer">
        <span>{unit.depends_on.length} upstream</span>
        {unit.execution_mode ? <span>{unit.execution_mode}</span> : null}
      </div>
      <Handle className="canvas-handle" position={Position.Bottom} type="source" />
    </div>
  );
}
