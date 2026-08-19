import { describe, expect, it } from "vitest";

import { AgentThread } from "../../domain/types";
import { agentReducer, createAgentPanelState } from "./agentStore";

const threadA: AgentThread = {
  threadId: "thread-a",
  title: "First chat",
  createdAt: "2026-08-16T10:00:00Z",
  updatedAt: "2026-08-16T10:01:00Z",
  messageCount: 2,
  preview: "A preview",
  messages: [
    { role: "user", content: "A question", createdAt: "2026-08-16T10:00:00Z" },
    { role: "assistant", content: "A answer", createdAt: "2026-08-16T10:01:00Z" },
  ],
};

const threadB: AgentThread = {
  threadId: "thread-b",
  title: "Second chat",
  createdAt: "2026-08-16T10:02:00Z",
  updatedAt: "2026-08-16T10:02:00Z",
  messageCount: 0,
  preview: null,
  messages: [],
};

describe("Agent panel state", () => {
  it("clears visible history when switching Threads", () => {
    let state = createAgentPanelState("project-a");
    state = agentReducer(state, {
      type: "list-loaded",
      threads: [threadA, threadB],
      selectedThreadId: threadA.threadId,
    });
    state = agentReducer(state, { type: "detail-loaded", thread: threadA });
    state = agentReducer(state, { type: "thread-selected", threadId: threadB.threadId });

    expect(state.selectedThreadId).toBe("thread-b");
    expect(state.details["thread-b"].thread).toBeNull();
    expect(state.details["thread-b"].status).toBe("loading");
  });

  it("keeps a late old-Thread detail out of the selected Thread view", () => {
    let state = createAgentPanelState("project-a");
    state = agentReducer(state, {
      type: "list-loaded",
      threads: [threadA, threadB],
      selectedThreadId: threadA.threadId,
    });
    state = agentReducer(state, { type: "thread-selected", threadId: threadB.threadId });
    state = agentReducer(state, { type: "detail-loaded", thread: threadA });

    expect(state.selectedThreadId).toBe("thread-b");
    expect(state.details["thread-b"].thread).toBeNull();
    expect(state.details["thread-a"].thread?.messages[0].content).toBe("A question");
  });

  it("drops all Project and Thread resources on Project reset", () => {
    let state = createAgentPanelState("project-a");
    state = agentReducer(state, {
      type: "thread-created",
      thread: threadA,
    });
    state = agentReducer(state, { type: "reset", projectId: "project-b" });

    expect(state.projectId).toBe("project-b");
    expect(state.threads).toEqual([]);
    expect(state.selectedThreadId).toBeNull();
    expect(state.details).toEqual({});
  });

  it("offers retry only after an explicit failed send", () => {
    let state = createAgentPanelState("project-a");
    state = agentReducer(state, { type: "send-started", message: "Try this" });
    state = agentReducer(state, {
      type: "send-failed",
      message: "Try this",
      error: "network failure",
    });

    expect(state.sendStatus).toBe("error");
    expect(state.retryMessage).toBe("Try this");
    expect(state.sendError).toBe("network failure");
  });
});
