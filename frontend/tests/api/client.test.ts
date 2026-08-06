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
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            JSON.stringify({ code: "MEETING_NOT_FOUND", message: "nope" }),
            { status: 404, headers: { "content-type": "application/json" } },
          ),
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
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ ok: true })));
    vi.stubGlobal("fetch", fetchMock);
    await request("http://storage/meetings", {
      headers: { Authorization: "Bearer x" },
    });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://storage/meetings");
    expect(init.headers).toEqual({
      "content-type": "application/json",
      Authorization: "Bearer x",
    });
  });

  it("marks offline when fetch rejects", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch")),
    );
    const err = (await request("http://storage/meetings").catch(
      (e) => e as ApiError,
    )) as ApiError;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.offline).toBe(true);
  });
});
