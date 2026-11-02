from datetime import datetime

from sqlalchemy import REAL, BigInteger, DateTime, ForeignKey, Identity, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

KG_NODE_KINDS = ("concept", "entity", "person")
KG_EDGE_KINDS = (
    "references",
    "mentioned_in",
    "example_of",
    "contradicts",
    "supersedes",
    "derived_from",
)


class KgNode(Base):
    """A node beyond the code: a concept, an entity or a person."""

    __tablename__ = "kg_nodes"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)
    key: Mapped[str] = mapped_column(Text, unique=True)  # "concept:hmac"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KgEdge(Base):
    """An edge between any two nodes, by reference ("symbol:12", "concept:3"), with its
    confidence and evidence (the source, and the passage and lines it was found in)."""

    __tablename__ = "kg_edges"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    from_ref: Mapped[str] = mapped_column(Text, index=True)
    to_ref: Mapped[str] = mapped_column(Text, index=True)
    confidence: Mapped[float] = mapped_column(REAL, default=0.5)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    symbol_id: Mapped[int | None] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    start_line: Mapped[int | None] = mapped_column(Integer)
    end_line: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
