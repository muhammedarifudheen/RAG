"""What the chat page needs besides /ask: reading attached files, and shared chats."""

import json
import secrets
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.orm import Session
from worker.sources import UPLOAD_TYPES, SourceError, load_upload

from app.config import settings
from app.db import get_db
from app.models import SharedChat as SharedChatRow
from app.ratelimit import rate_limit, require_write_key
from app.schemas import (
    MAX_SHARE_BYTES,
    AttachmentText,
    SharedChat,
    ShareRequest,
)

router = APIRouter(
    tags=["chat"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
    responses={429: {"description": "Rate limit exceeded; see the Retry-After header."}},
)

MAX_ATTACHMENT_BYTES = 20_000_000
# The text of one attached file is cut to this many characters.
ATTACHMENT_TEXT_LIMIT = 150_000


@router.post(
    "/attachments",
    response_model=AttachmentText,
    summary="Read a file's text, to attach to a question",
    responses={
        413: {"description": "The file is larger than 20 MB."},
        422: {"description": "The file has no readable text."},
    },
)
def read_attachment(file: UploadFile) -> AttachmentText:
    """Returns the text of a PDF, EPUB, HTML or any plain-text file (code, CSV, JSON,
    Markdown…), for the chat page to send with a question. Nothing is stored: unlike
    `POST /ingest/upload`, the file is not added to the knowledge base."""
    name = PurePosixPath((file.filename or "file").replace("\\", "/")).name or "file"
    suffix = PurePosixPath(name).suffix.lower()
    folder = Path(tempfile.mkdtemp(prefix="atlas-attachment-"))
    try:
        # load_upload reads by suffix; anything it does not know is read as plain text.
        path = folder / f"file{suffix if suffix in UPLOAD_TYPES else '.txt'}"
        size = 0
        with path.open("wb") as target:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise HTTPException(413, "Files larger than 20 MB cannot be attached.")
                target.write(chunk)
        try:
            loaded = load_upload(path, path.name)
        except SourceError as error:
            raise HTTPException(422, str(error)) from error
        text = "\n\n".join(document.text for document in loaded.documents).strip()
        if not text:
            raise HTTPException(422, "No readable text was found in that file.")
        return AttachmentText(
            name=name,
            text=text[:ATTACHMENT_TEXT_LIMIT],
            truncated=len(text) > ATTACHMENT_TEXT_LIMIT,
        )
    finally:
        shutil.rmtree(folder, ignore_errors=True)


@router.post(
    "/shares",
    response_model=SharedChat,
    status_code=201,
    summary="Share a chat by link",
    responses={413: {"description": "The chat is larger than 2 MB."}},
    dependencies=[Depends(require_write_key)],
)
def create_share(body: ShareRequest, db: Annotated[Session, Depends(get_db)]) -> SharedChat:
    """Stores a copy of a conversation and returns its id; anyone with the id can read
    it with `GET /shares/{id}`. Later changes to the chat are not shared."""
    if len(json.dumps(body.messages)) > MAX_SHARE_BYTES:
        raise HTTPException(413, "This chat is too large to share; images make it large.")
    row = SharedChatRow(id=secrets.token_urlsafe(9), title=body.title, messages=body.messages)
    db.add(row)
    db.commit()
    db.refresh(row)
    return SharedChat(id=row.id, title=row.title, messages=row.messages, created_at=row.created_at)


@router.get(
    "/shares/{share_id}",
    response_model=SharedChat,
    summary="Read a shared chat",
    responses={404: {"description": "No chat is shared under that id."}},
)
def get_share(share_id: str, db: Annotated[Session, Depends(get_db)]) -> SharedChat:
    row = db.get(SharedChatRow, share_id[:32])
    if row is None:
        raise HTTPException(404, "This shared chat does not exist, or the server has restarted.")
    return SharedChat(id=row.id, title=row.title, messages=row.messages, created_at=row.created_at)
