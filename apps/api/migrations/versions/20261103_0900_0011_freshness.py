"""add sources.source_updated_at: when the source itself last changed (freshness)

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-03 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_updated_at", sa.DateTime(timezone=True)))


def downgrade() -> None:
    op.drop_column("sources", "source_updated_at")
