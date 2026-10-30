from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class CodeChunk(BaseModel):
    """A symbol with the source code it spans."""

    symbol_id: int
    name: str = Field(examples=["User.label"])
    kind: Literal["module", "function", "class", "method", "section"]
    signature: str | None = Field(examples=["def label(self) -> str"])
    file: str = Field(examples=["pkg/models.py"])
    language: str = Field(examples=["python"])
    start_line: int = Field(description="First line of the symbol, 1-based.")
    end_line: int = Field(description="Last line of the symbol, inclusive.")
    score: float = Field(description="Cosine similarity to the query; higher is closer.")
    snippet: str = Field(description="Source from start_line to snippet_end_line.")
    snippet_end_line: int = Field(description="Last line included in the snippet.")
    truncated: bool = Field(description="True if the symbol is longer than the snippet.")
    citation: str = Field(
        description="Reference covering the snippet.", examples=["[pkg/models.py:16-17]"]
    )
    relevance: int | None = Field(
        default=None, description="The relevance judge's score, 0-10, when it judged this."
    )
    relevance_reason: str | None = Field(default=None, description="The judge's one-line reason.")


class SearchResponse(BaseModel):
    query: str
    results: list[CodeChunk]


# Limits on what can be attached to one question.
MAX_ATTACHMENT_TEXT = 400_000
MAX_IMAGE_DATA = 12_000_000


class ChatTurn(BaseModel):
    """One earlier message of the conversation, for follow-up questions."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=60000)


class Attachment(BaseModel):
    """A file the user attached to a question: its text, or an image."""

    name: str = Field(min_length=1, max_length=200, examples=["notes.pdf"])
    kind: Literal["text", "image"]
    text: str | None = Field(
        default=None, max_length=MAX_ATTACHMENT_TEXT, description="The file's text (kind text)."
    )
    mime: Literal["image/png", "image/jpeg", "image/webp", "image/gif"] | None = None
    data: str | None = Field(
        default=None,
        max_length=MAX_IMAGE_DATA,
        description="The image, base64-encoded (kind image).",
    )

    @model_validator(mode="after")
    def _has_content(self) -> "Attachment":
        if self.kind == "text" and self.text is None:
            raise ValueError("a text attachment needs its text")
        if self.kind == "image" and not (self.mime and self.data):
            raise ValueError("an image attachment needs mime and data")
        return self


class AskRequest(BaseModel):
    question: str = Field(
        min_length=1, max_length=32000, examples=["How are user names formatted?"]
    )
    top_k: int | None = Field(
        default=None,
        ge=1,
        le=20,
        description="How many excerpts to give the model: unset, 5 for the assistant "
        "(after hybrid search and the relevance judge) and 8 for a plain question.",
    )
    history: list[ChatTurn] = Field(
        default=[],
        max_length=40,
        description="Earlier messages, oldest first. Given, or with `Accept: text/event-stream`, "
        "the question goes to the assistant, which also answers from general knowledge and "
        "the web and suggests follow-up questions.",
    )
    # The assistant only; any of these also sends the question to it.
    attachments: list[Attachment] = Field(
        default=[], max_length=10, description="Files to answer from, for this question."
    )
    style: Literal["balanced", "concise", "detailed"] = Field(
        default="balanced", description="How long and detailed the answer should be."
    )
    temperature: float | None = Field(
        default=None, ge=0, le=2, description="Sampling temperature; unset is each model's default."
    )
    instructions: str = Field(
        default="",
        max_length=4000,
        description="The user's standing instructions to the assistant.",
    )
    # Models and the council.
    services: list[str] = Field(
        default=[],
        max_length=20,
        description="Only these AI services answer (gemini, groq, openrouter, nvidia, …); "
        "empty is every configured one.",
    )
    council_size: int | None = Field(
        default=None, ge=1, le=12, description="Agents answering in parallel; 1 is one model."
    )
    merger: str | None = Field(
        default=None,
        max_length=40,
        description="The service that merges the drafts, if it answered.",
    )
    # Retrieval.
    use_sources: bool = Field(default=True, description="Search the knowledge base.")
    min_score: float | None = Field(
        default=None, ge=0, le=1, description="Excerpts less similar than this are left out."
    )
    web_search: bool = Field(default=True, description="Search the web before answering.")
    plan_queries: bool = Field(
        default=True,
        description="Have a fast model plan several knowledge-base searches (the question, its "
        "keywords, a hypothetical answer, a variant) and fuse their results.",
    )
    rerank: bool = Field(
        default=True,
        description="Have fast models judge each candidate excerpt's relevance (0-10), then "
        "order the excerpts by that score and leave out those under `rerank_cutoff`.",
    )
    rank_passages: bool = Field(
        default=True,
        description="After the judge, one call to a fast model ranks the kept excerpts "
        "best-to-worst by how directly they answer, and they are given in that order.",
    )
    rerank_cutoff: int | None = Field(
        default=None, ge=0, le=10, description="Excerpts the judge scores below this are left out."
    )
    cache: bool = Field(
        default=True,
        description="Reuse the answer to the same question asked within a day (not for "
        "current events or answers from the web); false always answers afresh.",
    )
    research: bool | None = Field(
        default=None,
        description="Deep research: a model searches the knowledge base, reads spans and "
        "takes notes (up to 6 tool calls) before the answer is written. Unset: only for "
        "questions that look complex; false: never.",
    )
    strict: bool = Field(
        default=False,
        description="Strict sources only: answer from the knowledge base (and attached files) "
        "alone, citing every sentence of fact, flagging conflicts and saying what is missing. "
        "No web search, no general knowledge.",
    )
    # Generation.
    max_tokens: int | None = Field(
        default=None, ge=64, le=16000, description="The longest answer, in tokens."
    )
    format: Literal["markdown", "plain", "json"] = Field(
        default="markdown", description="How the answer is written."
    )
    # Transparency.
    include_drafts: bool = Field(
        default=False, description="Return each council agent's own draft with the answer."
    )
    task: Literal["answer", "image", "review", "check", "gaps"] = Field(
        default="answer",
        description="`image` draws a picture of the question; `review` runs the code analyser "
        "on the attached code, code in the question, or a GitHub link, and the agents review "
        "what it finds; `check` fact-checks `answer` against `chunks` (no new answer); "
        "`gaps` reports what the knowledge base covers and lacks for the question.",
    )
    # task: check
    answer: str | None = Field(
        default=None, max_length=60000, description="For `check`: the answer to fact-check."
    )
    chunks: list[CodeChunk] = Field(
        default=[], max_length=20, description="For `check`: the excerpts the answer was given."
    )

    @model_validator(mode="after")
    def _attachments_fit(self) -> "AskRequest":
        text = sum(len(a.text or "") for a in self.attachments)
        images = sum(len(a.data or "") for a in self.attachments)
        if text > MAX_ATTACHMENT_TEXT:
            raise ValueError(f"attached text is limited to {MAX_ATTACHMENT_TEXT} characters in all")
        if images > MAX_IMAGE_DATA:
            raise ValueError("attached images are too large in all")
        return self

    @property
    def for_assistant(self) -> bool:
        """True if anything only the assistant handles was asked for."""
        return bool(
            self.history
            or self.attachments
            or self.style != "balanced"
            or self.temperature is not None
            or self.instructions.strip()
            or self.task != "answer"
            or self.services
            or self.council_size is not None
            or self.merger
            or not self.use_sources
            or self.min_score is not None
            or not self.web_search
            or not self.plan_queries
            or not self.rerank
            or not self.rank_passages
            or self.rerank_cutoff is not None
            or self.strict
            or self.research is not None
            or not self.cache
            or self.max_tokens is not None
            or self.format != "markdown"
            or self.include_drafts
        )


class AttachmentText(BaseModel):
    """A document's text, read from an uploaded file for attaching to a question."""

    name: str
    kind: Literal["text"] = "text"
    text: str
    truncated: bool = Field(description="True if the text was cut to the size limit.")


