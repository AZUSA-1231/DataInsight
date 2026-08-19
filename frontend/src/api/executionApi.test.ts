import { afterEach, describe, expect, it, vi } from "vitest";

import {
  chartUrl,
  getExecutionResults,
  isTerminalExecutionStatus,
} from "./executionApi";

describe("Execution API boundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("decodes unit results without dropping warnings or checkpoint metadata", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            status: "complete",
            run_id: "run-1",
            stale_unit_ids: [2],
            units: [
              {
                unit_id: 1,
                status: "success",
                stdout: "ok",
                stderr: "",
                charts: ["analysis/unit_1/chart.png"],
                insights: ["Revenue is higher in East"],
                stale: false,
                run_id: "run-1-u1",
                input_checkpoint_ids: ["cp-orders"],
                output_checkpoint_id: "cp-revenue",
                row_count_before: 10,
                row_count_after: 10,
                row_count_delta: 0,
                input_row_counts: [10],
                statistics: { row_count: 10 },
                warnings: [{ code: "JOIN_UNMATCHED_KEYS", unmatched: 2 }],
              },
            ],
          }),
          { status: 200 },
        ),
      ),
    );

    await expect(getExecutionResults("project-1")).resolves.toMatchObject({
      status: "complete",
      runId: "run-1",
      staleUnitIds: [2],
      units: [
        expect.objectContaining({
          unitId: 1,
          outputCheckpointId: "cp-revenue",
          warnings: [{ code: "JOIN_UNMATCHED_KEYS", unmatched: 2 }],
        }),
      ],
    });
  });

  it("constructs an encoded session chart URL and rejects traversal references", () => {
    expect(chartUrl("project-1", "analysis/unit 1/chart.png")).toBe(
      "/api/sessions/project-1/execution/charts/analysis/unit%201/chart.png",
    );
    expect(() => chartUrl("project-1", "../outside.png")).toThrow(
      "session-relative path",
    );
    expect(isTerminalExecutionStatus("completed")).toBe(true);
    expect(isTerminalExecutionStatus("running")).toBe(false);
  });
});
