from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Output size of sentence-transformers/all-MiniLM-L6-v2.
EMBEDDING_DIM = 384

# "section" is a passage of a document; the others are code.
SYMBOL_KINDS = ("module", "function", "class", "method", "section")
EDGE_KINDS = ("calls", "imports", "inherits")
SOURCE_KINDS = ("repo", "web", "wikipedia", "crawl", "upload")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Source(Base):
    """Something that was ingested: a repository, a page, an article, a crawl or a file."""

    __tablename__ = "sources"
    __table_args__ = (
        CheckConstraint(_in("kind", SOURCE_KINDS), name="ck_sources_kind"),
        UniqueConstraint("key", name="uq_sources_key"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(16))
    # Identifies the source across ingests, so adding it again replaces it.
    key: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class File(Base):
    __tablename__ = "files"
    __table_args__ = (
        # Unique across sources: a citation names a file by its path alone.
        UniqueConstraint("path", name="uq_files_path"),
        Index("ix_files_source_id", "source_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"))
    path: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(32))
    hash: Mapped[str] = mapped_column(String(64))
    loc: Mapped[int] = mapped_column(Integer)
    # Full source, used to cut snippets. Deferred so listing files stays cheap.
    content: Mapped[str] = mapped_column(Text, deferred=True)


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        CheckConstraint(_in("kind", SYMBOL_KINDS), name="ck_symbols_kind"),
        Index("ix_symbols_file_id", "file_id"),
        Index("ix_symbols_name", "name"),
        Index(
            "ix_symbols_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    file_id: Mapped[int] = mapped_column(ForeignKey("files.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(16))
    start_line: Mapped[int] = mapped_column(Integer)
    end_line: Mapped[int] = mapped_column(Integer)
    signature: Mapped[str | None] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIM))


class Edge(Base):
    __tablename__ = "edges"
    __table_args__ = (
        CheckConstraint(_in("kind", EDGE_KINDS), name="ck_edges_kind"),
        UniqueConstraint("from_symbol_id", "to_symbol_id", "kind", name="uq_edges_from_to_kind"),
        Index("ix_edges_to_symbol_id", "to_symbol_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    from_symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    to_symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
