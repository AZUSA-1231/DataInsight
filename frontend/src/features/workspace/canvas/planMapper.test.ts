import { describe, expect, it } from "vitest";

import { decodePlan } from "../../../domain/plan";
import { WorkspaceLayout } from "../../../domain/plan";
import {
  dependencyEdgeId,
  toPlanCanvas,
  unitNodeId,
} from "./planMapper";

const emptyLayout: WorkspaceLayout = {
  version: 1,
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [],
};

function planFromUnits(units: unknown[]): ReturnType<typeof decodePlan> {
  return decodePlan({ units, alignment_notes: "" });
}

describe("Plan Canvas mapper", () => {
  it("maps every Plan Unit to one stable node and every dependency to one edge", () => {
    const plan = planFromUnits([
      { unit_id: 4, operation: "legacy", purpose: "Root", depends_on: [] },
      { unit_id: 9, operation: "legacy", purpose: "Leaf", depends_on: [4] },
    ]);
    const mapping = toPlanCanvas(plan, emptyLayout);

    expect(mapping.nodes.map((node) => node.id)).toEqual([unitNodeId(4), unitNodeId(9)]);
    expect(mapping.edges).toEqual([
      {
        id: dependencyEdgeId(4, 9),
        source: unitNodeId(4),
        target: unitNodeId(9),
        type: "smoothstep",
      },
    ]);
    expect(mapping.nodes[0].data.readOnly).toBe(true);
  });

  it("uses deterministic topological fallback positions for missing layout nodes", () => {
    const plan = planFromUnits([
      { unit_id: 9, operation: "legacy", purpose: "Leaf", depends_on: [4] },
      { unit_id: 4, operation: "legacy", purpose: "Root", depends_on: [] },
      { unit_id: 2, operation: "legacy", purpose: "Other root", depends_on: [] },
    ]);
    const mapping = toPlanCanvas(plan, emptyLayout);

    expect(mapping.layout.nodes).toEqual([
      { unit_id: 9, x: 432, y: 64, collapsed: false },
      { unit_id: 4, x: 72, y: 274, collapsed: false },
      { unit_id: 2, x: 72, y: 64, collapsed: false },
    ]);
  });

  it("prunes ghost layout records and keeps presentation state out of Plan data", () => {
    const plan = planFromUnits([
      { unit_id: 7, operation: "legacy", purpose: "Unit", depends_on: [] },
    ]);
    const mapping = toPlanCanvas(plan, {
      version: 1,
      viewport: { x: 20, y: 30, zoom: 1.25 },
      nodes: [
        { unit_id: 7, x: 200, y: 100, collapsed: true },
        { unit_id: 99, x: 999, y: 999, collapsed: false },
      ],
    });

    expect(mapping.layoutChanged).toBe(true);
    expect(mapping.layout.nodes).toEqual([
      { unit_id: 7, x: 200, y: 100, collapsed: true },
    ]);
    expect(mapping.layout.viewport).toEqual({ x: 20, y: 30, zoom: 1.25 });
    expect(mapping.nodes[0].data.unit.purpose).toBe("Unit");
  });

  it("rebuilds node data from a changed Plan while retaining harmless layout", () => {
    const first = planFromUnits([
      { unit_id: 3, operation: "legacy", purpose: "Before", depends_on: [] },
    ]);
    const second = planFromUnits([
      { unit_id: 3, operation: "legacy", purpose: "After", depends_on: [] },
    ]);
    const layout = {
      version: 1 as const,
      viewport: { x: 0, y: 0, zoom: 1 },
      nodes: [{ unit_id: 3, x: 400, y: 120, collapsed: true }],
    };

    const firstMapping = toPlanCanvas(first, layout);
    const secondMapping = toPlanCanvas(second, firstMapping.layout);

    expect(secondMapping.nodes[0].data.unit.purpose).toBe("After");
    expect(secondMapping.nodes[0].position).toEqual({ x: 400, y: 120 });
    expect(secondMapping.nodes[0].data.collapsed).toBe(true);
  });

  it("renders an empty Plan without inventing nodes or edges", () => {
    const mapping = toPlanCanvas(planFromUnits([]), emptyLayout);
    expect(mapping.nodes).toEqual([]);
    expect(mapping.edges).toEqual([]);
    expect(mapping.layoutChanged).toBe(false);
  });
});
