import { describe, expect, it } from "vitest";

import { decodePlan } from "../../../domain/plan";
import {
  parseDragPayload,
  resolveColumnDrop,
  resolveColumnRemove,
  resolveEmptyCanvasDrop,
  serializeDragPayload,
} from "./dropIntents";

function unit(operation: Record<string, unknown>) {
  const plan = decodePlan({ units: [operation], alignment_notes: "" });
  if (!plan) {
    throw new Error("Plan fixture did not decode");
  }
  return plan.units[0];
}

const revenue = { kind: "qualified-column" as const, ref: "orders.revenue", snapshot: "orders" };

describe("qualified column drop intents", () => {
  it("round-trips only typed drag payloads", () => {
    expect(parseDragPayload(serializeDragPayload(revenue))).toEqual(revenue);
    expect(parseDragPayload(JSON.stringify({ kind: "qualified-column", ref: "orders.revenue" }))).toBeNull();
    expect(parseDragPayload(JSON.stringify({ kind: "operation", operation: "join" }))).toBeNull();
  });

  it("maps compatible input drops and rejects duplicates or wrong snapshots", () => {
    const derive = unit({
      unit_id: 1,
      operation: "derive_column",
      purpose: "derive",
      depends_on: [],
      input_snapshot: "orders",
      input_columns: ["orders.amount"],
      output_columns: ["orders.revenue"],
    });
    expect(resolveColumnDrop(revenue, "input_columns", derive)).toMatchObject({
      kind: "patch",
      patch: { input_columns: ["orders.amount", "orders.revenue"] },
    });
    const deriveWithRevenue = unit({
      unit_id: 1,
      operation: "derive_column",
      purpose: "derive",
      depends_on: [],
      input_snapshot: "orders",
      input_columns: ["orders.amount", "orders.revenue"],
      output_columns: ["orders.new_value"],
    });
    expect(resolveColumnDrop(revenue, "input_columns", deriveWithRevenue)).toMatchObject({
      kind: "rejected",
    });
    expect(
      resolveColumnDrop(
        { ...revenue, snapshot: "customers", ref: "customers.name" },
        "input_columns",
        derive,
      ),
    ).toMatchObject({ kind: "rejected" });
    expect(resolveColumnRemove("input_columns", deriveWithRevenue, "orders.revenue")).toMatchObject({
      kind: "patch",
      patch: { input_columns: ["orders.amount"] },
    });
  });

  it("maps Join key and selected-output slots without changing dependencies", () => {
    const join = unit({
      unit_id: 2,
      operation: "join",
      purpose: "join",
      depends_on: [1],
      inputs: [
        { role: "left", snapshot: "orders" },
        { role: "right", snapshot: "customers" },
      ],
      keys: [{ left: "orders.customer_id", right: "customers.id" }],
      select: [{ from: "orders.revenue", as: "revenue" }],
      output_snapshot: "joined",
      how: "left",
    });
    expect(resolveColumnDrop(revenue, "join_left_key", join)).toMatchObject({
      kind: "patch",
      patch: { keys: [{ left: "orders.revenue", right: "customers.id" }] },
    });
    expect(resolveColumnDrop(revenue, "join_selected_output", join)).toMatchObject({
      kind: "rejected",
    });
    expect(resolveColumnDrop({ ...revenue, ref: "orders.margin" }, "join_selected_output", join)).toMatchObject({
      kind: "patch",
      patch: { select: [{ from: "orders.revenue", as: "revenue" }, { from: "orders.margin", as: "margin" }] },
    });
    expect(resolveColumnRemove("join_selected_output", join, "orders.revenue")).toMatchObject({
      kind: "patch",
      patch: { select: [] },
    });
  });

  it("rejects an empty canvas column drop without creating an operation", () => {
    expect(resolveEmptyCanvasDrop(revenue)).toEqual({
      kind: "rejected",
      reason: "Drop orders.revenue onto a Unit slot to add it.",
    });
  });
});
