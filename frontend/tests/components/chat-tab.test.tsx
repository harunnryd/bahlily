import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatTab } from "@/components/chat-tab";
import type { Meeting, Segment } from "@/lib/api/types";

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
  has_summary: false,
};

const segmentsFixture: Segment[] = [
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

function json(status: number, body: unknown): Promise<Response> {
  return Promise.resolve(
    new Response(body === null ? null : JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    }),
  );
}

function stubFetch(
  impl: (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>,
) {
  const fetchMock = vi.fn(impl);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ChatTab", () => {
  it("shows the ingest gate when not ingested", () => {
    render(<ChatTab meeting={meeting} ingested={false} />);
    expect(
      screen.getByRole("button", { name: /ingest transcript/i }),
    ).toBeInTheDocument();
  });

  it("renders the chat input when ingested", () => {
    render(<ChatTab meeting={meeting} ingested />);
    expect(
      screen.getByRole("textbox", { name: /question/i }),
    ).toBeInTheDocument();
  });

  it("ingests segments and flips to the chat input", async () => {
    const fetchMock = stubFetch((input, init) => {
      const url = String(input);
      if (url.endsWith("/meetings/m1/segments") && !init?.method) {
        return json(200, segmentsFixture);
      }
      if (url.endsWith("/meetings/m1/ingest") && init?.method === "POST") {
        return json(200, { meeting_id: "m1", segments_indexed: 1 });
      }
      return json(404, null);
    });
    const user = userEvent.setup();
    render(<ChatTab meeting={meeting} ingested={false} />);

    await user.click(
      screen.getByRole("button", { name: /ingest transcript/i }),
    );

    await waitFor(() => {
      const segmentCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith("/meetings/m1/segments") && !init?.method,
      );
      expect(segmentCall).toBeDefined();
    });
    await waitFor(() => {
      const ingestCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith("/meetings/m1/ingest") &&
          init?.method === "POST",
      );
      expect(ingestCall).toBeDefined();
      expect(JSON.parse(String(ingestCall![1]!.body))).toMatchObject({
        segments: [
          expect.objectContaining({
            segment_id: 1,
            text: "hello",
          }),
        ],
      });
    });
    expect(
      await screen.findByRole("textbox", { name: /question/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /ingest transcript/i }),
    ).not.toBeInTheDocument();
  });

  it("submits a question, appends user and assistant turns, shows citations", async () => {
    const fetchMock = stubFetch((input, init) => {
      const url = String(input);
      if (url.endsWith("/chat") && init?.method === "POST") {
        return json(200, {
          answer: "Discussed launch",
          citations: [
            {
              meeting_id: "m1",
              segment_id: 1,
              text: "we ship next week",
              start_time: 0,
              end_time: 1,
            },
          ],
        });
      }
      return json(404, null);
    });
    const user = userEvent.setup();
    render(<ChatTab meeting={meeting} ingested />);

    await user.type(
      screen.getByRole("textbox", { name: /question/i }),
      "What did we decide?",
    );
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("What did we decide?")).toBeInTheDocument();
    expect(await screen.findByText("Discussed launch")).toBeInTheDocument();
    expect(await screen.findByText("we ship next week")).toBeInTheDocument();

    await waitFor(() => {
      const chatCall = fetchMock.mock.calls.find(
        ([url, init]) =>
          String(url).endsWith("/chat") && init?.method === "POST",
      );
      expect(chatCall).toBeDefined();
      expect(JSON.parse(String(chatCall![1]!.body))).toMatchObject({
        question: "What did we decide?",
        meeting_id: "m1",
        provider: "ollama",
        model: "llama3",
      });
    });
  });

  it("shows an error and keeps the user turn when askChat fails", async () => {
    stubFetch(() => json(500, { message: "boom" }));
    const user = userEvent.setup();
    render(<ChatTab meeting={meeting} ingested />);

    await user.type(
      screen.getByRole("textbox", { name: /question/i }),
      "What happened?",
    );
    await user.click(screen.getByRole("button", { name: /send/i }));

    expect(await screen.findByText("What happened?")).toBeInTheDocument();
    expect(await screen.findByText("boom")).toBeInTheDocument();
  });

  it("disables input and submit while a request is in flight", async () => {
    stubFetch((input, init) => {
      if (String(input).endsWith("/chat") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          setTimeout(
            () => resolve(json(200, { answer: "Hi", citations: [] })),
            80,
          );
        });
      }
      return json(404, null);
    });
    const user = userEvent.setup();
    render(<ChatTab meeting={meeting} ingested />);

    await user.type(
      screen.getByRole("textbox", { name: /question/i }),
      "Hello",
    );
    await user.click(screen.getByRole("button", { name: /send/i }));

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: /question/i })).toBeDisabled(),
    );
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /send/i })).toBeDisabled(),
    );

    await waitFor(() => expect(screen.getByText("Hi")).toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: /question/i })).toBeEnabled();
  });
});
