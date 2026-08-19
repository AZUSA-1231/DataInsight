import { describe, expect, it } from "vitest";

import type { WorkspaceLayout } from "../../../domain/plan";
import {
  isValidWorkspaceLayout,
  layoutWithNodePosition,
  layoutWithPositions,
} from "./layoutPersistence";

const layout: WorkspaceLayout = {
  version: 1,
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [{ unit_id: 1, x: 40, y: 60, collapsed: false }],
};

describe("workspace layout persistence guards", () => {
  it("accepts complete finite layouts and applies positions without changing shape", () => {
    const next = layoutWithNodePosition(layout, 1, { x: 320, y: 180 });

    expect(next).toEqual({
      ...layout,
      nodes: [{ unit_id: 1, x: 320, y: 180, collapsed: false }],
    });
    expect(isValidWorkspaceLayout(next as WorkspaceLayout)).toBe(true);
  });

  it("updates several final positions in one layout", () => {
    const next = layoutWithPositions(
      {
        ...layout,
        nodes: [{ ...layout.nodes[0] }, { unit_id: 2, x: 80, y: 90, collapsed: true }],
      },
      new Map([
        [1, { x: 100, y: 120 }],
        [2, { x: 400, y: 500 }],
      ]),
    );

    expect(next?.nodes).toEqual([
      { unit_id: 1, x: 100, y: 120, collapsed: false },
      { unit_id: 2, x: 400, y: 500, collapsed: true },
    ]);
  });

  it("rejects non-finite, out-of-range, duplicate, and invalid viewport values locally", () => {
    expect(layoutWithNodePosition(layout, 1, { x: Number.NaN, y: 10 })).toBeNull();
    expect(layoutWithNodePosition(layout, 1, { x: 1_000_001, y: 10 })).toBeNull();
    expect(
      isValidWorkspaceLayout({
        ...layout,
        viewport: { x: 0, y: 0, zoom: 5 },
      }),
    ).toBe(false);
    expect(
      isValidWorkspaceLayout({
        ...layout,
        nodes: [...layout.nodes, { ...layout.nodes[0] }],
      }),
    ).toBe(false);
  });
});
