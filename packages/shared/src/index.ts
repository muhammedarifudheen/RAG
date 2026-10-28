// Shapes of the Atlas API's requests and responses.
// Mirrors apps/api/app/schemas.py; change both together.

/** "section" is a passage of a document; the others are code. */
export type SymbolKind = "module" | "function" | "class" | "method" | "section";
export type EdgeKind = "calls" | "imports" | "inherits";
export type Language = "python" | "typescript" | "go";

// --- /search and /ask -------------------------------------------------------

export interface CodeChunk {
  symbol_id: number;
  name: string;
  kind: SymbolKind;
  signature: string | null;
  file: string;
  language: string;
  /** First line of the symbol, 1-based. */
  start_line: number;
  /** Last line of the symbol, inclusive. */
  end_line: number;
  /** Cosine similarity to the query; higher is closer. */
  score: number;
  snippet: string;
  snippet_end_line: number;
  truncated: boolean;
  citation: string;
}

export interface SearchResponse {
  query: string;
  results: CodeChunk[];
}

/** One earlier message of a conversation, sent along for follow-up questions. */
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

/** A file sent with a question: its text, or an image (base64). */
export interface Attachment {
  name: string;
  kind: "text" | "image";
  text?: string;
  mime?: "image/png" | "image/jpeg" | "image/webp" | "image/gif";
  data?: string;
}

/** How long and detailed answers should be. */
export type AnswerStyle = "balanced" | "concise" | "detailed";

export interface AskRequest {
  question: string;
  top_k?: number;
  /** Earlier messages, oldest first; sent, the assistant answers. */
  history?: ChatTurn[];
  // The assistant only; each is left out when it has its default value.
  attachments?: Attachment[];
  style?: AnswerStyle;
  /** 0 to 2; unset is each model's default. */
  temperature?: number;
  /** Standing instructions to the assistant. */
  instructions?: string;
  /** "image" draws a picture of the question. */
  task?: "answer" | "image" | "review";
  /** Only these AI services answer; empty or absent is every configured one. */
  services?: string[];
  /** Agents answering in parallel (1-12); 1 is one model. */
  council_size?: number;
  /** The service that merges the drafts, if it answered. */
  merger?: string;
  /** Search the knowledge base (default true). */
  use_sources?: boolean;
  /** Excerpts less similar than this (0-1) are left out. */
  min_score?: number;
  /** Search the web before answering (default true). */
  web_search?: boolean;
  /** The longest answer, in tokens. */
  max_tokens?: number;
  format?: AnswerFormat;
  /** Return each council agent's own draft. */
  include_drafts?: boolean;
  /** Strict sources only: the knowledge base and attached files, cited, or "not there". */
  strict?: boolean;
  /** Plan several knowledge-base searches (keywords, a hypothetical answer…); default true. */
  plan_queries?: boolean;
}

export type AnswerFormat = "markdown" | "plain" | "json";

export interface AgentDraft {
  /** "Service · model". */
  agent: string;
  seconds: number;
  answer: string;
}

/** POST /attachments: a document's text, read for attaching to a question. */
export interface AttachmentText {
  name: string;
  kind: "text";
  text: string;
  /** True if the text was cut to the size limit. */
  truncated: boolean;
}

export interface GeneratedImage {
  /** A web address, or a data: URL for services that return the picture itself. */
  url: string;
  prompt: string;
  /** The service that drew it. */
  service?: string | null;
}

/** One agent of the council, as reported while the answer is prepared. */
export interface CouncilAgent {
  id: number;
  service?: string;
  model?: string;
  state: "thinking" | "done" | "failed" | "skipped";
  seconds?: number;
}

/** How the assistant picks models: by question type, or the strongest first. */
export type AssistantMode = "auto" | "best";

export type AssistantRoute =
  | "sources"
  | "code"
  | "current"
  | "reasoning"
  | "chat"
  | "general"
  | "image"
  | "vision"
  | "review";

export interface WebSource {
  title: string;
  url: string;
}

export interface Citation {
  /** The citation as written in the answer, e.g. "[pkg/models.py:20-21]". */
  ref: string;
  file: string;
  start_line: number;
  end_line: number;
  /** False if the cited lines were not in the code sent to the model. */
  verified: boolean;
}

export interface AskResponse {
  question: string;
  answer: string;
  citations: Citation[];
  chunks: CodeChunk[];
  model: string;
  /** False if the answer was cut off at the token limit. */
  complete: boolean;
  /** Set by the assistant: the service that answered ("Gemini", "Groq", …). */
  provider?: string | null;
  route?: AssistantRoute | null;
  /** Follow-up questions to offer. */
  suggestions?: string[];
  /** Web pages a search found. */
  web_sources?: WebSource[];
  /** Pictures drawn for the answer. */
  images?: GeneratedImage[];
  /** The council's agents whose drafts were merged into the answer. */
  agents?: string[];
  /** For a code review: what the code analyser found. */
  analysis?: CodeAnalysis | null;
  /** Each council agent's own draft, when include_drafts was set. */
  drafts?: AgentDraft[];
  /** The knowledge-base searches the query planner ran. */
  search_queries?: string[];
}

// --- The code analyser (a review's `analysis`) --------------------------------

export type Severity = "high" | "medium" | "low";

