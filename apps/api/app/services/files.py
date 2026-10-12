from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Edge, File, Symbol
from app.schemas import FileDetail, FileEdge, FileGraph, FileNode, FileSymbol
from app.services.health import strongly_connected


def file_graph(db: Session) -> FileGraph:
    """Every file, and for each pair of files the number of edges of each kind between them."""
    source, target = aliased(Symbol), aliased(Symbol)
    rows = db.execute(
        select(source.file_id, target.file_id, Edge.kind, func.count())
        .select_from(Edge)
        .join(source, source.id == Edge.from_symbol_id)
        .join(target, target.id == Edge.to_symbol_id)
        .where(source.file_id != target.file_id)
        .group_by(source.file_id, target.file_id, Edge.kind)
    ).all()

    counts: dict[tuple[int, int], dict[str, int]] = {}
    for src, dst, kind, count in rows:
        counts.setdefault((src, dst), {})[kind] = count

    cycles = sorted(sorted(component) for component in strongly_connected(counts))
    cycle_of = {file_id: index for index, cycle in enumerate(cycles) for file_id in cycle}

    files = db.execute(
        select(File.id, File.path, File.language, File.loc, func.count(Symbol.id))
        .outerjoin(Symbol, Symbol.file_id == File.id)
        .group_by(File.id)
        .order_by(File.path)
    ).all()

    return FileGraph(
        nodes=[
            FileNode(
                id=file_id,
                path=path,
                language=language,
                loc=loc,
                symbols=symbols,
                in_cycle=file_id in cycle_of,
            )
            for file_id, path, language, loc, symbols in files
        ],
        edges=[
            FileEdge(
                source=src,
                target=dst,
                imports=kinds.get("imports", 0),
                calls=kinds.get("calls", 0),
                inherits=kinds.get("inherits", 0),
                in_cycle=src in cycle_of and cycle_of[src] == cycle_of.get(dst),
            )
            for (src, dst), kinds in sorted(counts.items())
        ],
        cycles=cycles,
    )


def file_detail(db: Session, path: str) -> FileDetail | None:
    row = db.execute(
        select(File.id, File.path, File.language, File.loc, File.content).where(File.path == path)
    ).one_or_none()
    if row is None:
        return None
    symbols = db.execute(
        select(Symbol)
        .where(Symbol.file_id == row.id, Symbol.kind != "module")
        .order_by(Symbol.start_line, Symbol.id)
    ).scalars()
    return FileDetail(
        path=row.path,
        language=row.language,
        loc=row.loc,
        content=row.content,
        symbols=[
            FileSymbol(
                id=s.id,
                name=s.name,
                kind=s.kind,
                start_line=s.start_line,
                end_line=s.end_line,
                signature=s.signature,
            )
            for s in symbols
        ],
    )
