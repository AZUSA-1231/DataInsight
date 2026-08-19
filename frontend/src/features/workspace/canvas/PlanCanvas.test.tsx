// @vitest-environment jsdom

import { act } from "react";
import type { ReactNode } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

const apiMocks = vi.hoisted(() => ({
  createWorkspaceUnit: vi.fn(),
  deleteWorkspaceUnit: vi.fn(),
  getWorkspace: vi.fn(),
  updateWorkspaceUnit: vi.fn(),
}));

const layoutMocks = vi.hoisted(() => ({
  getWorkspaceLayout: vi.fn(),
  putWorkspaceLayout: vi.fn(),
}));

const flowMocks = vi.hoisted(() => ({
  props: null as Record<string, unknown> | null,
}));

vi.mock("../../../api/client", () => apiMocks);
vi.mock("../layoutApi", () => layoutMocks);
vi.mock("@xyflow/react", () => ({
  Background: () => null,
  BackgroundVariant: { Lines: "lines" },
  ConnectionLineType: { SmoothStep: "smoothstep" },
  Handle: () => null,
  MiniMap: () => null,
  NodeToolbar: () => null,
  Position: { Bottom: "bottom", Right: "right", Top: "top" },
  ReactFlow: (props: Record<string, unknown>) => {
    flowMocks.props = props;
    return null;
  },
  ReactFlowProvider: ({ children }: { children: ReactNode }) => children,
  useReactFlow: () => ({
    fitView: vi.fn(),
    screenToFlowPosition: vi.fn(),
    zoomIn: vi.fn(),
    zoomOut: vi.fn(),
  }),
}));

import type { PlanCanvasNode } from "./planMapper";
import { PlanCanvas } from "./PlanCanvas";
import type { WorkspaceLayout } from "../../../domain/plan";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const plan = {
  units: [{
    unit_id: 1,
    operation: "terminal" as const,
    purpose: "Inspect orders",
    depends_on: [],
    input_snapshot: "orders",
    input_columns: ["orders.revenue"],
  }],
  alignment_notes: "",
};

const layout: WorkspaceLayout = {
  version: 1,
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [{ unit_id: 1, x: 40, y: 60, collapsed: false }],
};

function callback<T extends (...args: never[]) => void>(name: string): T {
  const value = flowMocks.props?.[name];
  if (typeof value !== "function") {
    throw new Error(`React Flow callback ${name} was not registered`);
  }
  return value as T;
}

