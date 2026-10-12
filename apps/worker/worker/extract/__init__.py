from __future__ import annotations

import hashlib
from functools import cache
from pathlib import PurePosixPath

import tree_sitter_go
import tree_sitter_python
import tree_sitter_typescript
from tree_sitter import Language, Parser

from worker.extract.base import Extractor
from worker.extract.go import GoExtractor
from worker.extract.python import PythonExtractor
from worker.extract.types import Call, FileExtraction, Import, Symbol
from worker.extract.typescript import TypeScriptExtractor

__all__ = ["Call", "FileExtraction", "Import", "Symbol", "extract_source", "language_for"]

_GRAMMARS = {
    "python": tree_sitter_python.language,
    "typescript": tree_sitter_typescript.language_typescript,
    "tsx": tree_sitter_typescript.language_tsx,
    "go": tree_sitter_go.language,
}

# extension -> (language stored in files.language, grammar)
_EXTENSIONS = {
    ".py": ("python", "python"),
    ".ts": ("typescript", "typescript"),
    ".mts": ("typescript", "typescript"),
    ".cts": ("typescript", "typescript"),
    ".tsx": ("typescript", "tsx"),
    ".go": ("go", "go"),
}

_EXTRACTORS: dict[str, type[Extractor]] = {
    "python": PythonExtractor,
    "typescript": TypeScriptExtractor,
    "go": GoExtractor,
}


@cache
def _parser(grammar: str) -> Parser:
    return Parser(Language(_GRAMMARS[grammar]()))


def language_for(path: str) -> str | None:
    entry = _EXTENSIONS.get(PurePosixPath(path).suffix.lower())
    return entry[0] if entry else None


def extract_source(path: str, source: bytes) -> FileExtraction:
    """Parse one file. `path` is POSIX and relative to the repo root."""
    language, grammar = _EXTENSIONS[PurePosixPath(path).suffix.lower()]
    tree = _parser(grammar).parse(source)
    extraction = _EXTRACTORS[language](path, source, tree.root_node).extract()
    extraction.hash = hashlib.sha256(source).hexdigest()
    extraction.loc = len(source.splitlines())
    extraction.content = extraction.module.text
    return extraction
