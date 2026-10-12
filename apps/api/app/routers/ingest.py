import json
import logging
import queue
import re
import threading
from collections.abc import Callable, Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from worker.clone import parse_github_url
from worker.config import Settings as WorkerSettings
from worker.pipeline import IngestError, ingest_repo

from app.config import settings
from app.ratelimit import rate_limit
from app.schemas import IngestRequest

logger = logging.getLogger("atlas.api.ingest")

router = APIRouter(tags=["ingest"])

# An ingest replaces the whole database, so only one may run at a time.
_running = threading.Lock()

_STEP = re.compile(r"^\[(\d+)/(\d+)\]\s*(.*)$")
KEEP_ALIVE_SECONDS = 15.0

Event = tuple[str, dict]


def run_ingest(repo_url: str, progress: Callable[[str], None]) -> dict[str, int]:
    """Runs the worker's pipeline against the API's database."""
    result = ingest_repo(
        repo_url,
        settings=WorkerSettings(database_url=settings.database_url),
        progress=progress,
    )
    return {"files": result.files, "symbols": result.symbols, "edges": result.edges}


def _progress_event(message: str) -> Event:
    """`[2/5] Parsing` starts a step; any other line is detail for the current one."""
    match = _STEP.match(message)
    if match:
        return "progress", {"step": int(match[1]), "total": int(match[2]), "message": match[3]}
    return "progress", {"step": None, "total": None, "message": message.strip()}


def _work(repo_url: str, events: "queue.Queue[Event | None]") -> None:
    try:
        result = run_ingest(repo_url, lambda message: events.put(_progress_event(message)))
        events.put(("done", result))
    except IngestError as error:
        events.put(("error", {"message": str(error)}))
    except Exception:
        logger.exception("Ingest of %s failed", repo_url)
        events.put(("error", {"message": "Ingestion failed; see the server log."}))
    finally:
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


@router.post(
    "/ingest",
    summary="Ingest a GitHub repository",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "A Server-Sent Events stream of `progress` events, ending with "
            "one `done` or `error` event.",
            "content": {"text/event-stream": {}},
        },
        409: {"description": "Another ingest is running."},
        422: {"description": "Not an https://github.com/owner/repo URL."},
        429: {"description": "Rate limit exceeded; see the Retry-After header."},
    },
    dependencies=[Depends(rate_limit("ingest", lambda: settings.ingest_rate_limit_per_minute))],
)
def ingest(body: IngestRequest) -> StreamingResponse:
    """Clones the repository, extracts its code graph, embeds it and **replaces** whatever
    was ingested before. Progress is streamed as Server-Sent Events:

    - `progress`: `{"step": 2, "total": 5, "message": "Parsing source files"}` when a step
      starts; `step` is `null` for detail lines within the current step.
    - `done`: `{"files": 15, "symbols": 159, "edges": 180}`.
    - `error`: `{"message": "..."}`. The previous data is left untouched.

    The ingest keeps running if the client disconnects."""
    repo_url = body.repo_url.strip()
    try:
        parse_github_url(repo_url)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error

    if not _running.acquire(blocking=False):
        raise HTTPException(409, "Another ingest is running; wait for it to finish.")

    events: queue.Queue[Event | None] = queue.Queue()
    threading.Thread(target=_work, args=(repo_url, events), daemon=True).start()
    return StreamingResponse(
        _stream(events),
        media_type="text/event-stream",
        # no-transform and X-Accel-Buffering keep proxies from buffering the stream.
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )
