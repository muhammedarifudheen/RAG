from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Edge, File, Symbol
from app.schemas import (
    Cycles,
    FanOut,
    HealthReport,
    HealthSummary,
    HealthThresholds,
    LongFunction,
    SymbolRef,
)

# Called by a runtime or framework rather than by code in the repository.
_ENTRY_POINTS = {"main", "init", "constructor"}

_REF_COLUMNS = (Symbol.id, Symbol.name, Symbol.kind, File.path, Symbol.start_line, Symbol.end_line)


def _ref(row) -> SymbolRef:
    return SymbolRef(
        id=row[0], name=row[1], kind=row[2], file=row[3], start_line=row[4], end_line=row[5]
    )


def _is_entry_point(name: str) -> bool:
    short = name.rsplit(".", 1)[-1]
    return (
        short in _ENTRY_POINTS
        or (short.startswith("__") and short.endswith("__"))
        or short.lower().startswith("test")
    )


def strongly_connected(edges: Iterable[tuple[int, int]]) -> list[list[int]]:
    """Tarjan's algorithm, iteratively. Returns only components with more than one node."""
    graph: dict[int, list[int]] = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
        graph.setdefault(target, [])

    index: dict[int, int] = {}
    low: dict[int, int] = {}
    stack: list[int] = []
    on_stack: set[int] = set()
    components: list[list[int]] = []

    def enter(node: int) -> None:
        index[node] = low[node] = len(index)
        stack.append(node)
        on_stack.add(node)
        work.append((node, iter(graph[node])))

    for root in graph:
        if root in index:
            continue
        work: list[tuple[int, Iterable[int]]] = []
        enter(root)
        while work:
            node, successors = work[-1]
            for successor in successors:
                if successor not in index:
                    enter(successor)
                    break
                if successor in on_stack:
                    low[node] = min(low[node], index[successor])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    if len(component) > 1:
                        components.append(component)
    return components


def code_health(
    db: Session, *, max_function_loc: int, min_fan_out: int, limit: int
) -> HealthReport:
    # Dead symbols: functions and methods nothing calls or imports. Self-calls do not count.
    # Classes are left out: a type used in a declaration or literal leaves no edge, so
    # every Go struct and TypeScript interface would be reported.
    referenced = select(Edge.to_symbol_id).where(Edge.from_symbol_id != Edge.to_symbol_id)
    unreferenced = db.execute(
        select(*_REF_COLUMNS)
        .join(File, File.id == Symbol.file_id)
        .where(Symbol.kind.in_(("function", "method")), Symbol.id.not_in(referenced))
        .order_by(File.path, Symbol.start_line, Symbol.id)
    ).all()
    dead = [_ref(row) for row in unreferenced if not _is_entry_point(row[1])]

    loc = (Symbol.end_line - Symbol.start_line + 1).label("loc")
    long_rows = db.execute(
        select(*_REF_COLUMNS, loc)
        .join(File, File.id == Symbol.file_id)
        .where(Symbol.kind.in_(("function", "method")), loc > max_function_loc)
        .order_by(loc.desc(), File.path, Symbol.start_line)
    ).all()
    long_functions = [LongFunction(**_ref(row).model_dump(), loc=row[6]) for row in long_rows]

    # File A depends on file B if any symbol in A has an edge to a symbol in B.
    source, target = aliased(Symbol), aliased(Symbol)
    file_edges = db.execute(
        select(source.file_id, target.file_id)
        .select_from(Edge)
        .join(source, source.id == Edge.from_symbol_id)
        .join(target, target.id == Edge.to_symbol_id)
        .where(source.file_id != target.file_id)
        .distinct()
    ).all()
    paths = dict(db.execute(select(File.id, File.path)).all())

    dependencies: dict[int, set[int]] = {}
    for src, dst in file_edges:
        dependencies.setdefault(src, set()).add(dst)
    fan_out = sorted(
        (
            FanOut(
                file=paths[file_id],
                fan_out=len(targets),
                depends_on=sorted(paths[t] for t in targets),
            )
            for file_id, targets in dependencies.items()
            if len(targets) >= min_fan_out
        ),
        key=lambda item: (-item.fan_out, item.file),
    )

    file_cycles = sorted(
        sorted(paths[file_id] for file_id in component)
        for component in strongly_connected(file_edges)
    )

    call_edges = db.execute(
        select(Edge.from_symbol_id, Edge.to_symbol_id).where(
            Edge.kind == "calls", Edge.from_symbol_id != Edge.to_symbol_id
        )
    ).all()
    components = strongly_connected(call_edges)
    members = {symbol_id for component in components for symbol_id in component}
    refs = {
        row[0]: _ref(row)
        for row in db.execute(
            select(*_REF_COLUMNS)
            .join(File, File.id == Symbol.file_id)
            .where(Symbol.id.in_(members))
        ).all()
    }
    call_cycles = sorted(
        (
            sorted((refs[i] for i in component), key=lambda r: (r.file, r.start_line, r.id))
            for component in components
        ),
        key=lambda cycle: (cycle[0].file, cycle[0].start_line),
    )

    return HealthReport(
        summary=HealthSummary(
            files=db.scalar(select(func.count()).select_from(File)) or 0,
            symbols=db.scalar(select(func.count()).select_from(Symbol)) or 0,
            edges=db.scalar(select(func.count()).select_from(Edge)) or 0,
            dead_symbols=len(dead),
            file_cycles=len(file_cycles),
            call_cycles=len(call_cycles),
            long_functions=len(long_functions),
            high_fan_out_files=len(fan_out),
        ),
        thresholds=HealthThresholds(max_function_loc=max_function_loc, min_fan_out=min_fan_out),
        dead_symbols=dead[:limit],
        circular_dependencies=Cycles(files=file_cycles[:limit], calls=call_cycles[:limit]),
        long_functions=long_functions[:limit],
        high_fan_out_files=fan_out[:limit],
    )
