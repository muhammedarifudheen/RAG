from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Output size of sentence-transformers/all-MiniLM-L6-v2.
EMBEDDING_DIM = 384

SYMBOL_KINDS = ("module", "function", "class", "method")
EDGE_KINDS = ("calls", "imports", "inherits")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class File(Base):
    __tablename__ = "files"
    __table_args__ = (UniqueConstraint("path", name="uq_files_path"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
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
