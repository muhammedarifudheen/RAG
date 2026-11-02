"""knowledge graph: concept, entity and person nodes, and typed edges with evidence

Nodes beyond the code graph (concepts, entities, people) and edges between any nodes,
named by reference ("symbol:12", "concept:3", "source:2", "file:7"): references,
mentioned_in, example_of, contradicts, supersedes, derived_from. Each edge carries its
confidence and its evidence: the source and the lines it was found in.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-04 09:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kg_nodes",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False, unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('concept', 'entity', 'person')", name="ck_kg_nodes_kind"),
    )
    op.create_table(
        "kg_edges",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("from_ref", sa.Text(), nullable=False),
        sa.Column("to_ref", sa.Text(), nullable=False),
        sa.Column("confidence", sa.REAL(), nullable=False, server_default="0.5"),
        sa.Column("source_id", sa.BigInteger(), sa.ForeignKey("sources.id", ondelete="CASCADE")),
        sa.Column("symbol_id", sa.BigInteger(), sa.ForeignKey("symbols.id", ondelete="CASCADE")),
        sa.Column("start_line", sa.Integer()),
        sa.Column("end_line", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('references', 'mentioned_in', 'example_of', 'contradicts', 'supersedes', "
            "'derived_from')",
            name="ck_kg_edges_kind",
        ),
        sa.UniqueConstraint("kind", "from_ref", "to_ref", name="uq_kg_edges_kind_from_to"),
    )
    op.create_index("ix_kg_edges_from_ref", "kg_edges", ["from_ref"])
    op.create_index("ix_kg_edges_to_ref", "kg_edges", ["to_ref"])
    # Concept and entity nodes no edge refers to any more are left; they are cheap and
    # come back with their source.


def downgrade() -> None:
    op.drop_index("ix_kg_edges_to_ref", "kg_edges")
    op.drop_index("ix_kg_edges_from_ref", "kg_edges")
    op.drop_table("kg_edges")
    op.drop_table("kg_nodes")
