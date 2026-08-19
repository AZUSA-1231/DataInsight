// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentThread } from "../../domain/types";

const apiMocks = vi.hoisted(() => ({
  listAgentThreads: vi.fn(),
  createAgentThread: vi.fn(),
  getAgentThread: vi.fn(),
  sendCopilotTurn: vi.fn(),
}));

vi.mock("../../api/agentApi", () => apiMocks);

import { AgentPanel } from "./AgentPanel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function deferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
} {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((promiseResolve) => {
    resolve = promiseResolve;
  });
  return { promise, resolve };
}

const summaryA = {
  threadId: "thread-a",
  title: "First chat",
  createdAt: "2026-08-16T10:00:00Z",
  updatedAt: "2026-08-16T10:01:00Z",
  messageCount: 2,
  preview: "A preview",
};

const summaryB = {
  threadId: "thread-b",
  title: "Second chat",
  createdAt: "2026-08-16T10:02:00Z",
  updatedAt: "2026-08-16T10:02:00Z",
  messageCount: 0,
  preview: null,
};

function detailFor(
  summary: typeof summaryA | typeof summaryB,
  content: string,
): AgentThread {
  return {
    ...summary,
    messageCount: 1,
    preview: content,
    messages: [{ role: "assistant", content, createdAt: summary.updatedAt }],
  };
}

describe("AgentPanel lifecycle", () => {
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
    vi.clearAllMocks();
  });

  it("drops a late detail response after a fast Thread switch and Project reload", async () => {
    const detailA = deferred<AgentThread>();
    const detailB = deferred<AgentThread>();
    const detailProjectB = deferred<AgentThread>();
    apiMocks.listAgentThreads.mockImplementation((projectId: string) =>
      Promise.resolve(projectId === "project-b" ? [summaryB] : [summaryA, summaryB]),
    );
    apiMocks.getAgentThread.mockImplementation(
      (projectId: string, threadId: string) => {
        if (projectId === "project-b") {
          return detailProjectB.promise;
        }
        return threadId === "thread-a" ? detailA.promise : detailB.promise;
      },
    );

    const container = document.createElement("div");
    document.body.appendChild(container);
    await act(async () => {
      root = createRoot(container);
      root.render(<AgentPanel projectId="project-a" />);
      await Promise.resolve();
      await Promise.resolve();
    });

    const secondThread = Array.from(container.querySelectorAll("button")).find((button) =>
      button.textContent?.includes("Second chat"),
    );
    expect(secondThread).toBeDefined();

    await act(async () => {
      secondThread?.click();
      await Promise.resolve();
    });

    await act(async () => {
      detailA.resolve(detailFor(summaryA, "A-only history"));
      await Promise.resolve();
    });
    expect(container.textContent).not.toContain("A-only history");

    await act(async () => {
      detailB.resolve(detailFor(summaryB, "B-only history"));
      await Promise.resolve();
    });
    expect(container.textContent).toContain("B-only history");

    await act(async () => {
      root?.render(<AgentPanel projectId="project-b" />);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(container.textContent).not.toContain("B-only history");

    await act(async () => {
      detailProjectB.resolve(detailFor(summaryB, "Project-B history"));
      await Promise.resolve();
    });
    expect(container.textContent).toContain("Project-B history");
  });
});