export interface CodeFinding {
  /** ruff, secrets, patterns or complexity. */
  tool: string;
  rule: string;
  severity: Severity;
  path: string;
  line: number;
  message: string;
}

export interface FunctionMetric {
  path: string;
  name: string;
  start_line: number;
  end_line: number;
  /** Cyclomatic: 1 + decision points. */
  complexity: number;
  nesting: number;
}

export interface FileRisk {
  path: string;
  lines: number;
  findings: number;
  complexity: number;
  imported_by: number;
  risk: number;
}

export interface CodeAnalysis {
  /** The GitHub repository analysed, for a repository review. */
  repo?: string | null;
  commit?: string | null;
  files: number;
  lines: number;
  code_lines: number;
  /** Lines per language. */
  languages: Record<string, number>;
  /** 0-100: findings per thousand lines of code, weighted by severity. */
  score: number;
  grade: string;
  counts: Record<Severity, number>;
  findings: CodeFinding[];
  functions: FunctionMetric[];
  test_files?: number | null;
  cycles?: string[][];
  most_imported?: { path: string; imported_by: number }[];
  riskiest?: FileRisk[];
  seconds?: number | null;
}

// --- /shares ----------------------------------------------------------------

/** A conversation shared by link. `messages` are kept as the web app sent them. */
export interface SharedChat<M = unknown> {
  id: string;
  title: string;
  messages: M[];
  created_at: string;
}

// --- /graph, /graph/files and /file -----------------------------------------

export interface SymbolRef {
  id: number;
  name: string;
  kind: SymbolKind;
  file: string;
  start_line: number;
  end_line: number;
}

export interface GraphNode extends SymbolRef {
  depth: number;
}

export interface GraphEdge {
  source: number;
  target: number;
}

export type GraphDirection = "both" | "callers" | "callees";

export interface GraphResponse {
  file: string;
  hops: number;
  direction: GraphDirection;
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
}

export interface FileNode {
  id: number;
  path: string;
  language: string;
  loc: number;
  symbols: number;
  in_cycle: boolean;
}

export interface FileEdge {
  source: number;
  target: number;
  imports: number;
  calls: number;
  inherits: number;
  in_cycle: boolean;
}

export interface FileGraph {
  nodes: FileNode[];
  edges: FileEdge[];
  /** Groups of file ids that depend on each other. */
  cycles: number[][];
}

export interface FileSymbol {
  id: number;
  name: string;
  kind: SymbolKind;
  start_line: number;
  end_line: number;
  signature: string | null;
}

export interface FileDetail {
  path: string;
  language: string;
  loc: number;
  content: string;
  symbols: FileSymbol[];
}

// --- /health ----------------------------------------------------------------

export interface LongFunction extends SymbolRef {
  loc: number;
}

export interface FanOut {
  file: string;
  fan_out: number;
  depends_on: string[];
}

export interface Cycles {
  files: string[][];
  calls: SymbolRef[][];
}

export interface HealthSummary {
  files: number;
  symbols: number;
  edges: number;
  dead_symbols: number;
  file_cycles: number;
  call_cycles: number;
  long_functions: number;
  high_fan_out_files: number;
}

export interface HealthThresholds {
  max_function_loc: number;
  min_fan_out: number;
}

export interface HealthReport {
  summary: HealthSummary;
  thresholds: HealthThresholds;
  dead_symbols: SymbolRef[];
  circular_dependencies: Cycles;
  long_functions: LongFunction[];
  high_fan_out_files: FanOut[];
}

export interface HealthParams {
  max_function_loc?: number;
  min_fan_out?: number;
  limit?: number;
}

// --- /ingest (Server-Sent Events) -------------------------------------------

export type SourceKind = "repo" | "web" | "wikipedia" | "crawl" | "upload";

export interface IngestRequest {
  /** A GitHub repository, a Wikipedia article or any public web page. */
  url: string;
  /** "auto" (the default) picks repo, wikipedia or web from the address. */
  kind?: "auto" | "repo" | "web" | "wikipedia" | "crawl";
  /** Page limit for a crawl, 1 to 100. */
  max_pages?: number;
}

/** GET /config: what this deployment allows. */
export interface SiteConfig {
  /** Adding and removing sources needs the admin password. */
  admin_required: boolean;
  /** A model provider key is set, so questions can be answered. */
  chat_configured: boolean;
}

/** One entry of GET /sources. */
export interface SourceItem {
  id: number;
  kind: SourceKind;
  title: string;
  url: string | null;
  created_at: string;
  files: number;
  /** Symbols and passages that can be searched. */
  symbols: number;
}

/** `step` is set when a pipeline step starts and null for detail within the current step. */
export interface IngestProgress {
  step: number | null;
  total: number | null;
  message: string;
}

export interface IngestResult {
  files: number;
  symbols: number;
  edges: number;
}

export interface IngestFailure {
  message: string;
}

export type IngestEvent =
  | ({ type: "progress" } & IngestProgress)
  | ({ type: "done" } & IngestResult)
  | ({ type: "error" } & IngestFailure);

// --- errors -----------------------------------------------------------------

/** Body of every non-2xx response. Validation errors carry a list. */
export interface ApiErrorBody {
  detail: string | { msg: string }[];
}
