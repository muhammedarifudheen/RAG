"""add files.content

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-08 15:00:00

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Rows ingested before this migration get an empty string; re-ingest to fill them.
    op.add_column("files", sa.Column("content", sa.Text(), nullable=False, server_default=""))
    op.alter_column("files", "content", server_default=None)


def downgrade() -> None:
    op.drop_column("files", "content")
