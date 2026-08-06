import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deleteMeeting,
  getMeeting,
  labelSpeaker,
  listMeetings,
  listSegments,
  saveSummary,
} from "@/lib/api/storage";

function stubFetch(status: number, body: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      new Response(body === null ? null : JSON.stringify(body), {
        status,
        headers: { "content-type": "application/json" },
      }),
    ),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("storage api", () => {
  it("listMeetings calls /meetings with limit and offset", async () => {
    stubFetch(200, []);
    await listMeetings(10, 0);
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8003/meetings?limit=10&offset=0");
    expect(init.method).toBeUndefined();
  });

  it("deleteMeeting issues DELETE and returns void", async () => {
    stubFetch(204, null);
    await deleteMeeting("m1");
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8003/meetings/m1");
    expect(init.method).toBe("DELETE");
  });

  it("getMeeting returns a typed Meeting", async () => {
    stubFetch(200, { id: "m1", status: "recording" });
    const m = await getMeeting("m1");
    expect(m.id).toBe("m1");
  });

  it("listSegments returns segments", async () => {
    stubFetch(200, [{ segment_id: 1, text: "hi" }]);
    const segs = await listSegments("m1");
    expect(segs).toHaveLength(1);
  });

  it("labelSpeaker posts the label body", async () => {
    stubFetch(200, { id: "p1", name: "Alice" });
    await labelSpeaker("m1", "SPEAKER_01", "Alice");
    const [, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({ name: "Alice" });
  });

  it("saveSummary posts the summary body", async () => {
    stubFetch(201, {
      id: "s1",
      meeting_id: "m1",
      title: "T",
      overview: "O",
      key_points: [],
      action_items: [],
      quotes: [],
      provider: "openai",
      model: "gpt-4o",
      created_at: "2026-01-01T00:00:00Z",
    });
    await saveSummary("m1", {
      title: "T",
      overview: "O",
      key_points: [],
      action_items: [],
      quotes: [],
      provider: "openai",
      model: "gpt-4o",
    });
    const [url, init] = vi.mocked(fetch).mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://127.0.0.1:8003/meetings/m1/summary");
    expect(init.method).toBe("POST");
    expect(JSON.parse(String(init.body))).toEqual({
      title: "T",
      overview: "O",
      key_points: [],
      action_items: [],
      quotes: [],
      provider: "openai",
      model: "gpt-4o",
    });
  });
});