class Citation(BaseModel):
    ref: str = Field(
        description="The citation as written in the answer.", examples=["[pkg/models.py:20-21]"]
    )
    file: str
    start_line: int
    end_line: int
    verified: bool = Field(
        description="True if the cited lines lie inside one of the chunks sent to the model."
    )


class WebSource(BaseModel):
    title: str
    url: str


class Reranking(BaseModel):
    candidates: int = Field(description="Excerpts the search found.")
    judged: int = Field(description="Those the relevance judge scored in time.")
    kept: int = Field(description="Those given to the model.")
    cutoff: int = Field(description="Judged excerpts scoring below this were left out.")
    ranked: bool = Field(
        default=False, description="True if the listwise ranker then ordered the kept excerpts."
    )
    top_pick: str | None = Field(default=None, description="The ranker's reason for its first.")


class ResearchStep(BaseModel):
    step: int
    tool: Literal["search", "read", "note"]
    input: str = Field(description="The query, the span read, or the note.")
    result: str = Field(description='What came of it, briefly ("5 results", "read").')


class AgentDraft(BaseModel):
    agent: str = Field(description='"Service · model".')
    seconds: float
    answer: str


class CodeFinding(BaseModel):
    tool: str = Field(description="ruff, secrets, patterns or complexity.")
    rule: str
    severity: Literal["high", "medium", "low"]
    path: str
    line: int
    message: str


class FunctionMetricOut(BaseModel):
    path: str
    name: str
    start_line: int
    end_line: int
    complexity: int = Field(description="Cyclomatic: 1 + decision points.")
    nesting: int = Field(description="The deepest block nesting inside it.")


