export class ApiError extends Error {
  status: number;
  code: string | null;
  offline: boolean;

  constructor(status: number, code: string | null, message: string, offline = false) {
    super(message);
    this.status = status;
    this.code = code;
    this.offline = offline;
  }
}

function readCapability(): string | null {
  const raw = process.env.NEXT_PUBLIC_BAHLILY_CAPABILITY?.trim();
  return raw && raw.length > 0 ? raw : null;
}

function buildHeaders(init?: RequestInit): Headers {
  const headers = new Headers(init?.headers);
  if (!headers.has("content-type")) {
    headers.set("content-type", "application/json");
  }
  const capability = readCapability();
  if (capability !== null && !headers.has("x-bahlily-capability")) {
    headers.set("x-bahlily-capability", capability);
  }
  return headers;
}

export async function request<T>(
  url: string,
  init?: RequestInit,
  decode?: (value: unknown) => T,
): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, { ...init, headers: buildHeaders(init) });
  } catch {
    throw new ApiError(0, null, "service is offline", true);
  }

  let body: unknown = null;
  const text = await resp.text();
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = null;
    }
  }

  if (!resp.ok) {
    const b = (body ?? {}) as {
      code?: string;
      message?: string;
      detail?: unknown;
    };
    const code = typeof b.code === "string" ? b.code : null;
    const message =
      typeof b.message === "string"
        ? b.message
        : typeof b.detail === "string"
          ? b.detail
          : resp.statusText;
    throw new ApiError(resp.status, code, message);
  }

  return decode ? decode(body) : (body as T);
}
