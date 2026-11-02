from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Identity,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SourceVersion(Base):
    """One of the last three ingests of a source, as a compressed snapshot (its files,
    their symbols and embeddings, its edges), so it can be restored in one click."""

    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("source_key", "version", name="uq_source_versions_key_version"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_key: Mapped[str] = mapped_column(Text)
    version: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    source_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    files: Mapped[int] = mapped_column(Integer, default=0)
    symbols: Mapped[int] = mapped_column(Integer, default=0)
    snapshot: Mapped[bytes] = mapped_column(LargeBinary)


class HealthSnapshot(Base):
    """The knowledge base's overall health score at a moment, for its sparkline."""

    __tablename__ = "health_snapshots"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    score: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict] = mapped_column(JSONB, default=dict)
