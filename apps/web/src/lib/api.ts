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
  CodeChunk,
  CouncilAgent,
  FactCheck,
  GapReport,
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
  KnowledgeAudit,
  KnowledgeHealth,
  ResearchStep,
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

// The admin session an authenticator unlock gives: its key signs requests that add or
// remove sources.
const SESSION_KEY = "atlas-admin-session";

export interface AdminSession {
  session: string;
  key: string;
  expires_at: number;
}

export function getAdminSession(): AdminSession | null {
  try {
    const raw = window.localStorage.getItem(SESSION_KEY);
    const session = raw ? (JSON.parse(raw) as AdminSession) : null;
    return session && session.expires_at * 1000 > Date.now() ? session : null;
  } catch {
    return null;
  }
}

export function setAdminSession(session: AdminSession | null): void {
  try {
    if (session) window.localStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else window.localStorage.removeItem(SESSION_KEY);
  } catch {
    // Not remembered: unlock again next time.
  }
}

function hex(bytes: ArrayBuffer): string {
  return [...new Uint8Array(bytes)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** X-Atlas-Session, -Timestamp and -Signature for an admin request, if a session is open:
 * HMAC-SHA256 of "METHOD\nPATH\nTIMESTAMP\nSHA256(body)" with the session's key. */
async function signedHeaders(
  method: string,
  path: string,
  body: ArrayBuffer,
): Promise<Record<string, string>> {
  const session = getAdminSession();
  if (!session || !globalThis.crypto?.subtle) return {};
  const stamp = String(Math.floor(Date.now() / 1000));
  const digest = hex(await crypto.subtle.digest("SHA-256", body));
  const raw = new Uint8Array(session.key.match(/../g)!.map((h) => parseInt(h, 16)));
  const key = await crypto.subtle.importKey("raw", raw, { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const message = new TextEncoder().encode(`${method.toUpperCase()}\n${path}\n${stamp}\n${digest}`);
  return {
    "X-Atlas-Session": session.session,
    "X-Atlas-Timestamp": stamp,
    "X-Atlas-Signature": hex(await crypto.subtle.sign("HMAC", key, message)),
  };
}

/** A request that changes the sources: with the admin password and, when an
 * authenticator session is open, signed. A form is serialised first, so the bytes signed
 * are the bytes sent. */
async function adminFetch(
  path: string,
  init: { method: string; headers?: Record<string, string>; body?: string | FormData; signal?: AbortSignal },
): Promise<Response> {
  let body: ArrayBuffer = new ArrayBuffer(0);
  const headers: Record<string, string> = { ...(init.headers ?? {}), ...adminHeaders() };
  if (typeof init.body === "string") {
    body = new TextEncoder().encode(init.body).buffer as ArrayBuffer;
  } else if (init.body instanceof FormData) {
    const encoded = new Response(init.body);
    body = await encoded.arrayBuffer();
    headers["Content-Type"] = encoded.headers.get("content-type") ?? "multipart/form-data";
  }
  Object.assign(headers, await signedHeaders(init.method, path, body));
  return fetch(`${API_BASE}${path}`, {
    method: init.method,
    headers,
    body: init.body === undefined ? undefined : body,
    signal: init.signal,
  });
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
export async function checkAdmin(token: string, code?: string): Promise<boolean> {
  const response = await fetch(`${API_BASE}/admin/check`, {
    method: "POST",
    headers: code
      ? { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }
      : { Authorization: `Bearer ${token}` },
    body: code ? JSON.stringify({ code }) : undefined,
  });
  if (response.status === 401) return false;
  if (!response.ok) throw await errorFrom(response);
  // With an authenticator: a session whose key signs requests that change the sources.
  if (response.status === 200) setAdminSession((await response.json()) as AdminSession);
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
  /** Deep research: one tool call of the agent. */
  onResearch?: (step: ResearchStep) => void;
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
  rerank?: boolean;
  rankPassages?: boolean;
  /** True always, false never, unset when the server decides. */
  research?: boolean;
  /** False: never use the answer cache. */
  cache?: boolean;
  /** Answer afresh this once, but keep the answer (Regenerate). */
  fresh?: boolean;
  /** The chat this question belongs to, for the answer log and its knowledge health. */
  chatId?: string;
  /** Allow the web and general knowledge, not only the knowledge base. */
  open?: boolean;
  rerankCutoff?: number | null;
}

const DEFAULT_TOP_K = 5;

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
  if (asked.rerank === false) body.rerank = false;
  if (asked.research !== undefined) body.research = asked.research;
  if (asked.cache === false) body.cache = false;
  if (asked.rankPassages === false) body.rank_passages = false;
  if (asked.rerankCutoff !== undefined && asked.rerankCutoff !== null) {
    body.rerank_cutoff = asked.rerankCutoff;
  }
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
      ...(asked.fresh ? { "X-Atlas-Fresh": "true" } : {}),
      ...(asked.chatId ? { "X-Atlas-Chat": asked.chatId } : {}),
      ...(asked.open ? { "X-Atlas-Open": "true" } : {}),
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
    } else if (event.event === "researching") {
      handlers.onResearch?.(data as unknown as ResearchStep);
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

/** Has the fact-checker check an answer against the excerpts it was given. */
export async function factCheck(
  question: string,
  answer: string,
  chunks: CodeChunk[],
): Promise<FactCheck> {
  const response = await request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ question, task: "check", answer, chunks }),
  });
  if (!response.fact_check) throw new ApiError(503, "The fact-checker gave no report.");
  return response.fact_check;
}

/** Has the self-challenge object to an answer from its excerpts, and revise it if the
 * objection holds: the response carries the final answer, its citations and the report. */
export async function challengeAnswer(
  question: string,
  answer: string,
  chunks: CodeChunk[],
): Promise<AskResponse> {
  const response = await request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ question, task: "challenge", answer, chunks }),
  });
  if (!response.challenge) throw new ApiError(503, "The self-challenge gave no report.");
  return response;
}

