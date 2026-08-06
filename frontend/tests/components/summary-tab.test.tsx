import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { SummaryTab } from "@/components/summary-tab";
import { ApiError } from "@/lib/api/client";
import { getSummary } from "@/lib/api/storage";
import type { Meeting, Segment, SummarizeResponse, Summary, TemplateSpec } from "@/lib/api/types";

const meeting: Meeting = {
  id: "m1",
  title: "T",
  status: "completed",
  language: "en",
  engine: "whisper",
  model_name: "small",
  started_at: "2026-08-01T10:00:00Z",
  ended_at: null,
  segments_count: 0,
  recording_path: null,
  diarization_status: "completed",
  has_summary: true,
};

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

const template: TemplateSpec = {
  name: "brief",
  version: "1",
  system_prompt: "Summarize concisely.",
  focus_instructions: null,
  few_shot_examples: [],
};

const segments: Segment[] = [
  {
    segment_id: 1,
    text: "hello",
    confidence: 0.9,
    engine: "whisper",
    model_name: "small",
    audio_start_time: 0,
    audio_end_time: 1,
    language: "en",
    is_partial: false,
    trace_id: "t1",
    speaker_cluster_label: "SPEAKER_01",
    speaker_profile_id: null,
  },
];

const summarizeResponse: SummarizeResponse = {
  summary: {
    title: "Sprint planning",
    overview: "Reviewed sprint goals.",
    key_points: ["Shipped the API"],
    action_items: [],
    quotes: [],
  },
  attempts: 1,
  provider: "ollama",
  model: "llama3",
};

function json(status: number, body: unknown) {
  return Promise.resolve(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

function stubTemplates() {
  const fetchMock = vi.fn(() => json(200, [template]));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderTab(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

function SummaryHarness({ id }: { id: string }) {
  const { data } = useQuery({
    queryKey: ["summary", id],
    queryFn: () =>
      getSummary(id).catch((e) =>
        e instanceof ApiError && e.status === 404 ? null : Promise.reject(e),
      ),
  });
  return (
    <SummaryTab
      meeting={{ ...meeting, id }}
      segments={segments}
      segmentsPending={false}
      summary={data ?? null}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("SummaryTab", () => {
  it("renders an existing summary", () => {
    renderTab(
      <SummaryTab
        meeting={meeting}
        segments={segments}
        segmentsPending={false}
        summary={summary}
      />,
    );
    expect(screen.getByText("Sprint planning")).toBeInTheDocument();
    expect(screen.getByText("Shipped the API")).toBeInTheDocument();
  });

  it("shows the generate flow when no summary exists", async () => {
    stubTemplates();
    renderTab(
      <SummaryTab
        meeting={{ ...meeting, has_summary: false }}
        segments={segments}
        segmentsPending={false}
        summary={null}
      />,
    );
    expect(screen.getByRole("button", { name: /generate/i })).toBeInTheDocument();
    expect(await screen.findByText("brief 1")).toBeInTheDocument();
  });

  it("disables generation when no transcript is available", async () => {
    stubTemplates();
    renderTab(
      <SummaryTab
        meeting={{ ...meeting, has_summary: false }}
        segments={[]}
        segmentsPending={false}
        summary={null}
      />,
    );

    expect(await screen.findByText("No transcript available to summarize yet")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /generate/i })).toBeDisabled();
  });

  it("generates, persists, and flips to the rendered summary", async () => {
    let stored: Summary | null = null;
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (url.endsWith("/templates")) return json(200, [template]);
      if (url.endsWith("/segments")) return json(200, segments);
      if (url.endsWith("/summarize")) return json(200, summarizeResponse);
      if (url.endsWith("/meetings/m1/summary") && method === "POST") {
        stored = summary;
        return json(201, summary);
      }
      if (url.endsWith("/meetings/m1/summary")) {
        return stored === null ? json(404, null) : json(200, stored);
      }
      return json(404, null);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderTab(<SummaryHarness id="m1" />);

    await screen.findByRole("button", { name: /generate/i });
    await waitFor(() => expect(screen.getByRole("button", { name: /generate/i })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /generate/i }));

    await waitFor(() => {
      const summarizeCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith("/summarize") && init?.method === "POST",
      );
      expect(summarizeCall).toBeDefined();
      expect(JSON.parse(String(summarizeCall![1]!.body))).toMatchObject({
        template: { name: "brief" },
        provider: "ollama",
        model: "llama3",
      });
    });

    await waitFor(() => {
      const saveCall = fetchMock.mock.calls.find(
        ([url, init]) => String(url).endsWith("/meetings/m1/summary") && init?.method === "POST",
      );
      expect(saveCall).toBeDefined();
      expect(JSON.parse(String(saveCall![1]!.body))).toEqual({
        title: "Sprint planning",
        overview: "Reviewed sprint goals.",
        key_points: ["Shipped the API"],
        action_items: [],
        quotes: [],
        provider: "ollama",
        model: "llama3",
      });
    });

    expect(await screen.findByText("Sprint planning")).toBeInTheDocument();
    expect(screen.getByText("Shipped the API")).toBeInTheDocument();
  });

  it("shows an error when generation fails", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/templates")) return json(200, [template]);
      if (url.endsWith("/segments")) return json(200, segments);
      if (url.endsWith("/summarize")) return json(500, { message: "boom" });
      return json(404, null);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderTab(
      <SummaryTab
        meeting={{ ...meeting, has_summary: false }}
        segments={segments}
        segmentsPending={false}
        summary={null}
      />,
    );

    await screen.findByRole("button", { name: /generate/i });
    await waitFor(() => expect(screen.getByRole("button", { name: /generate/i })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: /generate/i }));

    expect(await screen.findByText("Failed to generate summary")).toBeInTheDocument();
  });
});
