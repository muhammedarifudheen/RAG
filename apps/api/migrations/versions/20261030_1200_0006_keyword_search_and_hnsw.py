"""keyword search beside vector search, and a denser HNSW index

Each symbol gets a full-text vector (its name, signature, path and code, with
identifiers split at _ . - / so "format_name" also matches "format name"), kept up
to date by a trigger, so the worker needs no change; a GIN index serves it. The HNSW
index is rebuilt with m=16, ef_construction=200.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-30 12:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The words of a symbol, from its row and its file's lines (at most 300 of them).
_TEXT = """
    coalesce(s.name, '') || ' ' || coalesce(s.signature, '') || ' ' || f.path || ' ' ||
    array_to_string(
        (string_to_array(coalesce(f.content, ''), E'\\n'))[s.start_line : least(s.end_line, s.start_line + 299)],
        ' '
    )
"""


def upgrade() -> None:
    op.execute("ALTER TABLE symbols ADD COLUMN search tsvector")
    op.execute(
        f"""
        CREATE FUNCTION symbols_search_text(s symbols) RETURNS tsvector
        LANGUAGE sql STABLE AS $$
            SELECT to_tsvector('english', t || ' ' || regexp_replace(t, '[_./\\-]+', ' ', 'g'))
            FROM (SELECT {_TEXT} AS t FROM files f WHERE f.id = s.file_id) words
        $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION symbols_search_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search := symbols_search_text(NEW);
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER symbols_search_update BEFORE INSERT OR UPDATE OF
            name, signature, start_line, end_line, file_id
        ON symbols FOR EACH ROW EXECUTE FUNCTION symbols_search_update()
        """
    )
    op.execute("UPDATE symbols s SET search = symbols_search_text(s)")
    op.execute("CREATE INDEX ix_symbols_search ON symbols USING gin (search)")

    op.execute("DROP INDEX IF EXISTS ix_symbols_embedding_hnsw")
    op.execute(
        "CREATE INDEX ix_symbols_embedding_hnsw ON symbols USING hnsw "
        "(embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_symbols_embedding_hnsw")
    op.execute(
        "CREATE INDEX ix_symbols_embedding_hnsw ON symbols USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute("DROP INDEX IF EXISTS ix_symbols_search")
    op.execute("DROP TRIGGER IF EXISTS symbols_search_update ON symbols")
    op.execute("DROP FUNCTION IF EXISTS symbols_search_update()")
    op.execute("DROP FUNCTION IF EXISTS symbols_search_text(symbols)")
    op.execute("ALTER TABLE symbols DROP COLUMN IF EXISTS search")
