from __future__ import annotations

from dataclasses import dataclass, field

MODULE = "module"
FUNCTION = "function"
CLASS = "class"
METHOD = "method"

# Normalised call receivers: `self.f()` / `this.f()` / Go receiver, and `super().f()`.
SELF = "<self>"
SUPER = "<super>"


@dataclass(eq=False)
class Symbol:
    """A definition in a file. Compared by identity so edges can reference it directly."""

    name: str  # qualified within the file, e.g. "Class.method"; the file path for modules
    kind: str
    path: str
    start_line: int  # 1-based, inclusive
    end_line: int
    signature: str | None
    text: str = field(default="", repr=False)  # source, used only to build the embedding
    parent: Symbol | None = field(default=None, repr=False)  # lexically enclosing symbol
    owner: str | None = None  # for methods: name of the class they belong to
    bases: list[str] = field(default_factory=list)  # for classes: base names as written
    embedding: list[float] | None = field(default=None, repr=False)


@dataclass
class Import:
    module: str  # as written: "pkg.mod", "./util", "example.com/mod/pkg"
    line: int
    names: list[tuple[str, str]] = field(default_factory=list)  # (imported name, local name)
    alias: str | None = None  # local name bound to the module itself
    level: int = 0  # Python relative import depth
    wildcard: bool = False


@dataclass
class Call:
    caller: Symbol
    name: str
    receiver: str | None  # None for `f()`; SELF, SUPER, or the receiver's source text
    line: int


@dataclass
class FileExtraction:
    path: str  # POSIX, relative to the repo root
    language: str
    hash: str = ""
    loc: int = 0
    content: str = field(default="", repr=False)
    package: str | None = None  # Go package name
    default_export: str | None = None  # TypeScript `export default`
    symbols: list[Symbol] = field(default_factory=list)  # symbols[0] is the module
    imports: list[Import] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    @property
    def module(self) -> Symbol:
        return self.symbols[0]
