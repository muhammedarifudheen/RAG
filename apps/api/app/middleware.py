import logging
import re
import time
import uuid

from fastapi import Request, Response

from app.security import private_client

logger = logging.getLogger("atlas.api.request")

_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


async def log_requests(request: Request, call_next) -> Response:
    """Logs one line per request and returns its ID in X-Request-ID.

    The query string and body are left out on purpose: they carry users' questions.
    """
    supplied = request.headers.get("x-request-id", "")
    # Only echo a caller's ID if it cannot inject content into the log line.
    request_id = supplied if _SAFE_REQUEST_ID.match(supplied) else uuid.uuid4().hex
    # An IP address is personal data: logged as a hash.
    client = private_client(request.client.host) if request.client else "-"
    started = time.perf_counter()

    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        logger.exception(
            "%s %s -> 500 in %.1fms client=%s request_id=%s",
            request.method, request.url.path, elapsed_ms, client, request_id,
        )  # fmt: skip
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s -> %d in %.1fms client=%s request_id=%s",
        request.method, request.url.path, response.status_code, elapsed_ms, client, request_id,
    )  # fmt: skip
    return response
