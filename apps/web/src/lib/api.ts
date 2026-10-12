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

/** Starts an ingest and yields its progress until a `done` or `error` event ends the stream. */
export async function* ingest(repoUrl: string, signal?: AbortSignal): AsyncGenerator<IngestEvent> {
  const body: IngestRequest = { repo_url: repoUrl };
  const response = await fetch("/api/ingest", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
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
