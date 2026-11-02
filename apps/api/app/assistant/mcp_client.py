"""External MCP servers' tools, for the AGENT mode's research (ATLAS_MCP_SERVERS).

Only tools a server marks read-only (`annotations.readOnlyHint: true`) are offered: the
agent researches, it never acts. What a tool returns is untrusted text, treated like any
retrieved excerpt: it can be cited, and instructions in it are never followed."""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx2

from app.config import settings
from app.schemas import CodeChunk

logger = logging.getLogger("atlas.mcp")

PROTOCOL_VERSION = "2025-06-18"
TIMEOUT_SECONDS = 15.0
TOOLS_FOR_SECONDS = 600.0
# What one result may add to the excerpts.
RESULT_CHARS = 6000
RESULT_LINES = 120


@dataclass
class ExternalTool:
    server: str
    name: str
    description: str
    schema: dict = field(default_factory=dict)

    @property
    def qualified(self) -> str:
        return f"{self.server}.{self.name}"

    def described(self) -> str:
        arguments = ", ".join((self.schema.get("properties") or {}).keys()) or "none"
        return f"- {self.qualified}: {self.description.strip()[:300]} (arguments: {arguments})"


class McpServer:
    """One remote MCP server over Streamable HTTP."""

    def __init__(self, name: str, url: str, token: str | None = None):
        self.name, self.url, self.token = name, url, token
        self.session: str | None = None
        self._tools: tuple[float, list[ExternalTool]] | None = None
        self._ids = 0
        self._lock = threading.Lock()

    def _post(self, method: str, params: dict | None = None, notify: bool = False) -> dict:
        with self._lock:
            self._ids += 1
            ident = self._ids
        payload: dict = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            payload["params"] = params
        if not notify:
            payload["id"] = ident
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        with httpx2.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(self.url, json=payload, headers=headers)
        if response.headers.get("mcp-session-id"):
            self.session = response.headers["mcp-session-id"]
        if notify:
            return {}
        response.raise_for_status()
        reply = _reply(response.text, response.headers.get("content-type", ""), ident)
        if "error" in reply:
            raise ValueError(str(reply["error"].get("message") or reply["error"]))
        return reply.get("result") or {}

    def _start(self) -> None:
        if self.session is not None:
            return
        self._post(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "atlas", "version": "1.0.0"},
            },
        )
        self.session = self.session or ""
        self._post("notifications/initialized", notify=True)

    def tools(self) -> list[ExternalTool]:
        """Its read-only tools, asked for once in ten minutes."""
        now = time.monotonic()
        if self._tools is not None and now - self._tools[0] < TOOLS_FOR_SECONDS:
            return self._tools[1]
        found: list[ExternalTool] = []
        try:
            self._start()
            for tool in self._post("tools/list", {}).get("tools") or []:
                if (tool.get("annotations") or {}).get("readOnlyHint") is not True:
                    continue
                found.append(
                    ExternalTool(
                        self.name,
                        str(tool.get("name")),
                        str(tool.get("description") or tool.get("title") or ""),
                        tool.get("inputSchema") or {},
                    )
                )
        except (httpx2.HTTPError, ValueError) as error:
            logger.info("MCP server %s: %s", self.name, error)
            self.session = None
        self._tools = (now, found)
        return found

    def call(self, tool: str, arguments: dict) -> str:
        try:
            self._start()
            result = self._post("tools/call", {"name": tool, "arguments": arguments})
        except (httpx2.HTTPError, ValueError) as error:
            self.session = None
            return f"The tool failed: {error}"
        text = "\n".join(
            str(part.get("text") or "")
            for part in result.get("content") or []
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
        if not text and result.get("structuredContent") is not None:
            text = json.dumps(result["structuredContent"], ensure_ascii=False)[:RESULT_CHARS]
        if result.get("isError"):
            return f"The tool failed: {text[:500]}"
        return text or "(no text)"


def _reply(body: str, content_type: str, ident: int) -> dict:
    """The JSON-RPC reply with `ident`: the body, or one of a stream's events."""
    if "text/event-stream" not in content_type:
        return json.loads(body)
    for block in body.split("\n\n"):
        data = "".join(line[5:].strip() for line in block.split("\n") if line.startswith("data:"))
        if not data:
            continue
        try:
            message = json.loads(data)
        except ValueError:
            continue
        if isinstance(message, dict) and message.get("id") == ident:
            return message
    raise ValueError("No reply in the stream.")


_servers: dict[str, McpServer] = {}


def servers() -> list[McpServer]:
    """The servers in ATLAS_MCP_SERVERS: `name=url` pairs or bare URLs, comma-separated."""
    found = []
    for entry in (settings.atlas_mcp_servers or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        name, _, url = entry.partition("=") if "=" in entry.split("://")[0] else ("", "", entry)
        url = url.strip()
        name = (name.strip() or urlsplit(url).hostname or "mcp").replace(".", "-")
        if url not in _servers:
            _servers[url] = McpServer(name, url, settings.atlas_mcp_token)
        found.append(_servers[url])
    return found


def external_tools() -> list[ExternalTool]:
    return [tool for server in servers() for tool in server.tools()]


def call_tool(qualified: str, arguments: dict) -> str | None:
    """Calls `server.tool`; None if there is no such read-only tool."""
    for server in servers():
        for tool in server.tools():
            if tool.qualified == qualified:
                return server.call(tool.name, arguments)
    return None


def result_chunk(qualified: str, text: str, call: int) -> CodeChunk:
    """A tool's result as an excerpt the answer can cite: [mcp/server/tool-N:1-n]."""
    lines = text[:RESULT_CHARS].split("\n")[:RESULT_LINES]
    path = f"mcp/{qualified.replace('.', '/', 1)}-{call}"
    digest = int(hashlib.sha256(path.encode()).hexdigest()[:8], 16)
    return CodeChunk(
        # Negative and outside the spans' range, so it never shares an id.
        symbol_id=-(10**15 + digest),
        name=qualified,
        kind="section",
        signature=None,
        file=path,
        language="text",
        start_line=1,
        end_line=len(lines),
        score=0.5,
        snippet="\n".join(lines),
        snippet_end_line=len(lines),
        truncated=len(text) > RESULT_CHARS,
        citation=f"[{path}:1-{len(lines)}]",
        weight=1,  # derived: another system's say-so, not a primary source
    )
