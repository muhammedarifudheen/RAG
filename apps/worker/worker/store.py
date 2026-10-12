from __future__ import annotations

from dataclasses import dataclass

from app import models
from sqlalchemy import delete, insert
from sqlalchemy.orm import Session

from worker.extract.types import FileExtraction
from worker.resolve import Edge


@dataclass
class SourceInfo:
    kind: str  # one of app.models.SOURCE_KINDS
    key: str  # identifies the source across ingests, e.g. "repo:owner/name"
    title: str
    url: str | None = None


def store_source(
    session: Session, source: SourceInfo, files: list[FileExtraction], edges: list[Edge]
) -> None:
    """Adds one source and its files, replacing an earlier ingest of the same source.

    Other sources are left alone. The caller owns the transaction.
    """
    session.execute(delete(models.Source).where(models.Source.key == source.key))
    # Paths are unique across sources. If another source already holds one of
    # these (a page added singly, then again by a crawl), the newer copy wins.
    paths = [f.path for f in files]
    for start in range(0, len(paths), 500):
        session.execute(delete(models.File).where(models.File.path.in_(paths[start : start + 500])))

    source_row = models.Source(kind=source.kind, key=source.key, title=source.title, url=source.url)
    session.add(source_row)
    session.flush()

    file_rows = [
        models.File(
            source_id=source_row.id,
            path=f.path,
            language=f.language,
            hash=f.hash,
            loc=f.loc,
            content=f.content,
        )
        for f in files
    ]
    session.add_all(file_rows)
    session.flush()

    symbol_rows = {
        id(symbol): models.Symbol(
            file_id=row.id,
            name=symbol.name,
            kind=symbol.kind,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            signature=symbol.signature,
            embedding=symbol.embedding,
        )
        for f, row in zip(files, file_rows)
        for symbol in f.symbols
    }
    session.add_all(symbol_rows.values())
    session.flush()

    if edges:
        session.execute(
            insert(models.Edge),
            [
                {
                    "from_symbol_id": symbol_rows[id(edge.src)].id,
                    "to_symbol_id": symbol_rows[id(edge.dst)].id,
                    "kind": edge.kind,
                }
                for edge in edges
            ],
        )