describe("Plan Canvas layout writes", () => {
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
    flowMocks.props = null;
    vi.clearAllMocks();
  });

  function renderCanvas(): HTMLDivElement {
    apiMocks.getWorkspace.mockResolvedValue({ plan });
    layoutMocks.getWorkspaceLayout.mockResolvedValue(layout);
    layoutMocks.putWorkspaceLayout.mockResolvedValue(layout);
    const container = document.createElement("div");
    document.body.appendChild(container);
    act(() => {
      root = createRoot(container);
      root.render(
        <PlanCanvas
          catalog={null}
          onRequestedOperationHandled={vi.fn()}
          projectId="project-1"
          requestedOperation={null}
        />,
      );
    });
    return container;
  }

  async function finishLoad(): Promise<void> {
    await act(async () => {
      await Promise.resolve();
      await Promise.resolve();
    });
  }

  it("keeps movement-only changes local and writes once at drag stop", async () => {
    renderCanvas();
    await finishLoad();

    await act(async () => {
      callback<(changes: unknown[]) => void>("onNodesChange")([
        { id: "unit:1", type: "position", dragging: true, position: { x: 100, y: 120 } },
      ]);
    });
    expect(layoutMocks.putWorkspaceLayout).not.toHaveBeenCalled();

    await act(async () => {
      callback<(_event: MouseEvent, node: PlanCanvasNode, nodes: PlanCanvasNode[]) => void>("onNodeDragStop")(
        new MouseEvent("mouseup"),
        { id: "unit:1", position: { x: 140, y: 180 } } as PlanCanvasNode,
        [],
      );
    });

    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledTimes(1);
    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledWith(
      "project-1",
      expect.objectContaining({
        nodes: [{ unit_id: 1, x: 140, y: 180, collapsed: false }],
      }),
      expect.any(AbortSignal),
    );
  });

  it("keeps only the newest layout while an older save is in flight", async () => {
    renderCanvas();
    await finishLoad();
    let resolveFirst: (value: WorkspaceLayout) => void = () => undefined;
    layoutMocks.putWorkspaceLayout.mockImplementationOnce(
      () => new Promise<WorkspaceLayout>((resolve) => { resolveFirst = resolve; }),
    );
    layoutMocks.putWorkspaceLayout.mockResolvedValue(layout);

    const dragStop = callback<(_event: MouseEvent, node: PlanCanvasNode, nodes: PlanCanvasNode[]) => void>("onNodeDragStop");
    await act(async () => {
      dragStop(new MouseEvent("mouseup"), { id: "unit:1", position: { x: 100, y: 120 } } as PlanCanvasNode, []);
      dragStop(new MouseEvent("mouseup"), { id: "unit:1", position: { x: 300, y: 320 } } as PlanCanvasNode, []);
    });

    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledTimes(1);
    resolveFirst(layout);
    await finishLoad();
    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledTimes(2);
    expect(layoutMocks.putWorkspaceLayout.mock.calls[1][1]).toMatchObject({
      nodes: [{ unit_id: 1, x: 300, y: 320, collapsed: false }],
    });
  });

  it("does not restore an active second drag when the first save resolves", async () => {
    renderCanvas();
    await finishLoad();
    let resolveFirst: (value: WorkspaceLayout) => void = () => undefined;
    layoutMocks.putWorkspaceLayout.mockImplementationOnce(
      () => new Promise<WorkspaceLayout>((resolve) => { resolveFirst = resolve; }),
    );
    layoutMocks.putWorkspaceLayout.mockResolvedValue(layout);

    const dragStop = callback<(_event: MouseEvent, node: PlanCanvasNode, nodes: PlanCanvasNode[]) => void>("onNodeDragStop");
    await act(async () => {
      dragStop(new MouseEvent("mouseup"), { id: "unit:1", position: { x: 100, y: 120 } } as PlanCanvasNode, []);
      callback<(changes: unknown[]) => void>("onNodesChange")([
        { id: "unit:1", type: "position", dragging: true, position: { x: 220, y: 240 } },
      ]);
    });

    resolveFirst(layout);
    await finishLoad();
    const nodes = flowMocks.props?.nodes as PlanCanvasNode[];
    expect(nodes[0].position).toEqual({ x: 220, y: 240 });
    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledTimes(1);

    await act(async () => {
      dragStop(new MouseEvent("mouseup"), { id: "unit:1", position: { x: 260, y: 280 } } as PlanCanvasNode, []);
    });
    await finishLoad();
    expect(layoutMocks.putWorkspaceLayout).toHaveBeenCalledTimes(2);
    expect(layoutMocks.putWorkspaceLayout.mock.calls[1][1]).toMatchObject({
      nodes: [{ unit_id: 1, x: 260, y: 280, collapsed: false }],
    });
  });

  it("keeps a newer local position when an older save is rejected", async () => {
    renderCanvas();
    await finishLoad();
    let rejectFirst: (reason?: unknown) => void = () => undefined;
    layoutMocks.putWorkspaceLayout.mockImplementationOnce(
      () => new Promise<WorkspaceLayout>((_resolve, reject) => { rejectFirst = reject; }),
    );
    layoutMocks.putWorkspaceLayout.mockResolvedValue(layout);

    const dragStop = callback<(_event: MouseEvent, node: PlanCanvasNode, nodes: PlanCanvasNode[]) => void>("onNodeDragStop");
    await act(async () => {
      dragStop(new MouseEvent("mouseup"), { id: "unit:1", position: { x: 100, y: 120 } } as PlanCanvasNode, []);
      callback<(changes: unknown[]) => void>("onNodesChange")([
        { id: "unit:1", type: "position", dragging: true, position: { x: 220, y: 240 } },
      ]);
    });

    rejectFirst(new Error("delayed save failed"));
    await finishLoad();
    const nodes = flowMocks.props?.nodes as PlanCanvasNode[];
    expect(nodes[0].position).toEqual({ x: 220, y: 240 });
    expect(document.body.textContent).not.toContain("delayed save failed");
    expect(flowMocks.props?.onMoveEnd).toBeUndefined();
  });

  it("rejects an invalid drag coordinate before it reaches the API", async () => {
    const container = renderCanvas();
    await finishLoad();

    await act(async () => {
      callback<(_event: MouseEvent, node: PlanCanvasNode, nodes: PlanCanvasNode[]) => void>("onNodeDragStop")(
        new MouseEvent("mouseup"),
        { id: "unit:1", position: { x: Number.NaN, y: 20 } } as PlanCanvasNode,
        [],
      );
    });

    expect(layoutMocks.putWorkspaceLayout).not.toHaveBeenCalled();
    expect(container.textContent).toContain("positions must be finite and bounded");
  });
});
