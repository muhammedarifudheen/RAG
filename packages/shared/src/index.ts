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
  /** The relevance judge's score, 0-10, when it judged this excerpt. */
  relevance?: number | null;
  /** The judge's one-line reason. */
  relevance_reason?: string | null;
  /** How much its source counts: 3 primary, 2 secondary, 1 derived. */
  weight?: number | null;
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
  /** "image" draws a picture of the question; "check" fact-checks `answer` against `chunks`. */
  task?: "answer" | "image" | "review" | "check" | "gaps" | "challenge";
  /** For task "check": the answer to fact-check, and the excerpts it was given. */
  answer?: string;
  chunks?: CodeChunk[];
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
  /** Deep research: true always, false never; unset only for questions that look complex. */
  research?: boolean;
  /** False answers afresh instead of reusing the answer to the same question. */
  cache?: boolean;
  /** Plan several knowledge-base searches (keywords, a hypothetical answer…); default true. */
  plan_queries?: boolean;
  /** Judge each excerpt's relevance (0-10) and rerank; default true. */
  rerank?: boolean;
  /** Then rank the kept excerpts together, best first, in one call; default true. */
  rank_passages?: boolean;
  /** Judged excerpts scoring below this are left out; unset is the server's (4). */
  rerank_cutoff?: number;
}

/** The uncertainty budget an answer from the sources spent (of 3). */
export interface Uncertainty {
  /** The higher of the model's own count and what the server saw. */
  spent: number;
  budget: number;
  model?: number | null;
  /** What the server saw spending units, such as "a single source". */
  reasons: string[];
  /** Over budget: the answer was withheld. */
  exceeded: boolean;
}

export type AtlasMode = "ASK" | "EXPLORE" | "COMPARE" | "BUILD" | "AUDIT" | "AGENT" | "TEACH";

/** What the user is trying to achieve, reconstructed before answering. */
export interface Intent {
  /** The question as typed. */
  literal?: string | null;
  /** What they are trying to do. */
  goal?: string | null;
  /** What they would consider a bad answer. */
  constraints?: string | null;
  /** One line, when the answer addresses the goal rather than the literal question. */
  reframe?: string | null;
}

export type EpistemicState =
  | "known"
  | "inferred"
  | "partial"
  | "absent"
  | "conflicted"
  | "general"
  | "web";

/** How far an answer from the knowledge base can be trusted. */
export interface Confidence {
  level: "high" | "medium" | "low";
  /** How relevant the excerpts were, 0-1. */
  relevance: number;
  /** The share of the answer's sentences cited. */
  coverage: number;
  verified: number;
  citations: number;
  reason: string;
}

/** One tool call of deep research. */
export interface ResearchStep {
  step: number;
  tool: "search" | "read" | "note";
  /** The query, the span read, or the note. */
  input: string;
  /** What came of it, briefly ("5 results", "read"). */
  result: string;
}

/** The self-challenge of an answer: the strongest objection from its context, and the
 * outcome (task "challenge"). */
export interface SelfChallenge {
  objection: string;
  /** True if the objection held and the answer was revised. */
  valid: boolean;
  /** Why the objection does not hold, in one line. */
  reason: string;
  /** The answer before revision, when it was revised. */
  original_answer?: string | null;
  /** "Service · model". */
  challenged_by: string;
}

/** What the knowledge base covers and lacks for a question (task "gaps"). */
export interface GapReport {
  /** Markdown: what it covers well, what is missing, the best source to add. */
  report: string;
  /** The link to the source it suggests adding, when it gave one. */
  suggestion_url?: string | null;
  /** "Service · model". */
  found_by: string;
}

/** The fact-checker's report on an answer, against the excerpts it was given. */
export interface FactCheck {
  faithful: boolean;
  /** Sentences no passage supports. */
  unsupported: string[];
  /** Citations that match no source ID and line range given. */
  citation_errors: string[];
  verdict: string;
  /** "Service · model". */
  checked_by: string;
}

