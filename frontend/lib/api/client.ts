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

export async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, {
      ...init,
      headers: { "content-type": "application/json", ...(init?.headers ?? {}) },
    });
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

  return body as T;
}
