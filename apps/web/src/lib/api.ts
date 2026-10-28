import type {
  AnswerFormat,
  AnswerStyle,
  ApiErrorBody,
  AskRequest,
  AskResponse,
  AssistantMode,
  AssistantRoute,
  Attachment,
  AttachmentText,
  ChatTurn,
  CodeAnalysis,
  CouncilAgent,
  FileDetail,
  GeneratedImage,
  FileGraph,
  HealthParams,
  HealthReport,
  IngestEvent,
  IngestFailure,
  IngestProgress,
  IngestRequest,
  IngestResult,
  SharedChat,
  SiteConfig,
  SourceItem,
  WebSource,
} from "@atlas/shared";

import { readServerSentEvents } from "./sse";

/**
 * Where the API is. By default the same origin under /api, which the Next.js
 * server proxies. A static build (GitHub Pages) has no server, so it is built
 * with NEXT_PUBLIC_API_URL set to the API's own address instead.
 */
export const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? "").replace(/\/+$/, "") || "/api";

/** Starts waking a sleeping server (free hosting sleeps when idle) while the user types. */
export function wakeServer(): void {
  fetch(`${API_BASE}/healthz`, { cache: "no-store" }).catch(() => undefined);
}

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
  /** The code analyser's progress, for a code review. */
  onAnalysing?: (message: string) => void;
  /** What the code analyser found, before the agents review it. */
  onAnalysis?: (analysis: CodeAnalysis) => void;
  /** The web is being searched for the latest information. */
  onSearching?: () => void;
  /** What the web search found; every agent reads it. */
  onWeb?: (sources: WebSource[]) => void;
  /** A council agent was seated, answered, failed or was not waited for. */
  onAgent?: (agent: CouncilAgent) => void;
  /** The agents' drafts are being merged into one answer. */
  onMerging?: (drafts: number) => void;
  /** A picture of the gallery is ready. */
  onImage?: (image: GeneratedImage) => void;
}

export interface AssistantQuestion {
  question: string;
  history: ChatTurn[];
  mode: AssistantMode;
  attachments?: Attachment[];
  style?: AnswerStyle;
  temperature?: number | null;
  instructions?: string;
  /** "image" draws a picture; "review" runs the code analyser and reviews its findings. */
  task?: "answer" | "image" | "review";
  services?: string[];
  councilSize?: number | null;
  merger?: string;
  useSources?: boolean;
  topK?: number;
  minScore?: number | null;
  webSearch?: boolean;
  maxTokens?: number | null;
  format?: AnswerFormat;
  includeDrafts?: boolean;
  strict?: boolean;
  planQueries?: boolean;
}

const DEFAULT_TOP_K = 8;

/** The request body, with only what differs from the API's defaults. */
export function askBody(asked: AssistantQuestion): AskRequest {
  const body: AskRequest = { question: asked.question };
  if (asked.history.length > 0) body.history = asked.history;
  if (asked.attachments?.length) body.attachments = asked.attachments;
  if (asked.style && asked.style !== "balanced") body.style = asked.style;
  if (asked.temperature !== undefined && asked.temperature !== null) {
    body.temperature = asked.temperature;
  }
  if (asked.instructions?.trim()) body.instructions = asked.instructions.trim();
  if (asked.task === "image" || asked.task === "review") body.task = asked.task;
  if (asked.services?.length) body.services = asked.services;
  if (asked.councilSize) body.council_size = asked.councilSize;
  if (asked.merger) body.merger = asked.merger;
  if (asked.useSources === false) body.use_sources = false;
  if (asked.topK && asked.topK !== DEFAULT_TOP_K) body.top_k = asked.topK;
  if (asked.minScore !== undefined && asked.minScore !== null) body.min_score = asked.minScore;
  if (asked.webSearch === false) body.web_search = false;
  if (asked.maxTokens) body.max_tokens = asked.maxTokens;
  if (asked.format && asked.format !== "markdown") body.format = asked.format;
  if (asked.includeDrafts) body.include_drafts = true;
  if (asked.strict) body.strict = true;
  if (asked.planQueries === false) body.plan_queries = false;
  return body;
}

/**
 * Asks the assistant, which answers anything and streams its answer.
 *
 * The first question of a conversation is sent on its own; later ones carry the
 * earlier messages. The API streams server-sent events; a plain JSON answer (an
 * older API) is accepted too.
 */
export async function askAssistant(
  asked: AssistantQuestion,
  handlers: AssistantHandlers = {},
  signal?: AbortSignal,
): Promise<AskResponse> {
  const body = askBody(asked);
  const mode = asked.mode;
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
    } else if (event.event === "analysing") {
      handlers.onAnalysing?.(String(data.message ?? ""));
    } else if (event.event === "analysis") {
      handlers.onAnalysis?.(data as unknown as CodeAnalysis);
    } else if (event.event === "searching") {
      handlers.onSearching?.();
    } else if (event.event === "web") {
      handlers.onWeb?.((data.sources as WebSource[]) ?? []);
    } else if (event.event === "agent") {
      handlers.onAgent?.(data as unknown as CouncilAgent);
    } else if (event.event === "merging") {
      handlers.onMerging?.(Number(data.drafts) || 0);
    } else if (event.event === "image") {
      handlers.onImage?.(data as unknown as GeneratedImage);
    } else if (event.event === "done") {
      return data as unknown as AskResponse;
    } else if (event.event === "error") {
      throw new ApiError(Number(data.status) || 500, String(data.detail));
    }
  }
  throw new ApiError(502, "The answer stopped before it was finished.");
}

/** Reads a document's text (PDF, EPUB, HTML, code, plain text) for attaching to a question. */
export async function readAttachment(file: File): Promise<AttachmentText> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/attachments`, { method: "POST", body: form });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as AttachmentText;
}

/** Stores a copy of a conversation; anyone with the returned id can read it. */
export function createShare<M>(title: string, messages: M[]): Promise<SharedChat<M>> {
  return request<SharedChat<M>>("/shares", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title, messages }),
  });
}

export function getShare<M>(id: string): Promise<SharedChat<M>> {
  return request<SharedChat<M>>(`/shares/${encodeURIComponent(id)}`);
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
