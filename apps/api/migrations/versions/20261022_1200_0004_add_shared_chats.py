"""add shared_chats, for conversations shared by link

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-22 12:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shared_chats",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("messages", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_table("shared_chats")
