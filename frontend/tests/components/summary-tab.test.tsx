import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReactElement } from "react";

import { SummaryTab } from "@/components/summary-tab";
import { ApiError } from "@/lib/api/client";
import { getSummary } from "@/lib/api/storage";
import type {
  Meeting,
  Segment,
  SummarizeResponse,
  Summary,
  Template,
  TemplateSpec,
} from "@/lib/api/types";

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
  id: "brief",
  source: "bundled",
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

const customTemplate: TemplateSpec = {
  name: "Standup",
  version: "1.0.0",
  system_prompt: "Summarize standups.",
  focus_instructions: null,
  few_shot_examples: [],
  id: "t1",
  source: "custom",
};

const customTemplateStorageResponse: Template = {
  id: "t1",
  name: "Standup",
  version: "1.0.0",
  system_prompt: "Summarize standups.",
  focus_instructions: null,
  few_shot_examples: [],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

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
    expect(await screen.findByText("brief")).toBeInTheDocument();
    expect(screen.getByText("Built-in")).toBeInTheDocument();
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

  it("creates a new custom template", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/templates") && init?.method === "POST") {
        return json(201, customTemplateStorageResponse);
      }
      if (url.endsWith("/templates")) return json(200, [template]);
      if (url.endsWith("/segments")) return json(200, segments);
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

    await user.click(await screen.findByRole("button", { name: "New" }));
    await user.type(screen.getByLabelText("Name"), "Standup");
    await user.type(screen.getByLabelText("System prompt"), "Summarize standups.");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) => String(u).endsWith("/templates") && i?.method === "POST",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call![1]!.body))).toEqual({
        name: "Standup",
        system_prompt: "Summarize standups.",
        focus_instructions: null,
      });
    });
  });

  it("edits and deletes an existing custom template", async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/templates/t1") && init?.method === "PATCH") {
        return json(200, { ...customTemplateStorageResponse, name: "Weekly standup" });
      }
      if (url.endsWith("/templates/t1") && init?.method === "DELETE") {
        return json(204, null);
      }
      if (url.endsWith("/templates")) return json(200, [customTemplate]);
      if (url.endsWith("/segments")) return json(200, segments);
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

    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const nameInput = screen.getByLabelText("Name");
    await user.clear(nameInput);
    await user.type(nameInput, "Weekly standup");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) => String(u).endsWith("/templates/t1") && i?.method === "PATCH",
      );
      expect(call).toBeDefined();
      expect(JSON.parse(String(call![1]!.body))).toEqual({
        name: "Weekly standup",
        system_prompt: "Summarize standups.",
        focus_instructions: null,
      });
    });

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    await user.click(await screen.findByRole("button", { name: "Delete" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        ([u, i]) => String(u).endsWith("/templates/t1") && i?.method === "DELETE",
      );
      expect(call).toBeDefined();
    });
  });
});
