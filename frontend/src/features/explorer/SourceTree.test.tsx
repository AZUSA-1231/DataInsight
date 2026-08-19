// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import { DataCatalog } from "../../api/dataApi";
import { SourceTree } from "./SourceTree";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const catalog: DataCatalog = {
  sources: [],
  snapshots: [
    {
      viewId: "plan:unit_2",
      snapshotId: null,
      name: "east_orders",
      displayName: "east_orders",
      rowCount: null,
      columnRefs: ["east_orders.revenue"],
      sourceId: null,
      createdByUnitId: 2,
      parentSnapshotNames: ["orders"],
      availability: "planned",
      profileAvailable: false,
    },
  ],
  columns: [
    {
      name: "revenue",
      dtype: null,
      nullCount: null,
      nullPct: null,
      ref: "east_orders.revenue",
      snapshot: "east_orders",
      sourceColumn: null,
      createdByUnitId: 2,
      availability: "planned",
    },
  ],
  lineage: [],
  compatibilityWarning: null,
};

describe("planned Explorer entries", () => {
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("renders pending row and column facts as draggable schema", () => {
    const container = document.createElement("div");
    document.body.appendChild(container);
    act(() => {
      root = createRoot(container);
      root.render(<SourceTree catalog={catalog} onSelect={() => undefined} selection={null} />);
    });

    expect(container.textContent).toContain("Planned");
    expect(container.textContent).toContain("Pending rows");
    expect(container.textContent).toContain("Pending type");
    expect(container.querySelector(".tree-column-row")?.getAttribute("draggable")).toBe("true");
  });
});
