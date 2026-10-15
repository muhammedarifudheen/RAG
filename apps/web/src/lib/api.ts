import type {
  ApiErrorBody,
  AskRequest,
  AskResponse,
  FileDetail,
  FileGraph,
  HealthParams,
  HealthReport,
  IngestEvent,
  IngestFailure,
  IngestProgress,
  IngestRequest,
  IngestResult,
  SiteConfig,
  SourceItem,
} from "@atlas/shared";

import { readServerSentEvents } from "./sse";

/**
 * Where the API is. By default the same origin under /api, which the Next.js
 * server proxies. A static build (GitHub Pages) has no server, so it is built
 * with NEXT_PUBLIC_API_URL set to the API's own address instead.
 */
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "") || "/api";

const ADMIN_KEY = "atlas-admin-token";

/** The admin password remembered in this browser, if any. */
export function getAdminToken(): string | null {
  try {
    return window.localStorage.getItem(ADMIN_KEY);
  } catch {
    return null; // storage blocked or unavailable: the visitor just is not an admin
  }
}

export function setAdminToken(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(ADMIN_KEY, token);
    else window.localStorage.removeItem(ADMIN_KEY);
  } catch {
    // Not remembered; the visitor can unlock again.
  }
}

function adminHeaders(): Record<string, string> {
  const token = getAdminToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function errorFrom(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status})`;
  try {
    const body = (await response.json()) as ApiErrorBody;
    message =
      typeof body.detail === "string" ? body.detail : body.detail.map((d) => d.msg).join("; ");
  } catch {
    // Not JSON (for example a proxy error page); keep the generic message.
  }
  return new ApiError(response.status, message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

function query(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export function getConfig(): Promise<SiteConfig> {
  return request<SiteConfig>("/config");
}

/** True if the API accepts this admin password. */
export async function checkAdmin(token: string): Promise<boolean> {
  const response = await fetch(`${API_BASE}/admin/check`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  if (response.status === 401) return false;
  if (!response.ok) throw await errorFrom(response);
  return true;
}

export function ask(body: AskRequest): Promise<AskResponse> {
  return request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getFile(path: string): Promise<FileDetail> {
  return request<FileDetail>(`/file${query({ path })}`);
}

export function getFileGraph(): Promise<FileGraph> {
  return request<FileGraph>("/graph/files");
}

export function getHealth(params: HealthParams = {}): Promise<HealthReport> {
  return request<HealthReport>(`/health${query(params)}`);
}

export function getSources(): Promise<SourceItem[]> {
  return request<SourceItem[]>("/sources");
}

export async function deleteSource(id: number): Promise<void> {
  const response = await fetch(`${API_BASE}/sources/${id}`, {
    method: "DELETE",
    headers: adminHeaders(),
  });
  if (!response.ok) throw await errorFrom(response);
}

/** Adds a source from a link and yields progress until a `done` or `error` event. */
export function ingest(body: IngestRequest, signal?: AbortSignal): AsyncGenerator<IngestEvent> {
  return ingestEvents(
    fetch(`${API_BASE}/ingest`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        ...adminHeaders(),
      },
      body: JSON.stringify(body),
      signal,
    }),
  );
}

/** Adds a source from a file and yields progress the same way. */
export function ingestFile(file: File, signal?: AbortSignal): AsyncGenerator<IngestEvent> {
  const form = new FormData();
  form.append("file", file);
  // No Content-Type header: the browser sets the multipart boundary itself.
  return ingestEvents(
    fetch(`${API_BASE}/ingest/upload`, {
      method: "POST",
      headers: { Accept: "text/event-stream", ...adminHeaders() },
      body: form,
      signal,
    }),
  );
}

async function* ingestEvents(pending: Promise<Response>): AsyncGenerator<IngestEvent> {
  const response = await pending;
  if (!response.ok) throw await errorFrom(response);

  for await (const { event, data } of readServerSentEvents(response)) {
    if (event === "progress") {
      yield { type: "progress", ...(JSON.parse(data) as IngestProgress) };
    } else if (event === "done") {
      yield { type: "done", ...(JSON.parse(data) as IngestResult) };
    } else if (event === "error") {
      yield { type: "error", ...(JSON.parse(data) as IngestFailure) };
    }
  }
}
