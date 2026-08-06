import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, request } from "@/lib/api/client";

describe("request", () => {
  afterEach(() => vi.restoreAllMocks());

  it("returns parsed json on 2xx", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ hello: "world" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    await expect(request("http://storage/meetings")).resolves.toEqual({
      hello: "world",
    });
  });

  it("throws ApiError with code and message from a BahlilyError body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ code: "MEETING_NOT_FOUND", message: "nope" }), {
          status: 404,
          headers: { "content-type": "application/json" },
        }),
      ),
    );
    const err = (await request("http://storage/meetings/x").catch(
      (e) => e as ApiError,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("MEETING_NOT_FOUND");
    expect(err.message).toBe("nope");
    expect(err.offline).toBe(false);
  });

  it("merges caller headers with the json content-type", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    await request("http://storage/meetings", {
      headers: { Authorization: "Bearer x" },
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://storage/meetings");
    const headers = init.headers as Headers;
    expect(headers).toBeInstanceOf(Headers);
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("Authorization")).toBe("Bearer x");
  });

  it("preserves Headers and tuple-array entries supplied by the caller", async () => {
    const fetchMock = vi.fn(() => Promise.resolve(new Response(JSON.stringify({ ok: true }))));
    vi.stubGlobal("fetch", fetchMock);

    const headersInstance = new Headers({ Authorization: "Bearer H" });
    await request("http://storage/meetings", { headers: headersInstance });
    const headers = fetchMock.mock.calls[0]![1]!.headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer H");
    expect(headers.get("content-type")).toBe("application/json");

    fetchMock.mockClear();
    await request("http://storage/meetings", {
      headers: [["Authorization", "Bearer T"]],
    });
    const tupleHeaders = fetchMock.mock.calls[0]![1]!.headers as Headers;
    expect(tupleHeaders.get("Authorization")).toBe("Bearer T");
    expect(tupleHeaders.get("content-type")).toBe("application/json");
  });

  it("honors a caller content-type without overriding it", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("plain", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await request("http://storage/meetings", {
      headers: { "Content-Type": "text/plain" },
    });
    const headers = fetchMock.mock.calls[0]![1]!.headers as Headers;
    expect(headers.get("content-type")).toBe("text/plain");
  });

  it("attaches the capability token when NEXT_PUBLIC_BAHLILY_CAPABILITY is set", async () => {
    const previous = process.env.NEXT_PUBLIC_BAHLILY_CAPABILITY;
    process.env.NEXT_PUBLIC_BAHLILY_CAPABILITY = "secret-token";
    try {
      const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })));
      vi.stubGlobal("fetch", fetchMock);
      await request("http://storage/meetings");
      const headers = fetchMock.mock.calls[0]![1]!.headers as Headers;
      expect(headers.get("x-bahlily-capability")).toBe("secret-token");
    } finally {
      if (previous === undefined) delete process.env.NEXT_PUBLIC_BAHLILY_CAPABILITY;
      else process.env.NEXT_PUBLIC_BAHLILY_CAPABILITY = previous;
    }
  });

  it("marks offline when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = (await request("http://storage/meetings").catch((e) => e as ApiError)) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.offline).toBe(true);
  });
});
