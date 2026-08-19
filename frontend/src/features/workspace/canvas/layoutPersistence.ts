import type { WorkspaceLayout } from "../../../domain/plan";

export const MAX_LAYOUT_COORDINATE = 1_000_000;

interface LayoutPosition {
  x: number;
  y: number;
}

function validCoordinate(value: number): boolean {
  return Number.isFinite(value) && Math.abs(value) <= MAX_LAYOUT_COORDINATE;
}

export function isValidWorkspaceLayout(layout: WorkspaceLayout): boolean {
  if (layout.version !== 1) {
    return false;
  }
  if (
    !validCoordinate(layout.viewport.x) ||
    !validCoordinate(layout.viewport.y) ||
    !Number.isFinite(layout.viewport.zoom) ||
    layout.viewport.zoom <= 0 ||
    layout.viewport.zoom > 4
  ) {
    return false;
  }

  const unitIds = new Set<number>();
  return layout.nodes.every((node) => {
    if (
      !Number.isSafeInteger(node.unit_id) ||
      node.unit_id <= 0 ||
      unitIds.has(node.unit_id) ||
      !validCoordinate(node.x) ||
      !validCoordinate(node.y) ||
      typeof node.collapsed !== "boolean"
    ) {
      return false;
    }
    unitIds.add(node.unit_id);
    return true;
  });
}

export function layoutWithPositions(
  layout: WorkspaceLayout,
  positions: ReadonlyMap<number, LayoutPosition>,
): WorkspaceLayout | null {
  const nextLayout: WorkspaceLayout = {
    ...layout,
    nodes: layout.nodes.map((node) => {
      const position = positions.get(node.unit_id);
      return position ? { ...node, x: position.x, y: position.y } : node;
    }),
  };
  return isValidWorkspaceLayout(nextLayout) ? nextLayout : null;
}

export function layoutWithNodePosition(
  layout: WorkspaceLayout,
  unitId: number,
  position: LayoutPosition,
): WorkspaceLayout | null {
  return layoutWithPositions(layout, new Map([[unitId, position]]));
}
