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
  SourceItem,
} from "@atlas/shared";

import { readServerSentEvents } from "./sse";

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
  const response = await fetch(`/api${path}`, init);
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
  const response = await fetch(`/api/sources/${id}`, { method: "DELETE" });
  if (!response.ok) throw await errorFrom(response);
}

/** Adds a source from a link and yields progress until a `done` or `error` event. */
export function ingest(body: IngestRequest, signal?: AbortSignal): AsyncGenerator<IngestEvent> {
  return ingestEvents(
    fetch("/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
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
    fetch("/api/ingest/upload", {
      method: "POST",
      headers: { Accept: "text/event-stream" },
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
