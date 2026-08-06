import { afterEach, describe, expect, it, vi } from "vitest";
import {
  deleteMeeting,
  getMeeting,
  labelSpeaker,
  listMeetings,
  listSegments,
  saveSummary,
} from "@/lib/api/storage";

type Responder = (url: string, init?: RequestInit) => Promise<Response>;

function jsonResponse(status: number, body: unknown): Response {
  return new Response(body === null ? null : JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function stubFetch(responder: Responder) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
      const url = typeof input === "string" ? input : input.toString();
      return responder(url, init);
    }),
  );
}

function getLastCall(): [string, RequestInit] {
  const call = vi.mocked(fetch).mock.calls.at(-1);
  if (call === undefined) throw new Error("fetch was not called");
  return call as [string, RequestInit];
}

afterEach(() => vi.restoreAllMocks());

describe("storage api", () => {
  it("listMeetings calls /meetings with limit and offset", async () => {
    stubFetch(async (url) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings?limit=10&offset=0");
      return jsonResponse(200, []);
    });
    await listMeetings(10, 0);
    const [, init] = getLastCall();
    expect(init.method).toBeUndefined();
  });

  it("deleteMeeting issues DELETE and returns void", async () => {
    stubFetch(async (url, init) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings/m1");
      expect(init?.method).toBe("DELETE");
      return jsonResponse(204, null);
    });
    await deleteMeeting("m1");
  });

  it("getMeeting returns a typed Meeting", async () => {
    stubFetch(async (url) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings/m1");
      return jsonResponse(200, { id: "m1", status: "recording" });
    });
    const m = await getMeeting("m1");
    expect(m.id).toBe("m1");
  });

  it("listSegments returns segments", async () => {
    stubFetch(async (url) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings/m1/segments");
      return jsonResponse(200, [{ segment_id: 1, text: "hi" }]);
    });
    const segs = await listSegments("m1");
    expect(segs).toHaveLength(1);
  });

  it("labelSpeaker posts the label body", async () => {
    stubFetch(async (url, init) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings/m1/speakers/SPEAKER_01/label");
      expect(init?.method).toBe("POST");
      return jsonResponse(200, { id: "p1", name: "Alice" });
    });
    await labelSpeaker("m1", "SPEAKER_01", "Alice");
    const [, init] = getLastCall();
    expect(JSON.parse(String(init.body))).toEqual({ name: "Alice" });
  });

  it("saveSummary posts the summary body", async () => {
    stubFetch(async (url, init) => {
      expect(url).toBe("http://127.0.0.1:8003/meetings/m1/summary");
      expect(init?.method).toBe("POST");
      return jsonResponse(201, {
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
    const [, init] = getLastCall();
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
