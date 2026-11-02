"""add webhooks, and the answer text and citations to the answer log (for the JSONL export)

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-02 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "webhooks",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("secret", sa.Text(), nullable=False),
        sa.Column("events", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("last_status", sa.Integer()),
        sa.Column("last_at", sa.DateTime(timezone=True)),
    )
    op.add_column("answer_log", sa.Column("answer", sa.Text()))
    op.add_column(
        "answer_log",
        sa.Column("cited", postgresql.JSONB(), nullable=False, server_default="[]"),
    )
    op.add_column("answer_log", sa.Column("mode", sa.Text()))


def downgrade() -> None:
    op.drop_column("answer_log", "mode")
    op.drop_column("answer_log", "cited")
    op.drop_column("answer_log", "answer")
    op.drop_table("webhooks")
