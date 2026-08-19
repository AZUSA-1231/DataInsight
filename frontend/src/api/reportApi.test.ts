import { afterEach, describe, expect, it, vi } from "vitest";

import { generateReport, getReport } from "./reportApi";

describe("Report API boundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("reads retained Markdown and sends report generation to the Project route", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ report: "# Retained", error: null }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ report: "# Generated", error: null }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getReport("project-1")).resolves.toEqual({ report: "# Retained", error: null });
    await expect(generateReport("project-1")).resolves.toEqual({ report: "# Generated", error: null });
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/sessions/project-1/report/generate",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
