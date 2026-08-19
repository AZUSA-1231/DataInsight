// @vitest-environment jsdom

import { act } from "react";
import { createRoot, Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Composer } from "./Composer";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("Agent Composer", () => {
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("submits trimmed text on Enter and keeps Shift+Enter multiline", () => {
    const onSubmit = vi.fn();
    const container = document.createElement("div");
    document.body.appendChild(container);
    act(() => {
      root = createRoot(container);
      root.render(
        <Composer
          resetKey="project-a:thread-a"
          disabled={false}
          busy={false}
          error={null}
          canRetry={false}
          onSubmit={onSubmit}
          onCancel={vi.fn()}
          onRetry={vi.fn()}
        />,
      );
    });

    const textarea = container.querySelector("textarea");
    expect(textarea).not.toBeNull();
    const setNativeValue = (value: string): void => {
      if (!textarea) {
        return;
      }
      const setter = Object.getOwnPropertyDescriptor(
        HTMLTextAreaElement.prototype,
        "value",
      )?.set;
      setter?.call(textarea, value);
      textarea.dispatchEvent(new Event("input", { bubbles: true }));
    };
    act(() => {
      if (textarea) {
        setNativeValue("  inspect this  ");
        textarea.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
      }
    });
    expect(onSubmit).toHaveBeenCalledWith("inspect this");

    onSubmit.mockClear();
    act(() => {
      if (textarea) {
        setNativeValue("line one");
        textarea.dispatchEvent(
          new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }),
        );
      }
    });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
