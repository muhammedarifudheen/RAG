"""The knowledge base described for a model: each source, its size, age and sample files."""

import re

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import File, Source, Symbol

# Identifiers in a question: dotted names, snake_case, camelCase, or name().
_IDENTIFIER = re.compile(
    r"\b[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+\b|\b[A-Za-z]\w*_\w+\b|\b[a-z]+[A-Z]\w*\b|\b\w+(?=\(\))"
)


def _names(source: Source) -> list[str]:
    """How a question might name a source: a repository by its name, a page or article
    by the first words of its title."""
    if source.kind == "repo":
        return [source.title.rstrip("/").split("/")[-1]]
    head = re.split(r"\s+[\u2014\u2013-]\s+|\s*\(", source.title, maxsplit=1)[0].strip()
    return [head.strip("`")] if head else []


def mentions_sources(db: Session, question: str) -> bool:
    """True if the question names one of the sources (a repository, page or article) or
    a symbol that looks like code from them, such as Signer.unsign or verify_token_v2:
    a question about the user's own sources, even if nothing matching is found."""
    lowered = question.lower()
    for source in db.scalars(select(Source)):
        for name in _names(source):
            if len(name) >= 3 and re.search(rf"(?<!\w){re.escape(name.lower())}(?!\w)", lowered):
                return True
    identifiers = {match.split(".")[-1] for match in _IDENTIFIER.findall(question)}
    if not identifiers:
        return False
    found = db.scalar(
        select(func.count(Symbol.id)).where(
            or_(*(or_(Symbol.name == i, Symbol.name.like(f"%.{i}")) for i in identifiers))
        )
    )
    return bool(found)


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
