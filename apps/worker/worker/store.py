from __future__ import annotations

from app import models
from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from worker.extract.types import FileExtraction
from worker.resolve import Edge


def replace_graph(session: Session, files: list[FileExtraction], edges: list[Edge]) -> None:
    """Replaces everything in files/symbols/edges. The caller owns the transaction."""
    session.execute(text("TRUNCATE TABLE edges, symbols, files RESTART IDENTITY CASCADE"))

    file_rows = [
        models.File(path=f.path, language=f.language, hash=f.hash, loc=f.loc, content=f.content)
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