class FileRiskOut(BaseModel):
    path: str
    lines: int
    findings: int
    complexity: int = Field(description="Its most complex function's complexity.")
    imported_by: int
    risk: float


class ImportCount(BaseModel):
    path: str
    imported_by: int


class CodeAnalysis(BaseModel):
    """What the code analyser found, before any AI looked at it."""

    repo: str | None = Field(default=None, description="The GitHub repository analysed.")
    commit: str | None = None
    files: int
    lines: int
    code_lines: int
    languages: dict[str, int] = Field(description="Lines per language.")
    score: int = Field(description="0-100: findings per thousand lines of code, weighted.")
    grade: str
    counts: dict[str, int] = Field(description="Findings by severity.")
    findings: list[CodeFinding] = Field(description="Most severe first; at most 300.")
    functions: list[FunctionMetricOut] = Field(description="The most complex functions.")
    test_files: int | None = None
    cycles: list[list[str]] = Field(default=[], description="Groups of files importing each other.")
    most_imported: list[ImportCount] = []
    riskiest: list[FileRiskOut] = []
    seconds: float | None = None


class GeneratedImage(BaseModel):
    url: str = Field(description="Where the picture is drawn; the browser loads it from there.")
    prompt: str = Field(description="What was asked of the image model.")
    service: str | None = Field(default=None, description="The service that drew it.")


class FactCheck(BaseModel):
    faithful: bool = Field(description="True if every claim is supported and cited correctly.")
    unsupported: list[str] = Field(default=[], description="Sentences no passage supports.")
    citation_errors: list[str] = Field(
        default=[], description="Citations that match no source ID and line range given."
    )
    verdict: str = Field(default="", description="The checker's one-line verdict.")
    checked_by: str = Field(default="", description='"Service · model".')


class GapReport(BaseModel):
    report: str = Field(
        description="Markdown: what the knowledge base covers, what it lacks, what to add."
    )
    suggestion_url: str | None = Field(
        default=None, description="The link to the source it suggests adding, if it gave one."
    )
    found_by: str = Field(default="", description='"Service · model".')


class Confidence(BaseModel):
    level: Literal["high", "medium", "low"]
    relevance: float = Field(description="How relevant the excerpts were, 0-1.")
    coverage: float = Field(description="The share of the answer's sentences cited.")
    verified: int = Field(description="Citations that point at lines the model was shown.")
    citations: int
    reason: str


class AskResponse(BaseModel):
    question: str
    answer: str = Field(description="Claude's answer with inline [path:start-end] citations.")
    citations: list[Citation] = Field(description="Citations found in the answer, in order.")
    chunks: list[CodeChunk] = Field(description="The code given to the model, most similar first.")
    model: str = Field(description="The model that produced the answer.")
    complete: bool = Field(description="False if the answer was cut off at the token limit.")
    # Set by the assistant only.
    provider: str | None = Field(default=None, description="The service that answered.")
    route: str | None = Field(
        default=None, description="The question type the assistant routed by.", examples=["code"]
    )
    suggestions: list[str] = Field(default=[], description="Follow-up questions to offer.")
    web_sources: list[WebSource] = Field(default=[], description="Web pages a search found.")
    images: list[GeneratedImage] = Field(default=[], description="Pictures drawn for the answer.")
    agents: list[str] = Field(
        default=[], description="The council's agents whose drafts were merged into the answer."
    )
    analysis: CodeAnalysis | None = Field(
        default=None, description="For a code review: what the code analyser found."
    )
    drafts: list[AgentDraft] = Field(
        default=[], description="Each council agent's own draft, when include_drafts was set."
    )
    search_queries: list[str] = Field(
        default=[], description="The knowledge-base searches the query planner ran."
    )
    reranking: Reranking | None = Field(
        default=None, description="What the relevance judge did with the excerpts."
    )
    fact_check: FactCheck | None = Field(
        default=None, description="The fact-checker's report, for `task: check`."
    )
    confidence: Confidence | None = Field(
        default=None,
        description="For an answer from the knowledge base: high, medium or low, from the "
        "excerpts' relevance and how much of the answer is cited to lines that check out.",
    )
    timings: dict[str, float] = Field(
        default={}, description="Seconds per stage: plan, search, judge, research, answer."
    )
    cached: bool = Field(
        default=False, description="True if this is a stored answer to the same question."
    )
    notice: str | None = Field(
        default=None, description="Something the user should know, such as a fallback."
    )
    research_steps: list[ResearchStep] = Field(
        default=[], description="Deep research: each tool call the agent made, in order."
    )
    gaps: GapReport | None = Field(
        default=None, description="For `task: gaps`: what the knowledge base lacks."
    )
    fact_check_pending: bool = Field(
        default=False,
        description="True for a strict answer: check it with `task: check` (the page does).",
    )


