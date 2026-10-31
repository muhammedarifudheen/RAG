from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin import ADMIN_REQUIRED, key_hash, new_api_key, require_admin
from app.db import get_db
from app.models import ApiKey
from app.schemas import ApiKeyCreate, ApiKeyCreated, ApiKeyOut
from app.services.audit import record

router = APIRouter(tags=["keys"], responses=ADMIN_REQUIRED, dependencies=[Depends(require_admin)])


def _out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        name=row.name,
        prefix=row.prefix,
        scope=row.scope,
        created_at=row.created_at,
        last_used=row.last_used,
        revoked=row.revoked,
    )


@router.get("/keys", response_model=list[ApiKeyOut], summary="List the API keys")
def list_keys(db: Annotated[Session, Depends(get_db)]) -> list[ApiKeyOut]:
    """Every API key, newest first, without the keys themselves (only their start)."""
    return [_out(k) for k in db.scalars(select(ApiKey).order_by(ApiKey.id.desc()))]


@router.post("/keys", response_model=ApiKeyCreated, status_code=201, summary="Make an API key")
def create_key(body: ApiKeyCreate, db: Annotated[Session, Depends(get_db)]) -> ApiKeyCreated:
    """A new key, sent as `X-Atlas-Key`: `read` asks, searches and reads; `write` may also
    share chats. Each key is limited to 60 requests a minute. The key is shown only now."""
    key = new_api_key()
    row = ApiKey(name=body.name, key_hash=key_hash(key), prefix=key[:8], scope=body.scope)
    db.add(row)
    db.commit()
    db.refresh(row)
    record(db, "admin", None, {"action": "create key", "key": row.prefix, "scope": row.scope})
    return ApiKeyCreated(**_out(row).model_dump(), key=key)


@router.delete("/keys/{key_id}", status_code=204, summary="Revoke an API key")
def revoke_key(key_id: int, db: Annotated[Session, Depends(get_db)]) -> Response:
    row = db.get(ApiKey, key_id)
    if row is None:
        raise HTTPException(404, "No such key.")
    row.revoked = True
    db.commit()
    record(db, "admin", None, {"action": "revoke key", "key": row.prefix})
    return Response(status_code=204)
