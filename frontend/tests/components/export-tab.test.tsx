import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ExportTab } from "@/components/export-tab";
import type { Summary } from "@/lib/api/types";

const summary: Summary = {
  id: "s1",
  meeting_id: "m1",
  title: "Sprint planning",
  overview: "Reviewed sprint goals.",
  key_points: ["Shipped the API"],
  action_items: [],
  quotes: [],
  provider: "ollama",
  model: "llama3",
  created_at: "2026-08-01T11:00:00Z",
};

const createObjectURL = vi.fn(() => "blob:fake");
const revokeObjectURL = vi.fn();

function stubUrl() {
  vi.stubGlobal("URL", {
    ...URL,
    createObjectURL,
    revokeObjectURL,
  });
}

function stubAnchorClick() {
  const click = vi.fn();
  Object.defineProperty(HTMLAnchorElement.prototype, "click", {
    configurable: true,
    writable: true,
    value: click,
  });
  return click;
}

function json(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function blobResponse(status: number, body: string): Response {
  return new Response(body, {
    status,
    headers: { "content-type": "application/octet-stream" },
  });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  createObjectURL.mockClear();
  revokeObjectURL.mockClear();
});

describe("ExportTab", () => {
  it("renders three export buttons", () => {
    render(<ExportTab disabled={false} summary={null} />);
    expect(screen.getByRole("button", { name: /markdown/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /docx/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /pdf/i })).toBeInTheDocument();
  });

  it("disables buttons when there is no summary", () => {
    render(<ExportTab disabled summary={null} />);
    expect(screen.getByRole("button", { name: /markdown/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /docx/i })).toBeDisabled();
    expect(screen.getByRole("button", { name: /pdf/i })).toBeDisabled();
  });

  it("fetches the export blob and triggers a download when a button is clicked", async () => {
    stubUrl();
    const click = stubAnchorClick();
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/export") && init?.method === "POST") {
        return Promise.resolve(blobResponse(200, "blob-bytes"));
      }
      return Promise.resolve(json(404, null));
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(<ExportTab disabled={false} summary={summary} />);

    await user.click(screen.getByRole("button", { name: /markdown/i }));

    await waitFor(() => {
      const exportCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).includes("/export") && init?.method === "POST",
      );
      expect(exportCall).toBeDefined();
    });
    await waitFor(() =>
      expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob)),
    );
    await waitFor(() => expect(click).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(revokeObjectURL).toHaveBeenCalledWith("blob:fake"),
    );
  });

  it("uses the matching extension for the filename", async () => {
    stubUrl();
    const click = vi.fn();
    let capturedAnchor: HTMLAnchorElement | null = null;
    const originalCreate = document.createElement.bind(document);
    const createSpy = vi.spyOn(document, "createElement");
    createSpy.mockImplementation(((name: string) => {
      const el = originalCreate(name);
      if (name === "a") {
        capturedAnchor = el as HTMLAnchorElement;
        Object.defineProperty(el, "click", {
          configurable: true,
          writable: true,
          value: click,
        });
      }
      return el;
    }) as typeof document.createElement);
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.resolve(blobResponse(200, "x"))),
    );
    const user = userEvent.setup();
    render(<ExportTab disabled={false} summary={summary} />);

    await user.click(screen.getByRole("button", { name: /pdf/i }));

    await waitFor(() => {
      expect(capturedAnchor).not.toBeNull();
      expect(capturedAnchor!.getAttribute("download")).toMatch(/\.pdf$/);
    });
  });
});
