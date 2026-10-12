"""create code graph tables

Revision ID: 0001
Revises:
Create Date: 2026-10-08 11:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "files",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("hash", sa.String(length=64), nullable=False),
        sa.Column("loc", sa.Integer(), nullable=False),
        sa.UniqueConstraint("path", name="uq_files_path"),
    )

    op.create_table(
        "symbols",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "file_id",
            sa.BigInteger(),
            sa.ForeignKey("files.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("embedding", Vector(384), nullable=True),
        sa.CheckConstraint(
            "kind IN ('module', 'function', 'class', 'method')", name="ck_symbols_kind"
        ),
    )
    op.create_index("ix_symbols_file_id", "symbols", ["file_id"])
    op.create_index("ix_symbols_name", "symbols", ["name"])
    op.create_index(
        "ix_symbols_embedding_hnsw",
        "symbols",
        ["embedding"],
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    op.create_table(
        "edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "from_symbol_id",
            sa.BigInteger(),
            sa.ForeignKey("symbols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "to_symbol_id",
            sa.BigInteger(),
            sa.ForeignKey("symbols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.CheckConstraint("kind IN ('calls', 'imports', 'inherits')", name="ck_edges_kind"),
        sa.UniqueConstraint(
            "from_symbol_id", "to_symbol_id", "kind", name="uq_edges_from_to_kind"
        ),
    )
    op.create_index("ix_edges_to_symbol_id", "edges", ["to_symbol_id"])


def downgrade() -> None:
    op.drop_table("edges")
    op.drop_table("symbols")
    op.drop_table("files")
    # The vector extension is left in place: docker-compose also creates it and
    # other objects may depend on it.
