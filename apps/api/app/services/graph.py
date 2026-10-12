from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Edge, File, Symbol
from app.schemas import GraphEdge, GraphNode, GraphResponse

MAX_NODES = 500


def call_graph(
    db: Session, path: str, hops: int, direction: str, max_nodes: int = MAX_NODES
) -> GraphResponse | None:
    """The call graph within `hops` calls of a file's symbols, or None if the file is unknown."""
    file_id = db.execute(select(File.id).where(File.path == path)).scalar_one_or_none()
    if file_id is None:
        return None

    seeds = db.execute(select(Symbol.id).where(Symbol.file_id == file_id)).scalars().all()
    depth = {symbol_id: 0 for symbol_id in seeds}
    frontier = set(seeds)
    edges: set[tuple[int, int]] = set()
    truncated = False

    for hop in range(1, hops + 1):
        if not frontier:
            break
        reachable = []
        if direction in ("callees", "both"):
            reachable.append(Edge.from_symbol_id.in_(frontier))
        if direction in ("callers", "both"):
            reachable.append(Edge.to_symbol_id.in_(frontier))
        rows = db.execute(
            select(Edge.from_symbol_id, Edge.to_symbol_id)
            .where(Edge.kind == "calls", or_(*reachable))
            .order_by(Edge.id)
        ).all()

        frontier = set()
        for source, target in rows:
            edges.add((source, target))
            for symbol_id in (source, target):
                if symbol_id in depth:
                    continue
                if len(depth) >= max_nodes:
                    truncated = True
                    continue
                depth[symbol_id] = hop
                frontier.add(symbol_id)

    symbols = db.execute(
        select(Symbol, File.path)
        .join(File, File.id == Symbol.file_id)
        .where(Symbol.id.in_(depth))
        .order_by(File.path, Symbol.start_line, Symbol.id)
    ).all()
    nodes = [
        GraphNode(
            id=symbol.id,
            name=symbol.name,
            kind=symbol.kind,
            file=symbol_path,
            start_line=symbol.start_line,
            end_line=symbol.end_line,
            depth=depth[symbol.id],
        )
        for symbol, symbol_path in symbols
    ]
    nodes.sort(key=lambda node: node.depth)  # stable: keeps file and line order within a depth

    return GraphResponse(
        file=path,
        hops=hops,
        direction=direction,
        nodes=nodes,
        edges=[
            GraphEdge(source=source, target=target)
            for source, target in sorted(edges)
            if source in depth and target in depth
        ],
        truncated=truncated,
    )
