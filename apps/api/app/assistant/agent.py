"""Deep research: a model searches the knowledge base, reads spans and keeps notes, a tool
call at a time, before the answer is written from what it found."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.schemas import CodeChunk

# The user's limit: stop after this many tool calls.
MAX_TOOL_CALLS = 6
# What a read returns at most, and what a search shows of each hit.
READ_LINES = 120
HIT_LINES = 8
HITS_SHOWN = 5

TOOLS = ("search", "read", "note", "mcp", "graph", "analytics", "health", "fetch", "done")

_RANGE = re.compile(r"(\d+)\s*(?:-|–|to|,)\s*(\d+)|(\d+)")
_CITED = re.compile(r"^\[?([^\[\]]+?):(\d+)(?:-(\d+))?\]?$")


@dataclass
class ResearchTools:
    """The knowledge base, for the agent: search it, and read a file's lines."""

    search: Callable[[str], list[CodeChunk]]
    read: Callable[[str, int, int], CodeChunk | None]
    # External MCP servers' read-only tools (ATLAS_MCP_SERVERS): one line describing each,
    # and call(qualified name, arguments) -> its text, or None for no such tool.
    external: Sequence[str] = field(default_factory=tuple)
    call: Callable[[str, dict], str | None] | None = None
    # The knowledge graph: graph(node, depth, edge kind or None) -> (its text, the excerpts
    # of the code and passages it reached, to cite).
    graph: Callable[[str, int, str | None], tuple[str, list[CodeChunk]]] | None = None
    # analytics.query(metric, window days, filter) -> text; health.check() -> text;
    # web.fetch(url) -> an excerpt (allowlisted hosts only) or why not.
    analytics: Callable[[str, int, str | None], str] | None = None
    health: Callable[[], str] | None = None
    fetch: Callable[[str], CodeChunk | str] | None = None


@dataclass
class Action:
    tool: str
    query: str = ""  # search
    path: str = ""  # read
    start: int = 0
    end: int = 0
    text: str = ""  # note
    name: str = ""  # mcp: the external tool, server.tool
    arguments: dict = field(default_factory=dict)

    def described(self) -> str:
        if self.tool == "mcp":
            return f"{self.name} {json.dumps(self.arguments)[:200]}"
        if self.tool in ("analytics", "fetch"):
            return (
                f"{self.name} {json.dumps(self.arguments)[:200]}" if self.arguments else self.name
            )
        if self.tool == "health":
            return "the knowledge base"
        if self.tool == "graph":
            edge = self.arguments.get("edge")
            return (
                f"{self.name} (depth {self.arguments.get('depth', 1)}{f', {edge}' if edge else ''})"
            )
        if self.tool == "search":
            return self.query
        if self.tool == "read":
            return f"{self.path}:{self.start}-{self.end}"
        return self.text


def parse_action(reply: str) -> Action | None:
    """The agent's tool call: {"tool": "search", "query": ...}, {"tool": "read",
    "source_id": ..., "line_range": "10-40"}, {"tool": "note", "text": ...} or
    {"tool": "done"}. None if the reply holds none."""
    for data in _objects(reply or ""):
        if not isinstance(data, dict):
            continue
        tool = str(data.get("tool") or data.get("action") or "").strip().lower()
        if tool in ("finish", "stop", "answer"):
            tool = "done"
        if tool not in TOOLS:
            continue
        if tool == "search":
            query = str(data.get("query") or data.get("input") or data.get("q") or "").strip()
            if query:
                return Action("search", query=query[:300])
        elif tool == "read":
            action = _read_action(data)
            if action:
                return action
        elif tool == "analytics":
            metric = str(data.get("metric") or "top_questions").strip()
            try:
                window = max(1, min(int(data.get("window") or 7), 365))
            except (TypeError, ValueError):
                window = 7
            found = str(data.get("filter") or "").strip() or None
            return Action(
                "analytics", name=metric[:40], arguments={"window": window, "filter": found}
            )
        elif tool == "health":
            return Action("health")
        elif tool == "fetch":
            url = str(data.get("url") or "").strip()
            if url.startswith(("http://", "https://")):
                return Action("fetch", name=url[:500])
        elif tool == "graph":
            node = str(data.get("node") or data.get("name") or data.get("id") or "").strip()
            if node:
                try:
                    depth = max(1, min(int(data.get("depth") or 1), 3))
                except (TypeError, ValueError):
                    depth = 1
                edge = str(data.get("edge") or data.get("edge_type") or "").strip() or None
                return Action("graph", name=node[:200], arguments={"depth": depth, "edge": edge})
        elif tool == "mcp":
            name = str(data.get("name") or data.get("tool_name") or "").strip()
            arguments = data.get("arguments") or data.get("args") or {}
            if name and isinstance(arguments, dict):
                return Action("mcp", name=name[:120], arguments=arguments)
        elif tool == "note":
            text = str(data.get("text") or data.get("note") or data.get("input") or "").strip()
            if text:
                return Action("note", text=text[:1500])
        else:
            return Action("done")
    return None


def _objects(text: str):
    """The JSON objects in a reply, nested ones (an mcp call's arguments) whole."""
    decoder = json.JSONDecoder()
    for start in (i for i, char in enumerate(text) if char == "{"):
        try:
            data, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        yield data


def _read_action(data: dict) -> Action | None:
    source = str(data.get("source_id") or data.get("path") or data.get("file") or "").strip()
    span = data.get("line_range") or data.get("lines") or ""
    cited = _CITED.match(source)
    if cited and not span:  # "[path:10-40]" as the source_id
        source, span = cited.group(1), f"{cited.group(2)}-{cited.group(3) or cited.group(2)}"
    if isinstance(span, list) and span:
        span = "-".join(str(v) for v in span[:2])
    found = _RANGE.search(str(span))
    if not source or not found:
        return None
    if found.group(3):
        start = end = int(found.group(3))
    else:
        start, end = int(found.group(1)), int(found.group(2))
    start, end = max(1, min(start, end)), max(start, end)
    return Action(
        "read", path=source.strip("[]` "), start=start, end=min(end, start + READ_LINES - 1)
    )


def hits_text(chunks: Sequence[CodeChunk]) -> str:
    """Search hits as the agent sees them: where each is and its first lines."""
    if not chunks:
        return "No results."
    shown = []
    for chunk in chunks[:HITS_SHOWN]:
        lines = chunk.snippet.split("\n")[:HIT_LINES]
        numbered = "\n".join(f"{chunk.start_line + i}| {line}" for i, line in enumerate(lines))
        shown.append(
            f"[{chunk.file}:{chunk.start_line}-{chunk.snippet_end_line}] {chunk.kind} "
            f"{chunk.name} (similarity {chunk.score:.2f})\n{numbered}"
        )
    return "\n\n".join(shown)


def read_text(chunk: CodeChunk | None) -> str:
    if chunk is None:
        return "Nothing there: use a source_id (path) and lines from the search results."
    lines = chunk.snippet.split("\n")
    numbered = "\n".join(f"{chunk.start_line + i}| {line}" for i, line in enumerate(lines))
    return f"[{chunk.file}:{chunk.start_line}-{chunk.snippet_end_line}]\n{numbered}"


def notes_block(notes: Sequence[str]) -> str:
    """The agent's notes, for the answer: synthesise from these and the excerpts."""
    listed = "\n".join(f"- {note}" for note in notes) or "- (no notes were saved)"
    return (
        f"<research_notes>\n{listed}\n</research_notes>\n"
        "These notes were gathered by searching and reading the knowledge base for this "
        "question. Synthesize the answer only from the notes and the excerpts, citing the "
        "excerpts' lines."
    )