/** Has the gap finder say what the knowledge base lacks to answer a question. */
export async function findGaps(question: string): Promise<GapReport> {
  const response = await request<AskResponse>("/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ question, task: "gaps" }),
  });
  if (!response.gaps) throw new ApiError(503, "The gap finder gave no report.");
  return response.gaps;
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

/** Has a model audit every source now (admin only); the table is kept for the Health page. */
export function runKnowledgeAudit(): Promise<KnowledgeAudit> {
  return request<KnowledgeAudit>("/health", { method: "POST", headers: adminHeaders() });
}

/** The knowledge-health note from the answer log: for one chat, or for everything. */
export async function getKnowledgeHealth(chatId?: string): Promise<KnowledgeHealth | null> {
  const report = await request<HealthReport>(
    `/health?limit=1${chatId ? `&chat=${encodeURIComponent(chatId)}` : ""}`,
  );
  return report.knowledge_health ?? null;
}

export function getSources(): Promise<SourceItem[]> {
  return request<SourceItem[]>("/sources");
}

/** Sets how much a source counts (3 primary, 2 secondary, 1 derived), or null for automatic. */
export async function setSourceWeight(id: number, weight: number | null): Promise<SourceItem> {
  const response = await adminFetch(`/sources/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weight }),
  });
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as SourceItem;
}

export async function deleteSource(id: number): Promise<void> {
  const response = await adminFetch(`/sources/${id}`, { method: "DELETE" });
  if (!response.ok) throw await errorFrom(response);
}

/** Adds a source from a link and yields progress until a `done` or `error` event. */
export function ingest(body: IngestRequest, signal?: AbortSignal): AsyncGenerator<IngestEvent> {
  return ingestEvents(
    adminFetch("/ingest", {
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
  // The multipart boundary comes from serialising the form (see adminFetch).
  return ingestEvents(
    adminFetch("/ingest/upload", {
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
