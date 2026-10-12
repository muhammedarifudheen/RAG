"""add sources, so several things can be ingested side by side

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-12 13:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('repo', 'web', 'wikipedia', 'crawl', 'upload')", name="ck_sources_kind"
        ),
        sa.UniqueConstraint("key", name="uq_sources_key"),
    )

    op.add_column("files", sa.Column("source_id", sa.BigInteger(), nullable=True))
    # Whatever was ingested before sources existed was a single repository.
    op.execute(
        """
        INSERT INTO sources (kind, key, title)
        SELECT 'repo', 'legacy', 'Previously ingested repository'
        WHERE EXISTS (SELECT 1 FROM files)
        """
    )
    op.execute("UPDATE files SET source_id = (SELECT id FROM sources WHERE key = 'legacy')")
    op.alter_column("files", "source_id", nullable=False)
    op.create_foreign_key(
        "files_source_id_fkey", "files", "sources", ["source_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_files_source_id", "files", ["source_id"])

    # Passages of documents are stored as symbols of kind "section".
    op.drop_constraint("ck_symbols_kind", "symbols", type_="check")
    op.create_check_constraint(
        "ck_symbols_kind",
        "symbols",
        "kind IN ('module', 'function', 'class', 'method', 'section')",
    )


def downgrade() -> None:
    op.execute("DELETE FROM symbols WHERE kind = 'section'")
    op.drop_constraint("ck_symbols_kind", "symbols", type_="check")
    op.create_check_constraint(
        "ck_symbols_kind", "symbols", "kind IN ('module', 'function', 'class', 'method')"
    )
    op.drop_index("ix_files_source_id", table_name="files")
    op.drop_constraint("files_source_id_fkey", "files", type_="foreignkey")
    op.drop_column("files", "source_id")
    op.drop_table("sources")