class SymbolRef(BaseModel):
    id: int
    name: str
    kind: str
    file: str
    start_line: int
    end_line: int


class GraphNode(SymbolRef):
    depth: int = Field(description="Hops from the requested file; 0 for its own symbols.")


class GraphEdge(BaseModel):
    source: int = Field(description="Symbol id of the caller.")
    target: int = Field(description="Symbol id of the callee.")


class GraphResponse(BaseModel):
    file: str
    hops: int
    direction: Literal["both", "callers", "callees"]
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    truncated: bool = Field(description="True if the node limit was reached before all hops.")


class FileNode(BaseModel):
    id: int
    path: str
    language: str
    loc: int
    symbols: int = Field(description="Number of symbols defined in the file.")
    in_cycle: bool = Field(description="True if the file is part of a circular dependency.")


class FileEdge(BaseModel):
    source: int = Field(description="Id of the file that depends on the target.")
    target: int
    imports: int = Field(description="Number of import edges from source to target.")
    calls: int
    inherits: int
    in_cycle: bool = Field(description="True if both files are in the same circular dependency.")


class FileGraph(BaseModel):
    nodes: list[FileNode]
    edges: list[FileEdge]
    cycles: list[list[int]] = Field(description="Groups of file ids that depend on each other.")


class FileSymbol(BaseModel):
    id: int
    name: str
    kind: str
    start_line: int
    end_line: int
    signature: str | None


class FileDetail(BaseModel):
    path: str
    language: str
    loc: int
    content: str
    symbols: list[FileSymbol]


class IngestRequest(BaseModel):
    url: str | None = Field(
        default=None,
        description="A GitHub repository, a Wikipedia article or any public web page.",
        examples=["https://en.wikipedia.org/wiki/Alan_Turing"],
    )
    repo_url: str | None = Field(default=None, description="Older name for `url`; still accepted.")
    kind: Literal["auto", "repo", "web", "wikipedia", "crawl"] = Field(
        default="auto",
        description="`auto` picks repo, wikipedia or web from the address. `crawl` follows "
        "links on the same site.",
    )
    max_pages: int = Field(default=20, ge=1, le=100, description="Page limit for `crawl`.")


class SiteConfig(BaseModel):
    admin_required: bool = Field(
        description="Adding and removing sources needs the admin password."
    )
    chat_configured: bool = Field(description="A model provider key is set, so /ask can answer.")


class SourceItem(BaseModel):
    id: int
    kind: Literal["repo", "web", "wikipedia", "crawl", "upload"]
    title: str
    url: str | None
    created_at: datetime
    files: int
    symbols: int = Field(description="Symbols and passages that can be searched.")


class LongFunction(SymbolRef):
    loc: int


class FanOut(BaseModel):
    file: str
    fan_out: int = Field(description="Number of other files this file depends on.")
    depends_on: list[str]


class Cycles(BaseModel):
    files: list[list[str]] = Field(description="Groups of files that depend on each other.")
    calls: list[list[SymbolRef]] = Field(description="Groups of symbols that call each other.")


class HealthSummary(BaseModel):
    files: int
    symbols: int
    edges: int
    dead_symbols: int
    file_cycles: int
    call_cycles: int
    long_functions: int
    high_fan_out_files: int


class HealthThresholds(BaseModel):
    max_function_loc: int
    min_fan_out: int


class KnowledgeAuditOut(BaseModel):
    report: str = Field(
        description="Markdown table: each source's coverage, staleness, redundancy and gaps."
    )
    model: str = Field(description='"Service · model" that wrote it.')
    sources: int = Field(description="How many sources were audited.")
    created_at: datetime


class HealthReport(BaseModel):
    summary: HealthSummary = Field(description="Totals, before the per-list limit is applied.")
    thresholds: HealthThresholds
    dead_symbols: list[SymbolRef]
    circular_dependencies: Cycles
    long_functions: list[LongFunction]
    high_fan_out_files: list[FanOut]
    knowledge_audit: KnowledgeAuditOut | None = Field(
        default=None, description="The newest health check of the knowledge base, if any."
    )


class Liveness(BaseModel):
    status: Literal["ok"]


# --- shared chats ---------------------------------------------------------------

MAX_SHARE_BYTES = 2_000_000


class ShareRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    messages: list[dict] = Field(
        min_length=1,
        max_length=200,
        description="The conversation as the web app keeps it; each has a `role`.",
    )

    @model_validator(mode="after")
    def _messages_have_roles(self) -> "ShareRequest":
        if any(m.get("role") not in ("user", "assistant", "error") for m in self.messages):
            raise ValueError("every message needs a role of user, assistant or error")
        return self


class SharedChat(BaseModel):
    id: str = Field(examples=["k3J9xQ2mZp"])
    title: str
    messages: list[dict]
    created_at: datetime
