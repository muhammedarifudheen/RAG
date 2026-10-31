"""Who may do what. Reading is open. Admin actions need the admin password; with an
authenticator configured (ADMIN_TOTP_SECRET), unlocking also needs its 6-digit code and
gives a short-lived session whose key signs each request, and adding or removing sources
needs such a signed request. API keys (read or write) identify callers of the API."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import threading
import time
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header, HTTPException, Request

from app.config import settings

ADMIN_REQUIRED = {401: {"description": "This needs the admin password (see ADMIN_TOKEN)."}}

# A signed request must be this recent, and a session lasts this long.
SIGNATURE_WINDOW = 300
SESSION_SECONDS = 12 * 3600


async def require_admin(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Lets a request through if no admin token is configured, or if it carries it, or a
    signed admin session."""
    if not settings.admin_token or _password(authorization):
        return
    if _signed(request, await request.body()):
        return
    raise HTTPException(
        401,
        "Adding or removing sources needs the admin password.",
        headers={"WWW-Authenticate": "Bearer"},
    )


async def require_signed_admin(
    request: Request, authorization: Annotated[str | None, Header()] = None
) -> None:
    """Adding or removing sources. Without an authenticator configured, as require_admin.
    With one, a request signed with an MFA session's key, or the password from the server
    itself (its start-up seeding)."""
    if not settings.admin_token:
        return
    if not settings.admin_totp_secret:
        if _password(authorization):
            return
    else:
        local = request.client is not None and request.client.host in ("127.0.0.1", "::1")
        body = await request.body()
        if _signed(request, body) or (local and _password(authorization)):
            return
    raise HTTPException(
        401,
        "Adding or removing sources needs the admin password and authenticator code."
        if settings.admin_totp_secret
        else "Adding or removing sources needs the admin password.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _password(authorization: str | None) -> bool:
    supplied = (authorization or "").encode()
    expected = f"Bearer {settings.admin_token}".encode()
    # Constant-time, so response timing does not reveal how much of a guess was right.
    return hmac.compare_digest(supplied, expected)


# --- TOTP (RFC 6238): 6 digits, 30 seconds, SHA-1, one step either side -----------------


def totp(secret: str, at: float | None = None, step: int = 0) -> str:
    key = base64.b32decode(secret.upper().replace(" ", "") + "=" * (-len(secret) % 8))
    counter = int((time.time() if at is None else at) // 30) + step
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1_000_000
    return f"{code:06d}"


def totp_ok(code: str | None, at: float | None = None) -> bool:
    secret = settings.admin_totp_secret
    if not secret or not code:
        return False
    code = code.strip().replace(" ", "")
    return any(hmac.compare_digest(totp(secret, at, step), code) for step in (-1, 0, 1))


# --- Admin sessions and signed requests --------------------------------------------------


@dataclass
class Session:
    key: bytes
    expires: float


_sessions: dict[str, Session] = {}
_seen: dict[str, float] = {}  # signatures already used, against replays
_lock = threading.Lock()


def open_session() -> tuple[str, str, float]:
    """A new admin session: (its id, its signing key in hex, when it expires)."""
    session_id, key = secrets.token_urlsafe(18), secrets.token_bytes(32)
    expires = time.time() + SESSION_SECONDS
    with _lock:
        now = time.time()
        for sid in [s for s, v in _sessions.items() if v.expires < now]:
            del _sessions[sid]
        _sessions[session_id] = Session(key, expires)
    return session_id, key.hex(), expires


def signature(key: bytes, method: str, path: str, timestamp: str, body: bytes) -> str:
    message = f"{method.upper()}\n{path}\n{timestamp}\n{hashlib.sha256(body).hexdigest()}"
    return hmac.new(key, message.encode(), hashlib.sha256).hexdigest()


def _signed(request: Request, body: bytes = b"") -> bool:
    session_id = request.headers.get("x-atlas-session")
    stamp = request.headers.get("x-atlas-timestamp", "")
    supplied = request.headers.get("x-atlas-signature", "")
    if not session_id or not stamp.isdigit() or not supplied:
        return False
    now = time.time()
    if abs(now - int(stamp)) > SIGNATURE_WINDOW:
        return False
    with _lock:
        session = _sessions.get(session_id)
        if session is None or session.expires < now:
            return False
        expected = signature(session.key, request.method, request.url.path, stamp, body)
        if not hmac.compare_digest(expected, supplied) or supplied in _seen:
            return False
        _seen[supplied] = now
        for old in [s for s, at in _seen.items() if now - at > SIGNATURE_WINDOW]:
            del _seen[old]
    return True


# --- API keys ----------------------------------------------------------------------------


def new_api_key() -> str:
    return "atl_" + secrets.token_urlsafe(30).replace("-", "").replace("_", "")[:32]


def key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
