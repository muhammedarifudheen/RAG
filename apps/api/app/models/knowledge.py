from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import REAL, BigInteger, DateTime, Identity, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.code_graph import EMBEDDING_DIM


class AnswerLog(Base):
    """One answer: the question, the sources it used and how well they answered it
    (known, inferred, partial, absent, conflicted). What the knowledge health is read from."""

    __tablename__ = "answer_log"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    chat_id: Mapped[str | None] = mapped_column(Text)
    question: Mapped[str] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    route: Mapped[str | None] = mapped_column(Text)
    # [{"title": source title, "file": path}] of the excerpts the answer was given.
    sources: Mapped[list] = mapped_column(JSONB, default=list)
    top_score: Mapped[float | None] = mapped_column(REAL)
    confidence: Mapped[str | None] = mapped_column(Text)
    verified: Mapped[int] = mapped_column(Integer, default=0)
    citations: Mapped[int] = mapped_column(Integer, default=0)
    # The source the gap finder suggested adding, when it ran for this question.
    suggestion: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class KnowledgeSignal(Base):
    """Something the knowledge base should get: a wanted source (a topic answered partly
    or not at all three times or more) or a source to refresh (outdated beside another)."""

    __tablename__ = "knowledge_signals"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)  # "wanted" or "refresh"
    subject: Mapped[str] = mapped_column(Text)  # the topic's question, or the source's title
    detail: Mapped[str | None] = mapped_column(Text)  # why, or what to add
    count: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))
