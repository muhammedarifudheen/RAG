"""ingest versions and duplicates, retrieval in the answer log, health history

- sources.version: which ingest of the source this is (1, 2, 3...).
- source_versions: a compressed snapshot of each of the last three ingests of a source,
  so any can be restored in one click.
- symbols.minhash and symbols.duplicate_of: near-duplicate passages across sources; the
  most trusted copy is canonical, the others point at it.
- answer_log.retrieved: what each answer retrieved, with its scores, for retrieval health.
- health_snapshots: the overall knowledge-base health score over time.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-03 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_table(
        "source_versions",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("source_updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("symbols", sa.Integer(), nullable=False, server_default="0"),
        # zlib-compressed JSON: files with their content and symbols (and embeddings), edges.
        sa.Column("snapshot", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("source_key", "version", name="uq_source_versions_key_version"),
    )
    op.add_column("symbols", sa.Column("minhash", sa.LargeBinary()))
    op.add_column(
        "symbols",
        sa.Column(
            "duplicate_of",
            sa.BigInteger(),
            sa.ForeignKey("symbols.id", ondelete="SET NULL"),
        ),
    )
    op.create_index("ix_symbols_duplicate_of", "symbols", ["duplicate_of"])
    op.add_column(
        "answer_log",
        sa.Column("retrieved", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.create_table(
        "health_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("metrics", postgresql.JSONB(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_table("health_snapshots")
    op.drop_column("answer_log", "retrieved")
    op.drop_index("ix_symbols_duplicate_of", "symbols")
    op.drop_column("symbols", "duplicate_of")
    op.drop_column("symbols", "minhash")
    op.drop_table("source_versions")
    op.drop_column("sources", "version")
