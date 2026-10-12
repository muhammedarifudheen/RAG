from pathlib import Path

from worker.extract import FileExtraction, Symbol
from worker.resolve import Edge

FIXTURE_REPO = Path(__file__).parent / "fixtures" / "sample_repo"


def symbol_table(f: FileExtraction) -> set[tuple[str, str, int, int]]:
    return {(s.name, s.kind, s.start_line, s.end_line) for s in f.symbols}


def signatures(f: FileExtraction) -> dict[str, str | None]:
    return {s.name: s.signature for s in f.symbols[1:]}


def bases(f: FileExtraction) -> dict[str, list[str]]:
    return {s.name: s.bases for s in f.symbols if s.bases}


def calls(f: FileExtraction) -> set[tuple[str, str | None, str]]:
    return {(c.caller.name, c.receiver, c.name) for c in f.calls}


def imports(f: FileExtraction) -> list[tuple]:
    return [(i.module, i.level, i.alias, i.names) for i in f.imports]


def label(symbol: Symbol) -> str:
    return symbol.name if symbol.kind == "module" else f"{symbol.path}:{symbol.name}"


def edge_set(edges: list[Edge], kind: str) -> set[tuple[str, str]]:
    return {(label(e.src), label(e.dst)) for e in edges if e.kind == kind}
