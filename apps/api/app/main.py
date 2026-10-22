import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.middleware import log_requests
from app.routers import chat, files, graph, health, ingest, search, sources

DESCRIPTION = """\
Build a knowledge base from GitHub repositories, web pages, Wikipedia articles and
uploaded documents, then query it: semantic search, question answering with cited
sources, and for code, call graphs and a health report.

All endpoints except `/healthz` are rate limited per client IP and answer `429` with a
`Retry-After` header when the limit is exceeded. Every response carries an
`X-Request-ID` header that also appears in the server's request log.
"""

TAGS = [
    {"name": "ingest", "description": "Add, list and remove the sources in the knowledge base."},
    {"name": "files", "description": "Source text and symbols of ingested files."},
    {"name": "search", "description": "Vector search and retrieval-augmented answers."},
    {"name": "chat", "description": "Attached files and shared chats, for the chat page."},
    {"name": "graph", "description": "Call graph traversal."},
    {"name": "health", "description": "Static measures of the ingested code."},
    {"name": "ops", "description": "Operational endpoints."},
]


def _configure_logging() -> None:
    # Uvicorn only configures its own loggers, so ours needs a handler to be visible.
    logger = logging.getLogger("atlas")
    logger.setLevel(settings.log_level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        logger.addHandler(handler)


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(title="Atlas API", version="0.1.0", description=DESCRIPTION, openapi_tags=TAGS)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "Retry-After"],
    )
    app.middleware("http")(log_requests)

    @app.exception_handler(OperationalError)
    def database_unavailable(_request: Request, _error: OperationalError) -> JSONResponse:
        return JSONResponse({"detail": "The database is unavailable."}, status_code=503)

    app.include_router(ingest.router)
    app.include_router(sources.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    app.include_router(graph.router)
    app.include_router(files.router)
    app.include_router(health.router)
    return app


app = create_app()
