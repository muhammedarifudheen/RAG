"""analytics: each answer's latency and the user's feedback; admin API keys

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-04 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_log", sa.Column("latency_ms", sa.Integer()))
    # 1 thumbs up, -1 thumbs down, with the reason given.
    op.add_column("answer_log", sa.Column("feedback", sa.SmallInteger()))
    op.add_column("answer_log", sa.Column("feedback_reason", sa.Text()))
    op.drop_constraint("ck_api_keys_scope", "api_keys", type_="check")
    op.create_check_constraint("ck_api_keys_scope", "api_keys", "scope IN ('read', 'write', 'admin')")


def downgrade() -> None:
    op.drop_constraint("ck_api_keys_scope", "api_keys", type_="check")
    op.create_check_constraint("ck_api_keys_scope", "api_keys", "scope IN ('read', 'write')")
    op.drop_column("answer_log", "feedback_reason")
    op.drop_column("answer_log", "feedback")
    op.drop_column("answer_log", "latency_ms")