/** What the relevance judge did with the excerpts. */
export interface Reranking {
  /** Excerpts the search found. */
  candidates: number;
  /** Those the judge scored in time. */
  judged: number;
  /** Those given to the model. */
  kept: number;
  cutoff: number;
  /** True if the listwise ranker then ordered the kept excerpts. */
  ranked?: boolean;
  /** The ranker's reason for its first pick. */
  top_pick?: string | null;
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
  /** What the relevance judge did with the excerpts. */
  reranking?: Reranking | null;
  /** The fact-checker's report, when asked for (task "check"). */
  fact_check?: FactCheck | null;
  /** Deep research: each tool call the agent made, in order. */
  research_steps?: ResearchStep[];
  /** Where the answer stands: for a question about the sources, as the model classified
   * it (known, inferred, partial, absent, conflicted); otherwise general or web. */
  epistemic?: EpistemicState | null;
  /** What the user is trying to achieve, reconstructed before answering. */
  intent?: Intent | null;
  /** True if answered only from the knowledge base. */
  grounded?: boolean;
  /** The Atlas mode that answered: ASK, EXPLORE, COMPARE, BUILD, AUDIT, AGENT or TEACH. */
  mode?: AtlasMode | null;
  /** From the request to the answer. */
  latency_ms?: number | null;
  /** [confidence: X] [sources: N] [latency: Xms], for every answer. */
  footer?: string | null;
  /** What was redacted from the answer (kinds, never values): "API key", "email", "link"… */
  redacted?: string[];
  /** For an answer from the sources: the uncertainty budget spent, of 3. */
  uncertainty?: Uncertainty | null;
  /** The highest weight among the excerpts: secondary or derived means the answer rests
   * on secondary sources only. */
  source_basis?: "primary" | "secondary" | "derived" | null;
  /** For an answer from the knowledge base: high, medium or low, and why. */
  confidence?: Confidence | null;
  /** Seconds per stage: plan, search, judge, research, answer. */
  timings?: Record<string, number>;
  /** True if this is the stored answer to the same question, asked before. */
  cached?: boolean;
  /** Something to know about how it was answered, such as a search fallback. */
  notice?: string | null;
  /** The self-challenge and its outcome, once done. */
  challenge?: SelfChallenge | null;
  /** True for an answer from the sources: the page asks for its self-challenge. */
  challenge_pending?: boolean;
  /** What the knowledge base lacks for the question, when asked for (task "gaps"). */
  gaps?: GapReport | null;
  /** True for a strict answer: the page asks for its fact-check once it is shown. */
  fact_check_pending?: boolean;
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

/** What the answer log says about the knowledge base: for one chat or for everything. */
export interface KnowledgeHealth {
  scope: "chat" | "all";
  answers: number;
  /** The top 3 recurring gaps: topics answered partly or not at all. */
  gaps: { question: string; times: number }[];
  /** The top 3 sources to add (a suggested link) or refresh (a source's title). */
  sources: { action: "add" | "refresh"; source: string; why?: string | null }[];
  /** One question the knowledge base answered surprisingly well. */
  well_answered?: { question: string; score: number } | null;
}

/** A model's health check of the whole knowledge base. */
export interface KnowledgeAudit {
  /** Markdown table: each source's coverage, staleness, redundancy and gaps. */
  report: string;
  /** "Service · model". */
  model: string;
  sources: number;
  created_at: string;
}

export interface HealthReport {
  summary: HealthSummary;
  thresholds: HealthThresholds;
  dead_symbols: SymbolRef[];
  circular_dependencies: Cycles;
  long_functions: LongFunction[];
  high_fan_out_files: FanOut[];
  /** The newest health check of the knowledge base, if any. */
  knowledge_audit?: KnowledgeAudit | null;
  /** Recurring gaps and sources to add or refresh, from the answer log. */
  knowledge_health?: KnowledgeHealth | null;
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
  /** Unlocking admin also needs an authenticator code. */
  admin_mfa?: boolean;
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
  /** How much it counts: 3 primary, 2 secondary, 1 derived. */
  weight?: number;
  /** The admin's choice; unset is automatic. */
  weight_override?: number | null;
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
