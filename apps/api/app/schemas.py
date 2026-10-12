from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


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


class SearchResponse(BaseModel):
    query: str
    results: list[CodeChunk]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000, examples=["How are user names formatted?"])
    top_k: int = Field(default=8, ge=1, le=20, description="How many search results to give Claude.")


class Citation(BaseModel):
    ref: str = Field(description="The citation as written in the answer.", examples=["[pkg/models.py:20-21]"])
    file: str
    start_line: int
    end_line: int
    verified: bool = Field(
        description="True if the cited lines lie inside one of the chunks sent to the model."
    )


class AskResponse(BaseModel):
    question: str
    answer: str = Field(description="Claude's answer with inline [path:start-end] citations.")
    citations: list[Citation] = Field(description="Citations found in the answer, in order.")
    chunks: list[CodeChunk] = Field(description="The code given to the model, most similar first.")
    model: str = Field(description="The model that produced the answer.")
    complete: bool = Field(description="False if the answer was cut off at the token limit.")


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


class HealthReport(BaseModel):
    summary: HealthSummary = Field(description="Totals, before the per-list limit is applied.")
    thresholds: HealthThresholds
    dead_symbols: list[SymbolRef]
    circular_dependencies: Cycles
    long_functions: list[LongFunction]
    high_fan_out_files: list[FanOut]


class Liveness(BaseModel):
    status: Literal["ok"]
