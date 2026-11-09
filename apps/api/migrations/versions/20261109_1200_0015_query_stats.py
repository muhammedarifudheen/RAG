"""the answer log keeps each query's stage times and budget breaches

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09 12:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("answer_log", sa.Column("stats", postgresql.JSONB()))


def downgrade() -> None:
    op.drop_column("answer_log", "stats")
