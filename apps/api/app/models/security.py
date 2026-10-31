from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Identity, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """An append-only record: answers (hashes and timings, no text), security events and
    admin actions. The database refuses to change or delete one (see migration 0009)."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    kind: Mapped[str] = mapped_column(Text)  # answer, injection, redaction, auth, admin
    actor: Mapped[str | None] = mapped_column(Text)  # a hash, never the identity
    detail: Mapped[dict] = mapped_column(JSONB, default=dict)


class ApiKey(Base):
    """A per-user key: read (ask, search, graph) or write (also shares and feedback). Only
    its hash is stored; the key itself is shown once, when it is made."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    key_hash: Mapped[str] = mapped_column(Text, unique=True)
    prefix: Mapped[str] = mapped_column(Text)  # the first characters, to recognise it
    scope: Mapped[str] = mapped_column(Text)  # "read" or "write"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_used: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
