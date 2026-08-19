// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  chartUrl: vi.fn((projectId: string, path: string) => `/chart/${projectId}/${path}`),
  getExecutionResults: vi.fn(),
  getExecutionStatus: vi.fn(),
  isTerminalExecutionStatus: vi.fn((status: string) => status !== "running"),
  rerunUnit: vi.fn(),
  startExecution: vi.fn(),
}));

const reportMocks = vi.hoisted(() => ({
  generateReport: vi.fn(),
  getReport: vi.fn(),
}));

vi.mock("../../api/executionApi", () => apiMocks);
vi.mock("../../api/reportApi", () => reportMocks);

import { OutputDock } from "./OutputDock";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const results = {
  status: "complete",
  runId: "run-1",
  staleUnitIds: [],
  units: [
    {
      unitId: 1,
      status: "success",
      stdout: "",
      stderr: "",
      charts: ["analysis/unit_1/chart.png"],
      insights: ["East is strongest"],
      error: null,
      stale: false,
      runId: "run-1-u1",
      inputCheckpointIds: ["cp-orders"],
      outputCheckpointId: "cp-revenue",
      rowCountBefore: 10,
      rowCountAfter: 10,
      rowCountDelta: 0,
      inputRowCounts: [10],
      statistics: {},
      warnings: [{ code: "JOIN_UNMATCHED_KEYS", message: "2 keys did not match" }],
    },
  ],
};

describe("Output Dock", () => {
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  function renderDock(
    onWorkspaceChanged = vi.fn(),
    nextResults = results,
  ): HTMLDivElement {
    apiMocks.getExecutionStatus.mockResolvedValue({ status: "completed", progress: null, error: null });
    apiMocks.getExecutionResults.mockResolvedValue(nextResults);
    reportMocks.getReport.mockResolvedValue({ report: "# Retained report", error: null });
    const container = document.createElement("div");
    document.body.appendChild(container);
    act(() => {
      root = createRoot(container);
      root.render(<OutputDock onWorkspaceChanged={onWorkspaceChanged} projectId="project-1" />);
    });
    return container;
  }

  it("shows structured warnings and links a result to its canvas unit", async () => {
    const container = renderDock();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(container.textContent).toContain("Unit 1");
    expect(container.textContent).toContain("cp-revenue");
    const unitButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Unit 1"),
    );
    expect(unitButton).toBeDefined();
    await act(async () => {
      unitButton?.click();
    });
    expect(container.textContent).toContain("JOIN_UNMATCHED_KEYS");
    expect(container.querySelector("img")?.getAttribute("src")).toContain("analysis/unit_1/chart.png");
  });

  it("loads Report on demand and never requests the compatibility Dashboard", async () => {
    const container = renderDock();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const dashboardButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent === "Dashboard",
    );
    expect(dashboardButton).toBeDefined();
    await act(async () => {
      dashboardButton?.click();
    });
    expect(container.textContent).toContain("Dashboard is deferred");
    expect(reportMocks.getReport).not.toHaveBeenCalled();
  });

  it("marks stale results and aborts the active request on unmount", async () => {
    const staleResults = {
      ...results,
      staleUnitIds: [1],
      units: [{ ...results.units[0], stale: true }],
    };
    let statusSignal: AbortSignal | undefined;
    apiMocks.getExecutionStatus.mockImplementation((_projectId: string, signal: AbortSignal) => {
      statusSignal = signal;
      return Promise.resolve({ status: "completed", progress: null, error: null });
    });
    apiMocks.getExecutionResults.mockResolvedValue(staleResults);
    const container = document.createElement("div");
    document.body.appendChild(container);
    act(() => {
      root = createRoot(container);
      root.render(<OutputDock onWorkspaceChanged={vi.fn()} projectId="project-1" />);
    });
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(statusSignal).toBeDefined();
    expect(container.textContent).toContain("Stale outputs");
    expect(container.textContent).toContain("stale");
    act(() => root?.unmount());
    expect(statusSignal?.aborted).toBe(true);
    root = null;
  });

  it("renders a retained report after opening the Report tab", async () => {
    const container = renderDock();
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
    const reportButton = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent === "Report",
    );
    await act(async () => {
      reportButton?.click();
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(reportMocks.getReport).toHaveBeenCalledWith("project-1", expect.any(AbortSignal));
    expect(container.textContent).toContain("# Retained report");
  });
});
