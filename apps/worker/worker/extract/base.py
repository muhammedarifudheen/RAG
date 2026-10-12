from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from typing import ClassVar

from tree_sitter import Node

from worker.extract.types import MODULE, Call, FileExtraction, Symbol


def text(node: Node) -> str:
    return node.text.decode("utf-8", errors="replace")


def line(node: Node) -> int:
    return node.start_point[0] + 1


class Extractor:
    """Walks a syntax tree, dispatching each node to `visit_<node type>` if defined."""

    language: ClassVar[str]

    def __init__(self, path: str, source: bytes, root: Node) -> None:
        self.source = source
        self.root = root
        module = Symbol(
            name=path,
            kind=MODULE,
            path=path,
            start_line=1,
            end_line=max(len(source.splitlines()), 1),
            signature=None,
            text=source.decode("utf-8", errors="replace"),
        )
        self.out = FileExtraction(path=path, language=self.language, symbols=[module])
        self._scope = [module]

    def extract(self) -> FileExtraction:
        self.visit(self.root)
        return self.out

    def visit(self, node: Node) -> None:
        handler = getattr(self, f"visit_{node.type}", None)
        if handler is None:
            self.visit_children(node)
        else:
            handler(node)

    def visit_children(self, node: Node) -> None:
        for child in node.named_children:
            self.visit(child)

    @property
    def scope(self) -> Symbol:
        return self._scope[-1]

    @contextmanager
    def inside(self, symbol: Symbol) -> Iterator[None]:
        self._scope.append(symbol)
        try:
            yield
        finally:
            self._scope.pop()

    def qualify(self, name: str) -> str:
        return name if self.scope.kind == MODULE else f"{self.scope.name}.{name}"

    def signature(self, node: Node, body: Node | None) -> str:
        """The declaration up to its body, on one line."""
        end = body.start_byte if body is not None else node.end_byte
        raw = self.source[node.start_byte : end].decode("utf-8", errors="replace")
        return " ".join(raw.split()).rstrip(":;").rstrip()

    def define(
        self,
        node: Node,
        name: str,
        kind: str,
        *,
        body: Node | None = None,
        owner: str | None = None,
        bases: Iterable[str] = (),
        span: Node | None = None,
        signature: str | None = None,
    ) -> Symbol:
        span = span or node
        symbol = Symbol(
            name=name,
            kind=kind,
            path=self.out.path,
            start_line=span.start_point[0] + 1,
            end_line=span.end_point[0] + 1,
            signature=signature if signature is not None else self.signature(node, body),
            text=text(span),
            parent=self.scope,
            owner=owner,
            bases=list(bases),
        )
        self.out.symbols.append(symbol)
        return symbol

    def call(self, node: Node, name: str, receiver: str | None) -> None:
        self.out.calls.append(
            Call(caller=self.scope, name=name, receiver=receiver, line=line(node))
        )
