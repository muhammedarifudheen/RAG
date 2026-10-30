"""The knowledge base described for a model: each source, its size, age and sample files."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import File, Source, Symbol


def source_catalog(db: Session, sample_files: int = 8) -> str:
    """One block per source, newest first: id, title, kind, address, when it was added, how
    many files and passages, and some of its file paths. Empty if nothing is ingested."""
    files = select(File.source_id, func.count().label("files")).group_by(File.source_id).subquery()
    symbols = (
        select(File.source_id, func.count().label("symbols"))
        .join(Symbol, Symbol.file_id == File.id)
        .group_by(File.source_id)
        .subquery()
    )
    rows = db.execute(
        select(Source, func.coalesce(files.c.files, 0), func.coalesce(symbols.c.symbols, 0))
        .outerjoin(files, files.c.source_id == Source.id)
        .outerjoin(symbols, symbols.c.source_id == Source.id)
        .order_by(Source.created_at.desc(), Source.id.desc())
    ).all()
    blocks = []
    for source, file_count, symbol_count in rows:
        paths = db.scalars(
            select(File.path)
            .where(File.source_id == source.id)
            .order_by(File.loc.desc())
            .limit(sample_files)
        ).all()
        where = f"; {source.url}" if source.url else ""
        blocks.append(
            f"- [{source.id}] {source.title} ({source.kind}{where}; added "
            f"{source.created_at:%Y-%m-%d}; {file_count} files, {symbol_count} passages)\n"
            f"  largest files: {', '.join(paths) or 'none'}"
        )
    return "\n".join(blocks)
