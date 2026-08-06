import {
  cleanup,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import type { Meeting } from "@/lib/api/types";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

function makeMeetings(count: number): Meeting[] {
  return Array.from({ length: count }, (_, index) => ({
    id: `m${index + 1}`,
    title: `Meeting ${index + 1}`,
    status: "completed",
    language: "en",
    engine: "whisper",
    model_name: "small",
    started_at: "2026-08-01T10:00:00Z",
    ended_at: "2026-08-01T11:00:00Z",
    segments_count: 1,
    recording_path: null,
    diarization_status: "completed",
    has_summary: false,
  }));
}

function stubFetch(meetings: Meeting[]) {
  const fetchMock = vi.fn(
    (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      if (init?.method === "DELETE") {
        return Promise.resolve(new Response(null, { status: 204 }));
      }
      return Promise.resolve(
        new Response(JSON.stringify(meetings), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function listUrls(fetchMock: ReturnType<typeof stubFetch>) {
  return fetchMock.mock.calls
    .filter(
      ([url, init]) => String(url).includes("/meetings?") && !init?.method,
    )
    .map(([url]) => String(url));
}

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <HomePage />
    </QueryClientProvider>,
  );
}

beforeEach(() => pushMock.mockClear());

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Meetings dashboard", () => {
  it("disables Previous on the first page", async () => {
    stubFetch(makeMeetings(20));
    renderPage();

    await screen.findByText("Meeting 1");

    expect(screen.getByRole("button", { name: "Previous" })).toBeDisabled();
  });

  it("steps to the next page and fetches offset 20", async () => {
    const fetchMock = stubFetch(makeMeetings(20));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Meeting 1");

    await user.click(screen.getByRole("button", { name: "Next" }));

    await waitFor(() => {
      expect(listUrls(fetchMock)).toContain(
        "http://127.0.0.1:8003/meetings?limit=20&offset=20",
      );
    });
    expect(screen.getByRole("button", { name: "Previous" })).toBeEnabled();
  });

  it("filters the fetched page by title", async () => {
    const fetchMock = stubFetch(makeMeetings(2));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Meeting 1");

    await user.type(
      screen.getByPlaceholderText("Search meetings"),
      "Meeting 2",
    );

    expect(screen.getByText("Meeting 2")).toBeInTheDocument();
    expect(screen.queryByText("Meeting 1")).not.toBeInTheDocument();
    expect(listUrls(fetchMock)).toHaveLength(1);
  });

  it("confirming delete calls DELETE and refetches the list", async () => {
    const fetchMock = stubFetch(makeMeetings(1));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Meeting 1");

    const row = screen.getByRole("row", { name: /Meeting 1/ });
    await user.click(within(row).getByRole("button", { name: "Delete" }));

    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => {
      const deleteCall = fetchMock.mock.calls.find(
        ([, init]) => init?.method === "DELETE",
      );
      expect(deleteCall).toBeDefined();
      expect(String(deleteCall![0])).toBe("http://127.0.0.1:8003/meetings/m1");
    });
    await waitFor(() => expect(listUrls(fetchMock)).toHaveLength(2));
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it("opens the meeting detail route", async () => {
    stubFetch(makeMeetings(1));
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Meeting 1");

    const row = screen.getByRole("row", { name: /Meeting 1/ });
    await user.click(within(row).getByRole("button", { name: "Open" }));

    expect(pushMock).toHaveBeenCalledWith("/meetings?id=m1");
  });

  it("shows an unreachable banner when the storage service is offline", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    renderPage();

    expect(
      await screen.findByText("Failed to load meetings"),
    ).toBeInTheDocument();
    expect(screen.getByText("Storage service unreachable")).toBeInTheDocument();
  });

  it("refetches from the error banner retry button", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValue(new TypeError("Failed to fetch"));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    await screen.findByText("Storage service unreachable");

    fetchMock.mockResolvedValue(
      new Response(JSON.stringify(makeMeetings(1)), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );

    await user.click(screen.getByRole("button", { name: "Retry" }));

    expect(await screen.findByText("Meeting 1")).toBeInTheDocument();
  });
});
