"""add answer_log and knowledge_signals, for the knowledge base's health over time

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-31 14:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "answer_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("chat_id", sa.Text()),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("state", sa.Text()),
        sa.Column("route", sa.Text()),
        sa.Column("sources", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("top_score", sa.REAL()),
        sa.Column("confidence", sa.Text()),
        sa.Column("verified", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("citations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suggestion", sa.Text()),
        sa.Column("embedding", Vector(384)),
    )
    op.create_index("ix_answer_log_chat_id", "answer_log", ["chat_id"])
    op.create_table(
        "knowledge_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("subject", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text()),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("embedding", Vector(384)),
        sa.CheckConstraint("kind IN ('wanted', 'refresh')", name="ck_knowledge_signals_kind"),
    )


def downgrade() -> None:
    op.drop_table("knowledge_signals")
    op.drop_index("ix_answer_log_chat_id", "answer_log")
    op.drop_table("answer_log")
