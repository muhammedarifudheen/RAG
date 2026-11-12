"""the answer log names each query and answer, and keeps the served and shadow chunk orders

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_log", sa.Column("query_hash", sa.Text()))
    op.add_column("answer_log", sa.Column("answer_hash", sa.Text()))
    op.add_column("answer_log", sa.Column("ranking", postgresql.JSONB()))
    op.add_column("answer_log", sa.Column("feedback_at", sa.DateTime(timezone=True)))
    op.create_index("ix_answer_log_query_hash", "answer_log", ["query_hash"])
    op.create_index("ix_answer_log_answer_hash", "answer_log", ["answer_hash"])


def downgrade() -> None:
    op.drop_index("ix_answer_log_answer_hash", table_name="answer_log")
    op.drop_index("ix_answer_log_query_hash", table_name="answer_log")
    op.drop_column("answer_log", "feedback_at")
    op.drop_column("answer_log", "ranking")
    op.drop_column("answer_log", "answer_hash")
    op.drop_column("answer_log", "query_hash")
