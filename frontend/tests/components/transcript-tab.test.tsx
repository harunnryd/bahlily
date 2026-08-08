import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TranscriptTab } from "@/components/transcript-tab";
import type { Meeting, Segment, SpeakerProfile } from "@/lib/api/types";

const meeting: Meeting = {
  id: "m1",
  title: "T",
  status: "completed",
  language: "en",
  engine: "whisper",
  model_name: "small",
  started_at: "2026-08-01T10:00:00Z",
  ended_at: null,
  segments_count: 2,
  recording_path: null,
  diarization_status: "completed",
  has_summary: false,
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
  {
    segment_id: 2,
    text: "world",
    confidence: 0.9,
    engine: "whisper",
    model_name: "small",
    audio_start_time: 1,
    audio_end_time: 2,
    language: "en",
    is_partial: false,
    trace_id: "t1",
    speaker_cluster_label: "SPEAKER_01",
    speaker_profile_id: null,
  },
];

const speakerProfile: SpeakerProfile = {
  id: "p1",
  name: "Alice",
  voice_embedding: [],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const otherProfile: SpeakerProfile = {
  id: "p2",
  name: "Bob",
  voice_embedding: [],
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

function stubProfiles(profiles: SpeakerProfile[]) {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = String(input);
    if (init?.method === "POST" && url.endsWith("/merge")) {
      const survivorId = url.split("/speaker-profiles/")[1]?.split("/merge")[0];
      const survivor = profiles.find((p) => p.id === survivorId) ?? speakerProfile;
      return Promise.resolve(
        new Response(JSON.stringify(survivor), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }
    if (init?.method === "POST") {
      const body = JSON.parse(String(init.body)) as { name?: string };
      const matched = profiles.find((p) => p.name === body.name);
      const response = matched ?? { ...speakerProfile, name: body.name ?? speakerProfile.name };
      return Promise.resolve(
        new Response(JSON.stringify(response), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(profiles), {
        status: 200,
        headers: { "content-type": "application/json" },
      }),
    );
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderTab(ui: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("TranscriptTab", () => {
  it("groups segments under their speaker label", () => {
    stubProfiles([]);
    renderTab(<TranscriptTab meeting={meeting} segments={segments} />);
    expect(screen.getAllByText("SPEAKER_01")).toHaveLength(1);
    expect(screen.getByText("hello")).toBeInTheDocument();
    expect(screen.getByText("world")).toBeInTheDocument();
  });

  it("shows empty state when no segments", () => {
    stubProfiles([]);
    renderTab(<TranscriptTab meeting={meeting} segments={[]} />);
    expect(screen.getByText("No transcripts yet")).toBeInTheDocument();
  });

  it("shows a persisted speaker profile name for a linked cluster", async () => {
    stubProfiles([speakerProfile]);
    renderTab(
      <TranscriptTab meeting={meeting} segments={[{ ...segments[0], speaker_profile_id: "p1" }]} />,
    );
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.queryByText("SPEAKER_01")).not.toBeInTheDocument();
  });

  it("relabels a cluster through the storage api and refetches profiles", async () => {
    const fetchMock = stubProfiles([]);
    const user = userEvent.setup();
    renderTab(<TranscriptTab meeting={meeting} segments={segments} />);

    await user.click(screen.getByText("SPEAKER_01"));
    await user.type(screen.getByPlaceholderText("Speaker name"), "Alice");
    await user.click(screen.getByRole("button", { name: "Rename" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
      expect(call).toBeDefined();
      expect(String(call![0])).toBe("http://127.0.0.1:8003/meetings/m1/speakers/SPEAKER_01/label");
      expect(JSON.parse(String(call![1]!.body))).toEqual({ name: "Alice" });
    });
    expect(await screen.findByText("Alice")).toBeInTheDocument();
    await waitFor(() => {
      const profileGets = fetchMock.mock.calls.filter(
        ([url, init]) => String(url).endsWith("/speaker-profiles") && !init?.method,
      );
      expect(profileGets.length).toBeGreaterThanOrEqual(2);
    });
  });

  it("reassigns a cluster to an existing speaker profile", async () => {
    const fetchMock = stubProfiles([otherProfile]);
    const user = userEvent.setup();
    renderTab(<TranscriptTab meeting={meeting} segments={segments} />);

    await user.click(screen.getByText("SPEAKER_01"));
    await user.click(screen.getByRole("combobox", { name: "Reassign to existing speaker" }));
    await user.click(screen.getByRole("option", { name: "Bob" }));
    await user.click(screen.getByRole("button", { name: "Reassign" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url, init]) =>
        String(url).endsWith("/label") ? init?.method === "POST" : false,
      );
      expect(call).toBeDefined();
      expect(String(call![0])).toBe("http://127.0.0.1:8003/meetings/m1/speakers/SPEAKER_01/label");
      expect(JSON.parse(String(call![1]!.body))).toEqual({ name: "Bob" });
    });
    expect(await screen.findByText("Bob")).toBeInTheDocument();
  });

  it("merges the current speaker profile into another existing one", async () => {
    const fetchMock = stubProfiles([speakerProfile, otherProfile]);
    const user = userEvent.setup();
    renderTab(
      <TranscriptTab meeting={meeting} segments={[{ ...segments[0], speaker_profile_id: "p1" }]} />,
    );

    await user.click(await screen.findByText("Alice"));
    await user.click(screen.getByRole("combobox", { name: "Merge into another speaker" }));
    await user.click(screen.getByRole("option", { name: "Bob" }));
    await user.click(screen.getByRole("button", { name: "Merge" }));

    await waitFor(() => {
      const call = fetchMock.mock.calls.find(([url]) => String(url).endsWith("/merge"));
      expect(call).toBeDefined();
      expect(String(call![0])).toBe("http://127.0.0.1:8003/speaker-profiles/p2/merge");
      expect(JSON.parse(String(call![1]!.body))).toEqual({ other_profile_id: "p1" });
    });
    expect(await screen.findByRole("button", { name: "Bob" })).toBeInTheDocument();
  });
});
