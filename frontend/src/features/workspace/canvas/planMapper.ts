import type { Edge, Node } from "@xyflow/react";

import {
  Plan,
  PlanUnit,
  WorkspaceLayout,
  WorkspaceNodeLayout,
} from "../../../domain/plan";
import type { ColumnDropSlot, QualifiedColumnDrag } from "../operations/dropIntents";

export const CANVAS_NODE_WIDTH = 276;
export const CANVAS_NODE_HEIGHT = 238;
const CANVAS_COLUMN_GAP = 360;
const CANVAS_ROW_GAP = 210;
const CANVAS_ORIGIN_X = 72;
const CANVAS_ORIGIN_Y = 64;

export interface PlanCanvasNodeData extends Record<string, unknown> {
  unit: PlanUnit;
  collapsed: boolean;
  readOnly: boolean;
  inspector?: JSX.Element | null;
  inspectorPosition?: "left" | "right";
  onToggle?: (unitId: number) => void;
  onDropColumn?: (unitId: number, slot: ColumnDropSlot, payload: QualifiedColumnDrag) => void;
  onRemoveColumn?: (unitId: number, slot: ColumnDropSlot, ref: string) => void;
}

export type PlanCanvasNode = Node<PlanCanvasNodeData, "operation">;

export interface PlanCanvasMapping {
  nodes: PlanCanvasNode[];
  edges: Edge[];
  layout: WorkspaceLayout;
  layoutChanged: boolean;
}

export function unitNodeId(unitId: number): string {
  return `unit:${unitId}`;
}

export function dependencyEdgeId(sourceUnitId: number, targetUnitId: number): string {
  return `${unitNodeId(sourceUnitId)}->${unitNodeId(targetUnitId)}`;
}

function isKnownOperation(operation: string): boolean {
  return ["derive_column", "filter", "join", "terminal"].includes(operation);
}

function topologicalLevels(units: PlanUnit[]): Map<number, number> {
  const byId = new Map(units.map((unit) => [unit.unit_id, unit]));
  const levels = new Map<number, number>();
  const visiting = new Set<number>();

  const levelFor = (unitId: number): number => {
    const known = levels.get(unitId);
    if (known !== undefined) {
      return known;
    }
    if (visiting.has(unitId)) {
      return 0;
    }
    const unit = byId.get(unitId);
    if (!unit) {
      return 0;
    }
    visiting.add(unitId);
    const level = unit.depends_on.reduce((maximum, dependencyId) => {
      if (!byId.has(dependencyId)) {
        return maximum;
      }
      return Math.max(maximum, levelFor(dependencyId) + 1);
    }, 0);
    visiting.delete(unitId);
    levels.set(unitId, level);
    return level;
  };

  units.forEach((unit) => levelFor(unit.unit_id));
  return levels;
}

function fallbackPositions(units: PlanUnit[]): Map<number, { x: number; y: number }> {
  const levels = topologicalLevels(units);
  const byLevel = new Map<number, number[]>();
  units.forEach((unit) => {
    const level = levels.get(unit.unit_id) ?? 0;
    const ids = byLevel.get(level) ?? [];
    ids.push(unit.unit_id);
    byLevel.set(level, ids);
  });

  const positions = new Map<number, { x: number; y: number }>();
  [...byLevel.entries()]
    .sort(([left], [right]) => left - right)
    .forEach(([level, unitIds]) => {
      unitIds
        .sort((left, right) => left - right)
        .forEach((unitId, row) => {
          positions.set(unitId, {
            x: CANVAS_ORIGIN_X + level * CANVAS_COLUMN_GAP,
            y: CANVAS_ORIGIN_Y + row * CANVAS_ROW_GAP,
          });
        });
    });
  return positions;
}

function sameLayoutNode(left: WorkspaceNodeLayout, right: WorkspaceNodeLayout): boolean {
  return (
    left.unit_id === right.unit_id &&
    left.x === right.x &&
    left.y === right.y &&
    left.collapsed === right.collapsed
  );
}

function normalizeLayout(plan: Plan | null, layout: WorkspaceLayout): {
  layout: WorkspaceLayout;
  layoutChanged: boolean;
} {
  const units = plan?.units ?? [];
  const currentIds = new Set(units.map((unit) => unit.unit_id));
  const savedById = new Map<number, WorkspaceNodeLayout>();
  let layoutChanged = false;
  layout.nodes.forEach((node) => {
    if (!currentIds.has(node.unit_id) || savedById.has(node.unit_id)) {
      layoutChanged = true;
      return;
    }
    savedById.set(node.unit_id, node);
  });

  const fallback = fallbackPositions(units);
  const nodes = units.map((unit) => {
    const saved = savedById.get(unit.unit_id);
    if (saved) {
      return { ...saved };
    }
    layoutChanged = true;
    const position = fallback.get(unit.unit_id) ?? { x: CANVAS_ORIGIN_X, y: CANVAS_ORIGIN_Y };
    return { unit_id: unit.unit_id, ...position, collapsed: false };
  });

  if (
    nodes.length !== layout.nodes.length ||
    nodes.some((node, index) => !sameLayoutNode(node, layout.nodes[index] ?? node))
  ) {
    layoutChanged = true;
  }

  return {
    layout: {
      version: 1,
      viewport: { ...layout.viewport },
      nodes,
    },
    layoutChanged,
  };
}

export function toPlanCanvas(plan: Plan | null, layout: WorkspaceLayout): PlanCanvasMapping {
  const normalized = normalizeLayout(plan, layout);
  const units = plan?.units ?? [];
  const layoutById = new Map(normalized.layout.nodes.map((node) => [node.unit_id, node]));
  const currentIds = new Set(units.map((unit) => unit.unit_id));

  const nodes: PlanCanvasNode[] = units.map((unit) => {
    const nodeLayout = layoutById.get(unit.unit_id);
    return {
      id: unitNodeId(unit.unit_id),
      type: "operation",
      position: { x: nodeLayout?.x ?? CANVAS_ORIGIN_X, y: nodeLayout?.y ?? CANVAS_ORIGIN_Y },
      data: {
        unit,
        collapsed: nodeLayout?.collapsed ?? false,
        readOnly: !isKnownOperation(unit.operation),
      },
      draggable: true,
      selectable: true,
    };
  });

  const edges: Edge[] = [];
  units.forEach((target) => {
    target.depends_on.forEach((sourceUnitId) => {
      if (!currentIds.has(sourceUnitId)) {
        return;
      }
      edges.push({
        id: dependencyEdgeId(sourceUnitId, target.unit_id),
        source: unitNodeId(sourceUnitId),
        target: unitNodeId(target.unit_id),
        type: "smoothstep",
      });
    });
  });

  return {
    nodes,
    edges,
    layout: normalized.layout,
    layoutChanged: normalized.layoutChanged,
  };
}
