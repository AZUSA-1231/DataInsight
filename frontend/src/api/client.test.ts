import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, projectIdFromPath, projectPath } from "./client";
import { ApiError } from "../domain/types";

const projectId = "0123456789abcdef0123456789abcdef";

describe("Project API boundary helpers", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses and builds the stable Project URL", () => {
    expect(projectPath(projectId)).toBe(`/projects/${projectId}`);
    expect(projectIdFromPath(`/projects/${projectId}`)).toBe(projectId);
    expect(projectIdFromPath(`/projects/${projectId}/`)).toBe(projectId);
    expect(projectIdFromPath("/projects/not-a-project")).toBeNull();
  });

  it("decodes successful JSON through the typed boundary", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ value: "ok" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiFetch("/api/test", {}, (payload) => {
      if (!payload || typeof payload !== "object" || !("value" in payload)) {
        throw new Error("invalid payload");
      }
      return String(payload.value);
    })).resolves.toBe("ok");
  });

  it("normalizes structured HTTP errors without exposing a raw response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: { code: "INCOMPATIBLE_SESSION_SCHEMA", message: "unavailable" } }), {
          status: 409,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const request = apiFetch("/api/test", {}, () => "never");
    await expect(request).rejects.toBeInstanceOf(ApiError);
    await expect(request).rejects.toMatchObject({ status: 409, message: "unavailable" });
  });
});
