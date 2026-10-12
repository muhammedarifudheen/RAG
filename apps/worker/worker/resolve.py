"""Turns per-file extractions into edges between symbols.

Resolution is syntactic: a reference becomes an edge only when its target can be
identified from names, imports and class hierarchies. There is no type inference,
so calls on arbitrary values (`user.save()`) are dropped rather than guessed.
"""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass

from worker.extract.types import (
    CLASS,
    METHOD,
    MODULE,
    SELF,
    SUPER,
    Call,
    FileExtraction,
    Import,
    Symbol,
)

CALLS = "calls"
IMPORTS = "imports"
INHERITS = "inherits"

_TS_SUFFIXES = ("", ".ts", ".tsx", ".mts", ".cts", "/index.ts", "/index.tsx")
_JS_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs")


@dataclass(frozen=True)
class Edge:
    src: Symbol
    dst: Symbol
    kind: str


def resolve(files: list[FileExtraction], go_modules: dict[str, str] | None = None) -> list[Edge]:
    """`go_modules` maps the directory of each go.mod ("" for the root) to its module path."""
    return _Resolver(files, go_modules or {}).run()


class _Resolver:
    def __init__(self, files: list[FileExtraction], go_modules: dict[str, str]) -> None:
        self.files = {f.path: f for f in files}
        self.go_modules = go_modules
        self.edges: dict[Edge, None] = {}

        # name -> symbol per file; the first definition wins on duplicates.
        self.defs: dict[str, dict[str, Symbol]] = {}
        for f in files:
            names: dict[str, Symbol] = {}
            for symbol in f.symbols[1:]:
                names.setdefault(symbol.name, symbol)
            self.defs[f.path] = names

        # A Go package is a directory: its files share one namespace.
        self.go_packages: dict[str, list[FileExtraction]] = defaultdict(list)
        self.go_defs: dict[str, dict[str, Symbol]] = defaultdict(dict)
        for f in files:
            if f.language == "go":
                directory = posixpath.dirname(f.path)
                self.go_packages[directory].append(f)
                for name, symbol in self.defs[f.path].items():
                    self.go_defs[directory].setdefault(name, symbol)

        # Python module name -> [(source root, path)]. A file's importable name starts
        # at the nearest ancestor directory that is not a package; the name from the
        # repo root is indexed too, which covers namespace packages.
        self.py_modules: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for f in files:
            if f.language == "python":
                for root in {self._py_root(f.path), ""}:
                    name = self._py_name(f.path, root)
                    if name:
                        self.py_modules[name].append((root, f.path))

        # Local names introduced by imports, per file.
        self.bound_symbols: dict[str, dict[str, Symbol]] = defaultdict(dict)
        self.bound_modules: dict[str, dict[str, list[str]]] = defaultdict(dict)

    def run(self) -> list[Edge]:
        binders = {"python": self._bind_python, "typescript": self._bind_ts, "go": self._bind_go}
        for f in self.files.values():
            for imported in f.imports:
                binders[f.language](f, imported)
        for f in self.files.values():
            for symbol in f.symbols:
                if symbol.kind == CLASS:
                    for base in self._bases(symbol):
                        if base is not symbol:
                            self._add(symbol, base, INHERITS)
        for f in self.files.values():
            for call in f.calls:
                target = self._resolve_call(f, call)
                if target is not None:
                    self._add(call.caller, target, CALLS)
        return list(self.edges)

    def _add(self, src: Symbol, dst: Symbol, kind: str) -> None:
        self.edges.setdefault(Edge(src, dst, kind))

    # --- imports -------------------------------------------------------------

    def _import_module(self, f: FileExtraction, path: str, local: str | None) -> None:
        self._add(f.module, self.files[path].module, IMPORTS)
        if local:
            self.bound_modules[f.path].setdefault(local, []).append(path)

    def _import_symbol(self, f: FileExtraction, symbol: Symbol, local: str) -> None:
        self._add(f.module, symbol, IMPORTS)
        self.bound_symbols[f.path][local] = symbol

    def _import_all(self, f: FileExtraction, path: str) -> None:
        for name, symbol in self.defs[path].items():
            if "." not in name:
                self.bound_symbols[f.path].setdefault(name, symbol)

    def _py_root(self, path: str) -> str:
        directory = posixpath.dirname(path)
        while directory and posixpath.join(directory, "__init__.py") in self.files:
            directory = posixpath.dirname(directory)
        return directory

    @staticmethod
    def _py_name(path: str, root: str) -> str:
        relative = posixpath.relpath(path, root) if root else path
        parts = relative[: -len(".py")].split("/")
        if parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _py_module(self, f: FileExtraction, module: str, level: int) -> str | None:
        if level:
            base = posixpath.dirname(f.path)
            for _ in range(level - 1):
                base = posixpath.dirname(base)
            target = posixpath.join(base, *module.split(".")) if module else base
            for candidate in (f"{target}.py", posixpath.join(target, "__init__.py")):
                if candidate in self.files:
                    return candidate
            return None

        candidates = self.py_modules.get(module)
        if not candidates:
            return None
        own_root = self._py_root(f.path)
        # Prefer the importer's own source root, then the shallowest one.
        return min(candidates, key=lambda c: (c[0] != own_root, c[0].count("/"), c[0], c[1]))[1]

    def _bind_python(self, f: FileExtraction, imported: Import) -> None:
        target = self._py_module(f, imported.module, imported.level)

        if not imported.names and not imported.wildcard:  # import a.b [as c]
            if target:
                self._import_module(f, target, imported.alias)
            return

        if imported.wildcard and target:
            self._import_module(f, target, None)
            self._import_all(f, target)

        for name, local in imported.names:
            symbol = self.defs[target].get(name) if target else None
            if symbol is not None:
                self._import_symbol(f, symbol, local)
                continue
            # `from pkg import submodule`
            dotted = f"{imported.module}.{name}" if imported.module else name
            submodule = self._py_module(f, dotted, imported.level)
            if submodule:
                self._import_module(f, submodule, local)
            elif target:
                self._import_module(f, target, None)

    def _ts_module(self, f: FileExtraction, specifier: str) -> str | None:
        if not specifier.startswith("."):
            return None  # a package, or a tsconfig path alias
        base = posixpath.normpath(posixpath.join(posixpath.dirname(f.path), specifier))
        bases = [base]
        for extension in _JS_EXTENSIONS:  # ESM-style `./util.js` refers to util.ts
            if base.endswith(extension):
                bases.append(base[: -len(extension)])
        for candidate in (b + suffix for b in bases for suffix in _TS_SUFFIXES):
            if candidate in self.files and candidate != f.path:
                return candidate
        return None

    def _bind_ts(self, f: FileExtraction, imported: Import) -> None:
        target = self._ts_module(f, imported.module)
        if not target:
            return
        if imported.alias or not imported.names:  # namespace, side-effect or re-export
            self._import_module(f, target, imported.alias)
        for name, local in imported.names:
            if name == "default":
                name = self.files[target].default_export or ""
            symbol = self.defs[target].get(name)
            if symbol is not None:
                self._import_symbol(f, symbol, local)
            else:
                self._import_module(f, target, local)

    def _go_package(self, import_path: str) -> list[FileExtraction]:
        for directory, module in sorted(self.go_modules.items(), key=lambda m: -len(m[1])):
            if import_path == module or import_path.startswith(module + "/"):
                relative = import_path[len(module) :].lstrip("/")
                package = posixpath.join(directory, relative) if relative else directory
                return [
                    f for f in self.go_packages.get(package, []) if not f.path.endswith("_test.go")
                ]
        return []

    def _bind_go(self, f: FileExtraction, imported: Import) -> None:
        targets = self._go_package(imported.module)
        if not targets:
            return
        if imported.alias in ("_", "."):
            local = None
        else:
            local = imported.alias or targets[0].package or imported.module.rsplit("/", 1)[-1]
        for target in targets:
            self._import_module(f, target.path, local)
            if imported.alias == ".":
                self._import_all(f, target.path)

    # --- names ---------------------------------------------------------------

    def _lookup(self, f: FileExtraction, name: str) -> Symbol | None:
        """A name visible at file level: defined here, in the Go package, or imported."""
        symbol = self.defs[f.path].get(name)
        if symbol is None and f.language == "go":
            symbol = self.go_defs[posixpath.dirname(f.path)].get(name)
        return symbol or self.bound_symbols[f.path].get(name)

    def _lookup_dotted(self, f: FileExtraction, dotted: str) -> Symbol | None:
        if "." not in dotted:
            return self._lookup(f, dotted)
        receiver, _, name = dotted.rpartition(".")
        return self._member(f, receiver, name)

    def _member(self, f: FileExtraction, receiver: str, name: str) -> Symbol | None:
        """`receiver.name` where receiver is an imported module or a known class."""
        paths = self.bound_modules[f.path].get(receiver)
        if paths:
            for path in paths:
                symbol = self.defs[path].get(name)
                if symbol is not None:
                    return symbol
            return None
        owner = self._lookup_dotted(f, receiver)
        if owner is not None and owner.kind == CLASS:
            return self._find_member(owner, name, set())
        return None

    def _bases(self, cls: Symbol) -> list[Symbol]:
        f = self.files[cls.path]
        resolved = (self._lookup_dotted(f, base) for base in cls.bases)
        return [base for base in resolved if base is not None and base.kind == CLASS]

    def _find_member(self, cls: Symbol, name: str, seen: set[int]) -> Symbol | None:
        """A method on a class or, failing that, on its bases."""
        if id(cls) in seen:
            return None
        seen.add(id(cls))
        member = self._lookup(self.files[cls.path], f"{cls.name}.{name}")
        if member is not None:
            return member
        for base in self._bases(cls):
            member = self._find_member(base, name, seen)
            if member is not None:
                return member
        return None

    def _enclosing_class(self, f: FileExtraction, symbol: Symbol | None) -> Symbol | None:
        while symbol is not None:
            if symbol.kind == METHOD and symbol.owner:
                cls = self._lookup(f, symbol.owner)
                return cls if cls is not None and cls.kind == CLASS else None
            symbol = symbol.parent
        return None

    # --- calls ---------------------------------------------------------------

    def _resolve_call(self, f: FileExtraction, call: Call) -> Symbol | None:
        if call.receiver is None:
            # Functions nested in the caller or its enclosing functions come first.
            # Class bodies are skipped: methods are not in scope as bare names.
            scope: Symbol | None = call.caller
            while scope is not None and scope.kind != MODULE:
                if scope.kind != CLASS:
                    nested = self.defs[f.path].get(f"{scope.name}.{call.name}")
                    if nested is not None:
                        return nested
                scope = scope.parent
            return self._lookup(f, call.name)

        if call.receiver in (SELF, SUPER):
            cls = self._enclosing_class(f, call.caller)
            if cls is None:
                return None
            if call.receiver == SELF:
                return self._find_member(cls, call.name, set())
            for base in self._bases(cls):
                member = self._find_member(base, call.name, set())
                if member is not None:
                    return member
            return None

        return self._member(f, call.receiver, call.name)
