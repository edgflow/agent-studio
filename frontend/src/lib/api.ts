// Every request goes to our own origin (/api is proxied to FastAPI) and
// carries the X-Requested-With header the backend requires on writes.

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public body: unknown,
  ) {
    super(message);
  }
}

function messageOf(body: unknown): string | null {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) return detail.map((d) => d.msg ?? String(d)).join("; ");
    if (detail && typeof detail === "object" && "message" in detail) {
      return String((detail as { message: unknown }).message);
    }
  }
  return null;
}

export async function api<T>(
  path: string,
  options: { method?: string; json?: unknown } = {},
): Promise<T> {
  const headers: Record<string, string> = { "X-Requested-With": "studio" };
  if (options.json !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.json === undefined ? undefined : JSON.stringify(options.json),
    credentials: "same-origin",
  });
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    throw new ApiError(response.status, messageOf(body) ?? response.statusText, body);
  }
  return body as T;
}
