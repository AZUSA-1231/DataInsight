import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createAgentThread,
  getAgentThread,
  listAgentThreads,
  sendCopilotTurn,
} from "./agentApi";

const projectId = "0123456789abcdef0123456789abcdef";

const summary = {
  thread_id: "thread-a",
  title: "Analysis questions",
  created_at: "2026-08-16T10:00:00Z",
  updated_at: "2026-08-16T10:01:00Z",
  message_count: 2,
  preview: "The latest answer",
};

const detail = {
  ...summary,
  messages: [
    { role: "user", content: "Inspect sales", created_at: "2026-08-16T10:00:00Z" },
    { role: "assistant", content: "I found three columns", created_at: "2026-08-16T10:01:00Z" },
  ],
};

describe("Agent API boundary helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("decodes Project-local Thread summaries and details", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ threads: [summary] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify(detail), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listAgentThreads(projectId)).resolves.toEqual([
      {
        threadId: "thread-a",
        title: "Analysis questions",
        createdAt: "2026-08-16T10:00:00Z",
        updatedAt: "2026-08-16T10:01:00Z",
        messageCount: 2,
        preview: "The latest answer",
      },
    ]);
    await expect(getAgentThread(projectId, "thread-a")).resolves.toMatchObject({
      threadId: "thread-a",
      messages: [
        { role: "user", content: "Inspect sales" },
        { role: "assistant", content: "I found three columns" },
      ],
    });

    expect(fetchMock.mock.calls[0][0]).toBe(`/api/sessions/${projectId}/agent-chats`);
    expect(fetchMock.mock.calls[1][0]).toBe(
      `/api/sessions/${projectId}/agent-chats/thread-a`,
    );
  });

  it("sends only the selected Thread ID and user message", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          status: "complete",
          message: "Done",
          skill: "inspect",
          tool_results: [],
          tool_rounds: 0,
          model_calls: 1,
          error: null,
        }),
        { status: 200 },
      ),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(sendCopilotTurn(projectId, "thread-a", "Inspect sales")).resolves.toMatchObject({
      status: "complete",
      message: "Done",
      skill: "inspect",
    });
    const request = fetchMock.mock.calls[0][1] as RequestInit;
    expect(request.method).toBe("POST");
    expect(JSON.parse(String(request.body))).toEqual({
      thread_id: "thread-a",
      message: "Inspect sales",
    });
  });

  it("decodes create responses and preserves structured HTTP errors", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify(detail), { status: 200 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: { code: "THREAD_NOT_FOUND", message: "missing" } }), {
          status: 404,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(createAgentThread(projectId)).resolves.toMatchObject({
      threadId: "thread-a",
      messages: expect.any(Array),
    });
    await expect(getAgentThread(projectId, "missing")).rejects.toMatchObject({
      status: 404,
      message: "missing",
    });
  });
});
