"""Atlas as an MCP server (Model Context Protocol, Streamable HTTP transport): any
MCP-compatible agent can search the knowledge base, ask it and list its sources.

Add it to an MCP client as a remote server at `<server>/mcp`. Requests are JSON-RPC 2.0
POSTs; replies are JSON (the transport allows JSON in place of a stream). An Atlas API key
may be sent as `Authorization: Bearer atl_…` or X-Atlas-Key; reading needs none."""

import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.embedding import Embedder, get_embedder
from app.ratelimit import rate_limit
from app.routers.openai import _content, _events, bearer_key
from app.routers.search import ask
from app.routers.sources import list_sources
from app.schemas import AskRequest
from app.security import REFUSED, injection
from app.services.search import hybrid_search

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER = {"name": "atlas", "title": "Atlas knowledge base", "version": "1.0.0"}
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}

TOOLS = [
    {
        "name": "search_atlas",
        "title": "Search the knowledge base",
        "description": "Hybrid (keyword and semantic) search of the Atlas knowledge base: "
        "code symbols and document passages, each with its [path:start-end] citation "
        "and text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for."},
                "top_k": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5},
            },
            "required": ["query"],
        },
        "annotations": READ_ONLY,
    },
    {
        "name": "ask_atlas",
        "title": "Ask Atlas",
        "description": "A grounded answer from the knowledge base only, with inline "
        "[path:start-end] citations, its epistemic state (known, inferred, partial, "
        "absent, conflicted) and a confidence footer.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
        "annotations": READ_ONLY,
    },
    {
        "name": "list_sources",
        "title": "List the sources",
        "description": "What the knowledge base holds: each source's title, kind, address, "
        "weight (3 primary, 2 secondary, 1 derived) and size.",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": READ_ONLY,
    },
]


@router.get("/mcp", summary="MCP: no server-initiated stream", status_code=405)
def mcp_stream() -> Response:
    """This server sends no messages of its own, so there is no stream to open."""
    return Response(status_code=405, headers={"Allow": "POST"})


@router.post(
    "/mcp",
    summary="MCP (Streamable HTTP): JSON-RPC requests",
    dependencies=[
        Depends(bearer_key),
        Depends(rate_limit("ask", lambda: settings.ask_rate_limit_per_minute)),
    ],
)
async def mcp(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
):
    """`initialize`, `ping`, `tools/list` and `tools/call` (search_atlas, ask_atlas,
    list_sources). Notifications are acknowledged with 202. A batch is answered as one."""
    try:
        message = json.loads(await request.body())
    except ValueError:
        return JSONResponse(_failure(None, -32700, "Parse error"), status_code=400)
    batch = isinstance(message, list)
    replies = []
    for item in message if batch else [message]:
        reply = await _handle(item, request, db, embedder)
        if reply is not None:
            replies.append(reply)
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if batch else replies[0])


async def _handle(item, request: Request, db: Session, embedder: Embedder) -> dict | None:
    if not isinstance(item, dict) or item.get("jsonrpc") != "2.0" or "method" not in item:
        return _failure(
            item.get("id") if isinstance(item, dict) else None, -32600, "Invalid Request"
        )
    if "id" not in item:
        return None  # a notification, such as notifications/initialized
    ident, method, params = item["id"], item["method"], item.get("params") or {}
    if method == "initialize":
        asked = params.get("protocolVersion")
        return _success(
            ident,
            {
                "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER,
                "instructions": "Atlas answers only from its knowledge base. Cite what it "
                "returns as [path:start-end]; an 'absent' state means it does not know.",
            },
        )
    if method == "ping":
        return _success(ident, {})
    if method == "tools/list":
        return _success(ident, {"tools": TOOLS})
    if method == "tools/call":
        name, arguments = params.get("name"), params.get("arguments") or {}
        if name not in {t["name"] for t in TOOLS}:
            return _failure(ident, -32602, f"Unknown tool: {name}")
        try:
            text, data = await _call(name, arguments, request, db, embedder)
        except ValueError as error:
            return _success(ident, _tool_result(str(error), None, error=True))
        return _success(ident, _tool_result(text, data))
    return _failure(ident, -32601, f"Method not found: {method}")


async def _call(name: str, arguments: dict, request: Request, db: Session, embedder: Embedder):
    if name == "list_sources":
        sources = await run_in_threadpool(list_sources, db)
        data = [s.model_dump(mode="json", exclude={"created_at"}) for s in sources]
        lines = [
            f"- {s['title']} ({s['kind']}, weight {s['weight']}, {s['files']} files)"
            + (f" {s['url']}" if s.get("url") else "")
            for s in data
        ]
        return "\n".join(lines) or "The knowledge base is empty.", {"sources": data}
    if name == "search_atlas":
        query = str(arguments.get("query") or "").strip()
        if not query:
            raise ValueError("Give a query.")
        if injection(query):
            raise ValueError(REFUSED)
        top_k = max(1, min(int(arguments.get("top_k") or 5), 20))
        chunks, _ = await run_in_threadpool(
            hybrid_search, db, embedder, query, top_k, settings.snippet_max_lines
        )
        text = "\n\n".join(
            f"{c.citation} {c.kind} {c.name} (score {c.score:.2f})"
            + (f" [license: {c.license}, {c.source_url}]" if c.license else "")
            + f"\n{c.snippet}"
            for c in chunks
        )
        return text or "No results.", {"results": [c.model_dump() for c in chunks]}
    question = str(arguments.get("question") or "").strip()
    if not question:
        raise ValueError("Give a question.")
    headers = [(k, v) for k, v in request.scope["headers"] if k not in (b"accept", b"x-atlas-open")]
    headers.append((b"accept", b"text/event-stream"))
    inner = Request({**request.scope, "headers": headers}, request.receive)
    try:
        response = await run_in_threadpool(
            ask, AskRequest(question=question[:8000]), inner, db, embedder,
            mode="auto", fresh=False, chat=None,
        )  # fmt: skip
    except HTTPException as error:
        raise ValueError(str(error.detail)) from error
    done: dict = {}
    async for event, data in _events(response):
        if event == "done":
            done = data
        elif event == "error":
            raise ValueError(str(data.get("detail") or "The answer failed."))
    extras = ("epistemic", "confidence", "mode", "footer", "citations")
    return _content(done), {k: done.get(k) for k in extras}


def _tool_result(text: str, data: dict | None, error: bool = False) -> dict:
    result: dict = {"content": [{"type": "text", "text": text}], "isError": error}
    if data is not None:
        result["structuredContent"] = data
    return result


def _success(ident, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def _failure(ident, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "error": {"code": code, "message": message}}
