"""A small, hand-built code graph for the endpoint tests.

Five files, 18 symbols, 12 edges. Chosen so that each measure in /health has a
known answer:

- dead symbols: Base.describe, User.label, create_user, unused_helper
  (User.__init__ and main are unreferenced too, but are entry points)
- file cycle: cycle_a.py <-> cycle_b.py; call cycle: ping <-> pong
- long function: long_job, 60 lines
- fan-out: service.py, cycle_a.py and cycle_b.py each depend on one other file
"""

import math
import re
import zlib

from sqlalchemy import insert, text
from sqlalchemy.orm import Session

from app.models import EMBEDDING_DIM, Edge, File, Symbol

MODELS = '''"""Domain models."""


class Base:
    def describe(self) -> str:
        return self.label()

    def label(self) -> str:
        return "base"


class User(Base):
    def __init__(self, name: str) -> None:
        self.name = name

    def label(self) -> str:
        return format_name(self.name)


def format_name(name: str) -> str:
    return name.strip().title()
'''

SERVICE = """from .models import User, format_name


def create_user(raw: str) -> User:
    return User(format_name(raw))


def unused_helper() -> int:
    return 42
"""

CYCLE_A = """from .cycle_b import pong


def ping(n: int) -> int:
    return pong(n - 1) if n else 0
"""

CYCLE_B = """from .cycle_a import ping


def pong(n: int) -> int:
    return ping(n - 1) if n else 0
"""

# long_job spans lines 1-60; main is on lines 63-64.
BIG = (
    "def long_job() -> int:\n    total = 0\n"
    + "".join(f"    total += {i}\n" for i in range(57))
    + "    return total\n\n\ndef main() -> None:\n    long_job()\n"
)

# path -> (content, [(name, kind, start_line, end_line, signature)])
FILES = {
    "pkg/models.py": (
        MODELS,
        [
            ("Base", "class", 4, 9, "class Base"),
            ("Base.describe", "method", 5, 6, "def describe(self) -> str"),
            ("Base.label", "method", 8, 9, "def label(self) -> str"),
            ("User", "class", 12, 17, "class User(Base)"),
            ("User.__init__", "method", 13, 14, "def __init__(self, name: str) -> None"),
            ("User.label", "method", 16, 17, "def label(self) -> str"),
            ("format_name", "function", 20, 21, "def format_name(name: str) -> str"),
        ],
    ),
    "pkg/service.py": (
        SERVICE,
        [
            ("create_user", "function", 4, 5, "def create_user(raw: str) -> User"),
            ("unused_helper", "function", 8, 9, "def unused_helper() -> int"),
        ],
    ),
    "pkg/cycle_a.py": (CYCLE_A, [("ping", "function", 4, 5, "def ping(n: int) -> int")]),
    "pkg/cycle_b.py": (CYCLE_B, [("pong", "function", 4, 5, "def pong(n: int) -> int")]),
    "pkg/big.py": (
        BIG,
        [
            ("long_job", "function", 1, 60, "def long_job() -> int"),
            ("main", "function", 63, 64, "def main() -> None"),
        ],
    ),
}

# (kind, from, to). A bare path is that file's module symbol.
EDGES = [
    ("imports", "pkg/service.py", "pkg/models.py:User"),
    ("imports", "pkg/service.py", "pkg/models.py:format_name"),
    ("imports", "pkg/cycle_a.py", "pkg/cycle_b.py:pong"),
    ("imports", "pkg/cycle_b.py", "pkg/cycle_a.py:ping"),
    ("inherits", "pkg/models.py:User", "pkg/models.py:Base"),
    ("calls", "pkg/models.py:Base.describe", "pkg/models.py:Base.label"),
    ("calls", "pkg/models.py:User.label", "pkg/models.py:format_name"),
    ("calls", "pkg/service.py:create_user", "pkg/models.py:User"),
    ("calls", "pkg/service.py:create_user", "pkg/models.py:format_name"),
    ("calls", "pkg/cycle_a.py:ping", "pkg/cycle_b.py:pong"),
    ("calls", "pkg/cycle_b.py:pong", "pkg/cycle_a.py:ping"),
    ("calls", "pkg/big.py:main", "pkg/big.py:long_job"),
]

SYMBOL_COUNT = sum(len(symbols) + 1 for _, symbols in FILES.values())


class FakeEmbedder:
    """Deterministic bag-of-words vectors: texts sharing words are close in cosine distance."""

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * EMBEDDING_DIM
        for word in re.findall(r"[a-z]+", text.lower()):
            vector[zlib.crc32(word.encode()) % EMBEDDING_DIM] += 1.0
        if not any(vector):
            vector[0] = 1.0
        norm = math.sqrt(sum(x * x for x in vector))
        return [x / norm for x in vector]


def seed(session: Session) -> None:
    embedder = FakeEmbedder()
    session.execute(text("TRUNCATE TABLE edges, symbols, files RESTART IDENTITY CASCADE"))

    ids: dict[str, int] = {}
    for path, (content, symbols) in FILES.items():
        loc = len(content.splitlines())
        file = File(path=path, language="python", hash="0" * 64, loc=loc, content=content)
        session.add(file)
        session.flush()
        for name, kind, start, end, signature in [(path, "module", 1, loc, None), *symbols]:
            symbol = Symbol(
                file_id=file.id,
                name=name,
                kind=kind,
                start_line=start,
                end_line=end,
                signature=signature,
                embedding=embedder.embed(f"{name} {signature or ''}"),
            )
            session.add(symbol)
            session.flush()
            ids[path if kind == "module" else f"{path}:{name}"] = symbol.id

    session.execute(
        insert(Edge),
        [
            {"kind": kind, "from_symbol_id": ids[source], "to_symbol_id": ids[target]}
            for kind, source, target in EDGES
        ],
    )
