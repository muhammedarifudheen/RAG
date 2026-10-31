import json
import logging
import queue
import re
import shutil
import tempfile
import threading
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from worker.clone import parse_github_url
from worker.config import Settings as WorkerSettings
from worker.pipeline import IngestError, ingest_upload, ingest_url
from worker.sources import (
    MAX_UPLOAD_BYTES,
    UPLOAD_TYPES,
    SourceError,
    detect_kind,
    parse_wikipedia_url,
)

from app.admin import ADMIN_REQUIRED, require_signed_admin
from app.config import settings
from app.ratelimit import rate_limit
from app.schemas import IngestRequest

logger = logging.getLogger("atlas.api.ingest")

router = APIRouter(tags=["ingest"])

# Ingests load a model and write in bulk, so only one runs at a time.
_running = threading.Lock()

_STEP = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")
KEEP_ALIVE_SECONDS = 15.0

Event = tuple[str, dict]
Progress = Callable[[str], None]

SSE_RESPONSES = {
    200: {
        "description": "A Server-Sent Events stream of `progress` events, ending with "
        "one `done` or `error` event.",
        "content": {"text/event-stream": {}},
    },
    409: {"description": "Another ingest is running."},
    429: {"description": "Rate limit exceeded; see the Retry-After header."},
}


def _worker_settings() -> WorkerSettings:
    return WorkerSettings(database_url=settings.database_url)


def run_ingest(url: str, kind: str, max_pages: int, progress: Progress) -> dict[str, int]:
    """Runs the worker's pipeline for a link against the API's database."""
    result = ingest_url(
        url, settings=_worker_settings(), kind=kind, max_pages=max_pages, progress=progress
    )
    return {"files": result.files, "symbols": result.symbols, "edges": result.edges}


def run_upload(path: Path, filename: str, progress: Progress) -> dict[str, int]:
    """Runs the worker's pipeline for an uploaded file against the API's database."""
    result = ingest_upload(path, filename, settings=_worker_settings(), progress=progress)
    return {"files": result.files, "symbols": result.symbols, "edges": result.edges}


def _progress_event(message: str) -> Event:
    """`[2/5] Parsing` starts a step; any other line is detail for the current one."""
    match = _STEP.match(message)
    if match:
        return "progress", {"step": int(match[1]), "total": int(match[2]), "message": match[3]}
    return "progress", {"step": None, "total": None, "message": message.strip()}


def _work(
    job: Callable[[Progress], dict[str, int]],
    what: str,
    events: "queue.Queue[Event | None]",
    cleanup: Callable[[], None] | None,
) -> None:
    try:
        result = job(lambda message: events.put(_progress_event(message)))
        events.put(("done", result))
    except IngestError as error:
        events.put(("error", {"message": str(error)}))
    except Exception:
        logger.exception("Ingest of %s failed", what)
        events.put(("error", {"message": "Ingestion failed; see the server log."}))
    finally:
        if cleanup is not None:
            cleanup()
        _running.release()
        events.put(None)


def _stream(events: "queue.Queue[Event | None]") -> Iterator[str]:
    while True:
        try:
            event = events.get(timeout=KEEP_ALIVE_SECONDS)
        except queue.Empty:
            yield ": keep-alive\n\n"  # stops proxies closing an idle connection
            continue
        if event is None:
            return
        name, data = event
        yield f"event: {name}\ndata: {json.dumps(data)}\n\n"


def _start(
    job: Callable[[Progress], dict[str, int]],
    what: str,
    cleanup: Callable[[], None] | None = None,
) -> StreamingResponse:
    if not _running.acquire(blocking=False):
        if cleanup is not None:
            cleanup()
        raise HTTPException(409, "Another ingest is running; wait for it to finish.")
    events: queue.Queue[Event | None] = queue.Queue()
    threading.Thread(target=_work, args=(job, what, events, cleanup), daemon=True).start()
    return StreamingResponse(
        _stream(events),
        media_type="text/event-stream",
        # no-transform and X-Accel-Buffering keep proxies from buffering the stream.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


def _checked_kind(url: str, kind: str) -> str:
    """Resolves `auto` and rejects links that cannot be that kind of source."""
    if kind == "auto":
        kind = detect_kind(url)
    try:
        if kind == "repo":
            parse_github_url(url)
        elif kind == "wikipedia":
            parse_wikipedia_url(url)
        else:
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or not parts.hostname:
                raise ValueError("Expected a link starting with http:// or https://.")
    except (ValueError, SourceError) as error:
        raise HTTPException(422, str(error)) from error
    return kind


@router.post(
    "/ingest",
    summary="Add a source from a link",
    response_class=StreamingResponse,
    responses={
        **SSE_RESPONSES,
        **ADMIN_REQUIRED,
        422: {"description": "The link is not a usable source."},
    },
    dependencies=[
        Depends(require_signed_admin),
        Depends(rate_limit("ingest", lambda: settings.ingest_rate_limit_per_minute)),
    ],
)
def ingest(body: IngestRequest) -> StreamingResponse:
    """Adds a source to the knowledge base: a GitHub repository, a Wikipedia article, a
    web page, or (`kind: "crawl"`) up to `max_pages` pages of one site.

    Sources accumulate. Adding one that is already present replaces that source only.
    Progress is streamed as Server-Sent Events:

    - `progress`: `{"step": 2, "total": 5, "message": "Parsing source files"}` when a step
      starts; `step` is `null` for detail lines within the current step.
    - `done`: `{"files": 15, "symbols": 159, "edges": 180}`.
    - `error`: `{"message": "..."}`. Nothing is changed.

    Only public web addresses are fetched. The ingest keeps running if the client
    disconnects."""
    url = (body.url or body.repo_url or "").strip()
    if not url:
        raise HTTPException(422, "Give a link in `url`.")
    kind = _checked_kind(url, body.kind)
    return _start(lambda progress: run_ingest(url, kind, body.max_pages, progress), url)


@router.post(
    "/ingest/upload",
    summary="Add a source from an uploaded file",
    response_class=StreamingResponse,
    responses={
        **SSE_RESPONSES,
        **ADMIN_REQUIRED,
        413: {"description": "The file is too large."},
        422: {"description": "The file type is not supported."},
    },
    dependencies=[
        Depends(require_signed_admin),
        Depends(rate_limit("ingest", lambda: settings.ingest_rate_limit_per_minute)),
    ],
)
def ingest_file(file: UploadFile) -> StreamingResponse:
    """Adds a PDF, EPUB, text, Markdown or HTML file to the knowledge base. Uploading a
    file with the same name again replaces the earlier copy. Progress is streamed as
    for `POST /ingest`.

    PDFs need a text layer; scanned pages are not read."""
    filename = PurePosixPath((file.filename or "upload").replace("\\", "/")).name
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in UPLOAD_TYPES:
        raise HTTPException(
            422,
            f"{suffix or 'That file type'} is not supported. Upload one of: {', '.join(UPLOAD_TYPES)}.",
        )

    folder = Path(tempfile.mkdtemp(prefix="atlas-upload-"))
    path = folder / f"upload{suffix}"

    def cleanup() -> None:
        shutil.rmtree(folder, ignore_errors=True)

    size = 0
    with path.open("wb") as target:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                target.close()
                cleanup()
                raise HTTPException(
                    413, f"Files larger than {MAX_UPLOAD_BYTES // 1_000_000} MB are not accepted."
                )
            target.write(chunk)

    return _start(lambda progress: run_upload(path, filename, progress), filename, cleanup)
