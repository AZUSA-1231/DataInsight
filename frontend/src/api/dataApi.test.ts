import { afterEach, describe, expect, it, vi } from "vitest";

import { getDataCatalog } from "./dataApi";

const projectId = "0123456789abcdef0123456789abcdef";

describe("Explorer workspace data projection", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("decodes planned nullable facts through one coherent request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          sources: [],
          snapshots: [
            {
              view_id: "plan:unit_2",
              snapshot_id: null,
              name: "east_orders",
              display_name: "east_orders",
              row_count: null,
              column_refs: ["east_orders.revenue"],
              source_id: null,
              created_by_unit_id: 2,
              parent_snapshot_names: ["orders"],
              availability: "planned",
              profile_available: false,
            },
          ],
          columns: [
            {
              ref: "east_orders.revenue",
              name: "revenue",
              snapshot: "east_orders",
              dtype: null,
              null_count: null,
              null_pct: null,
              source_column: null,
              created_by_unit_id: 2,
              availability: "planned",
            },
          ],
          lineage: [],
          compatibility_warning: null,
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getDataCatalog(projectId)).resolves.toMatchObject({
      snapshots: [
        expect.objectContaining({
          viewId: "plan:unit_2",
          snapshotId: null,
          rowCount: null,
          availability: "planned",
        }),
      ],
      columns: [
        expect.objectContaining({
          ref: "east_orders.revenue",
          dtype: null,
          nullCount: null,
          nullPct: null,
          availability: "planned",
        }),
      ],
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `/api/sessions/${projectId}/data/workspace-projection`,
    );
  });
});
