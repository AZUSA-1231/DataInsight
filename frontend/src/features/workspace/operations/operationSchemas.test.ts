import { describe, expect, it } from "vitest";

import { DataCatalog } from "../../../api/dataApi";
import { decodePlan } from "../../../domain/plan";
import { buildInitialUnitPayload } from "./operationSchemas";

const catalog: DataCatalog = {
  sources: [],
  snapshots: [
    {
      viewId: "snapshot-orders",
      snapshotId: "snapshot-orders",
      name: "orders",
      displayName: "orders.csv",
      rowCount: 10,
      columnRefs: ["orders.amount"],
      sourceId: "source-orders",
      createdByUnitId: null,
      parentSnapshotNames: [],
      availability: "materialized",
      profileAvailable: true,
    },
  ],
  columns: [
    {
      name: "amount",
      dtype: "float64",
      nullCount: 0,
      nullPct: 0,
      ref: "orders.amount",
      snapshot: "orders",
      sourceColumn: "amount",
      createdByUnitId: null,
      availability: "materialized",
    },
  ],
  lineage: [],
  compatibilityWarning: null,
};

describe("initial operation payloads", () => {
  it("includes the existing Plan producer when a new Unit reads its Snapshot", () => {
    const plan = decodePlan({
      units: [
        {
          unit_id: 1,
          operation: "derive_column",
          purpose: "derive",
          depends_on: [],
          input_snapshot: "orders",
          input_columns: ["orders.amount"],
          output_columns: ["orders.revenue"],
        },
      ],
      alignment_notes: "",
    });
    const result = buildInitialUnitPayload("terminal", catalog, undefined, plan);

    expect(result.payload?.depends_on).toEqual([1]);
  });

  it("keeps output names unique against visible Snapshot columns", () => {
    const result = buildInitialUnitPayload("derive_column", catalog);

    expect(result.payload?.output_columns).toEqual(["orders.derived_value"]);
  });

  it("keeps planned output names unique before execution updates the catalog", () => {
    const plan = decodePlan({
      units: [
        {
          unit_id: 1,
          operation: "derive_column",
          purpose: "derive",
          depends_on: [],
          input_snapshot: "orders",
          input_columns: ["orders.amount"],
          output_columns: ["orders.derived_value"],
        },
      ],
      alignment_notes: "",
    });
    const result = buildInitialUnitPayload("derive_column", catalog, undefined, plan);

    expect(result.payload?.output_columns).toEqual(["orders.derived_value_2"]);
  });
});
