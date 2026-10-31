"""add sources.weight, the admin's choice of how much a source counts

NULL is automatic (see app/services/weights.py); 3 primary, 2 secondary, 1 derived.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-31 10:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("weight", sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        "ck_sources_weight", "sources", "weight IS NULL OR weight BETWEEN 1 AND 3"
    )


def downgrade() -> None:
    op.drop_constraint("ck_sources_weight", "sources", type_="check")
    op.drop_column("sources", "weight")
