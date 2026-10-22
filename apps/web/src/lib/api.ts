import type {
  ApiErrorBody,
  AskRequest,
  AskResponse,
  AssistantMode,
  AssistantRoute,
  ChatTurn,
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

export interface AssistantHandlers {
  /** The question type and the services the assistant will try, in order. */
  onRoute?: (route: AssistantRoute, providers: string[]) => void;
  /** The next piece of the answer as it is written. */
  onDelta?: (text: string) => void;
  /** A service failed partway; drop the text so far, the next one starts over. */
  onReset?: () => void;
}

/**
 * Asks the assistant, which answers anything and streams its answer.
 *
 * The first question of a conversation is sent on its own; later ones carry the
 * earlier messages. The API streams server-sent events; a plain JSON answer (an
 * older API) is accepted too.
 */
export async function askAssistant(
  question: string,
  history: ChatTurn[],
  mode: AssistantMode,
  handlers: AssistantHandlers = {},
  signal?: AbortSignal,
): Promise<AskResponse> {
  const body: AskRequest = history.length > 0 ? { question, history } : { question };
  const response = await fetch(`${API_BASE}/ask`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream, application/json",
      "X-Atlas-Mode": mode,
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok) throw await errorFrom(response);
  if (!(response.headers.get("content-type") ?? "").includes("text/event-stream")) {
    return (await response.json()) as AskResponse;
  }

  for await (const event of readServerSentEvents(response)) {
    const data = JSON.parse(event.data) as Record<string, unknown>;
    if (event.event === "route") {
      handlers.onRoute?.(data.route as AssistantRoute, (data.providers as string[]) ?? []);
    } else if (event.event === "delta") {
      handlers.onDelta?.(data.text as string);
    } else if (event.event === "reset") {
      handlers.onReset?.();
    } else if (event.event === "done") {
      return data as unknown as AskResponse;
    } else if (event.event === "error") {
      throw new ApiError(Number(data.status) || 500, String(data.detail));
    }
  }
  throw new ApiError(502, "The answer stopped before it was finished.");
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
