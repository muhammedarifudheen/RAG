from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from worker.clone import clone_repo, parse_github_url, remove_clone
from worker.config import Settings
from worker.documents import build_extraction
from worker.embed import Embedder, SentenceTransformerEmbedder, symbol_text
from worker.extract import FileExtraction, extract_source, language_for
from worker.resolve import Edge, resolve
from worker.sources import (
    Loaded,
    SourceError,
    detect_kind,
    load_crawl,
    load_upload,
    load_web,
    load_wikipedia,
    parse_wikipedia_url,
)
from worker.store import SourceInfo, store_source

Progress = Callable[[str], None]

_GO_MODULE = re.compile(rb"^module\s+(\S+)", re.MULTILINE)
# Dependencies and build output. Hidden directories are skipped as well.
_SKIP_DIRS = {"node_modules", "vendor", "__pycache__", "venv", "dist"}


class IngestError(Exception):
    """A failure the CLI reports without a traceback."""


@dataclass
class ParsedRepo:
    files: list[FileExtraction] = field(default_factory=list)
    go_modules: dict[str, str] = field(default_factory=dict)  # go.mod directory -> module path
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)


@dataclass
class IngestResult:
    files: int
    symbols: int
    edges: int


def _silent(_message: str) -> None:
    pass


def _milestone(done: int, total: int) -> bool:
    """True roughly every 10% and at the end, to keep progress output short."""
    return done == total or (total >= 20 and done % (total // 10) == 0)


def discover(root: Path) -> tuple[list[Path], list[Path]]:
    """Returns (source files, go.mod files) under root, in a stable order."""
    sources, go_mods = [], []
    for directory, subdirs, names in os.walk(root):
        subdirs[:] = sorted(d for d in subdirs if d not in _SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            path = Path(directory, name)
            if path.is_symlink():  # could point outside the repository
                continue
            if name == "go.mod":
                go_mods.append(path)
            elif language_for(name):
                sources.append(path)
    return sources, go_mods


def parse_repo(
    root: Path, *, max_file_bytes: int = 1_000_000, progress: Progress = _silent
) -> ParsedRepo:
    sources, go_mods = discover(root)
    repo = ParsedRepo()

    for go_mod in go_mods:
        match = _GO_MODULE.search(go_mod.read_bytes())
        if match:
            directory = go_mod.parent.relative_to(root).as_posix()
            repo.go_modules["" if directory == "." else directory] = match[1].decode()

    for done, source in enumerate(sources, start=1):
        path = source.relative_to(root).as_posix()
        if source.stat().st_size > max_file_bytes:
            repo.skipped.append((path, "too large"))
        elif b"\x00" in (data := source.read_bytes()):
            # Not text, and Postgres cannot store NUL in a text column.
            repo.skipped.append((path, "binary"))
        else:
            try:
                repo.files.append(extract_source(path, data))
            except RecursionError:
                repo.skipped.append((path, "nesting too deep"))
        if _milestone(done, len(sources)):
            progress(f"parsed {done}/{len(sources)} files")
    return repo


def embed_symbols(files: list[FileExtraction], embedder: Embedder, progress: Progress) -> None:
    symbols = [symbol for f in files for symbol in f.symbols]

    reported = 0

    def report(done: int, total: int) -> None:
        nonlocal reported
        tenth = done * 10 // total
        if tenth > reported:
            reported = tenth
            progress(f"embedded {done}/{total} symbols")

    vectors = embedder.encode([symbol_text(s) for s in symbols], report)
    for symbol, vector in zip(symbols, vectors, strict=True):
        symbol.embedding = vector


def check_database(engine: Engine) -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM sources, files, symbols, edges LIMIT 0"))
    except SQLAlchemyError as error:
        reason = str(getattr(error, "orig", error)).strip().splitlines()[0]
        raise IngestError(
            f"Database is not ready: {reason}\n"
            "Start Postgres (docker compose up -d postgres) and run "
            "`alembic upgrade head` in apps/api."
        ) from error


def _open_database(settings: Settings) -> Engine:
    # Without a timeout, psycopg waits indefinitely when the port drops packets.
    engine = create_engine(settings.database_url, connect_args={"connect_timeout": 5})
    check_database(engine)
    return engine


def _load_embedder(settings: Settings, progress: Progress) -> Embedder:
    progress(f"      loading {settings.embedding_model}")
    return SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_batch_size)


def _under_prefix(files: list[FileExtraction], prefix: str) -> None:
    """Moves every file under `prefix`, so paths stay unique across sources."""
    if not prefix:
        return
    for f in files:
        f.path = prefix + f.path
        f.module.name = f.path
        for symbol in f.symbols:
            symbol.path = f.path


def ingest_directory(
    root: Path,
    *,
    engine: Engine,
    embedder: Embedder,
    source: SourceInfo | None = None,
    prefix: str = "",
    max_file_bytes: int = 1_000_000,
    progress: Progress = _silent,
) -> IngestResult:
    """Steps 2-5: parse, resolve, embed and store the repository at `root`.

    It is stored as `source`, replacing an earlier ingest of the same source and
    leaving other sources alone. `prefix` is put in front of every file path.
    """
    source = source or SourceInfo(kind="repo", key=f"local:{root.name}", title=root.name)

    progress("[2/5] Parsing source files")
    repo = parse_repo(root, max_file_bytes=max_file_bytes, progress=lambda m: progress(f"      {m}"))
    for path, reason in repo.skipped:
        progress(f"      skipped {path}: {reason}")
    languages = Counter(f.language for f in repo.files)
    summary = ", ".join(f"{count} {language}" for language, count in sorted(languages.items()))
    symbol_count = sum(len(f.symbols) for f in repo.files)
    progress(f"      {len(repo.files)} files ({summary or 'none'}), {symbol_count} symbols")

    progress("[3/5] Resolving imports, calls and inheritance")
    edges: list[Edge] = resolve(repo.files, repo.go_modules)
    kinds = Counter(edge.kind for edge in edges)
    summary = ", ".join(f"{count} {kind}" for kind, count in sorted(kinds.items()))
    progress(f"      {len(edges)} edges ({summary or 'none'})")
    # Resolution works on paths relative to the repository; prefix them afterwards.
    _under_prefix(repo.files, prefix)

    progress(f"[4/5] Embedding {symbol_count} symbols")
    embed_symbols(repo.files, embedder, lambda m: progress(f"      {m}"))

    progress("[5/5] Writing to Postgres")
    with Session(engine) as session, session.begin():
        store_source(session, source, repo.files, edges)

    return IngestResult(files=len(repo.files), symbols=symbol_count, edges=len(edges))


def ingest_repo(
    url: str, *, settings: Settings, keep_clone: bool = False, progress: Progress = _silent
) -> IngestResult:
    try:
        owner, name = parse_github_url(url)
    except ValueError as error:
        raise IngestError(str(error)) from error
    engine = _open_database(settings)

    progress(f"[1/5] Cloning {url}")
    cloned = clone_repo(url, settings.clone_dir, settings.github_token)
    progress(f"      {cloned.path} at {cloned.commit[:12]}")

    try:
        return ingest_directory(
            cloned.path,
            engine=engine,
            embedder=_load_embedder(settings, progress),
            source=SourceInfo(
                kind="repo",
                key=f"repo:{owner}/{name}".lower(),
                title=f"{owner}/{name}",
                url=f"https://github.com/{owner}/{name}",
            ),
            prefix=f"{owner}/{name}/",
            max_file_bytes=settings.max_file_bytes,
            progress=progress,
        )
    finally:
        if keep_clone:
            progress(f"      kept clone at {cloned.path}")
        else:
            remove_clone(cloned.path)
        engine.dispose()


def ingest_documents(
    kind: str,
    key: str,
    load: Callable[[], Loaded],
    what: str,
    *,
    settings: Settings,
    progress: Progress = _silent,
) -> IngestResult:
    """Fetches documents with `load`, splits them into passages, embeds and stores them."""
    engine = _open_database(settings)
    try:
        progress(f"[1/4] Fetching {what}")
        try:
            loaded = load()
        except SourceError as error:
            raise IngestError(str(error)) from error

        progress(f"[2/4] Splitting {len(loaded.documents)} document(s) into passages")
        files = []
        for document in loaded.documents:
            try:
                files.append(build_extraction(document))
            except ValueError as error:
                progress(f"      skipped: {error}")
        if not files:
            raise IngestError("No readable text was found.")
        passages = sum(len(f.symbols) - 1 for f in files)
        progress(f"      {len(files)} document(s), {passages} passages")

        progress(f"[3/4] Embedding {passages} passages")
        embed_symbols(files, _load_embedder(settings, progress), lambda m: progress(f"      {m}"))

        progress("[4/4] Writing to Postgres")
        source = SourceInfo(kind=kind, key=key, title=loaded.title, url=loaded.url)
        with Session(engine) as session, session.begin():
            store_source(session, source, files, [])
        return IngestResult(
            files=len(files), symbols=sum(len(f.symbols) for f in files), edges=0
        )
    finally:
        engine.dispose()


def ingest_url(
    url: str,
    *,
    settings: Settings,
    kind: str = "auto",
    max_pages: int = 20,
    keep_clone: bool = False,
    progress: Progress = _silent,
) -> IngestResult:
    """Ingests a link. `kind` is repo, web, wikipedia or crawl; "auto" picks from the address."""
    url = url.strip()
    if kind == "auto":
        kind = detect_kind(url)
    if kind == "repo":
        return ingest_repo(url, settings=settings, keep_clone=keep_clone, progress=progress)
    if kind == "wikipedia":
        language, title = _wikipedia_identity(url)
        return ingest_documents(
            "wikipedia",
            f"wikipedia:{language}:{title}".lower(),
            lambda: load_wikipedia(url),
            f"the Wikipedia article {title!r}",
            settings=settings,
            progress=progress,
        )
    if kind == "crawl":
        return ingest_documents(
            "crawl",
            f"crawl:{url}".lower(),
            lambda: load_crawl(url, max_pages, lambda m: progress(f"      {m}")),
            f"up to {max_pages} pages starting at {url}",
            settings=settings,
            progress=progress,
        )
    if kind == "web":
        return ingest_documents(
            "web", f"web:{url}".lower(), lambda: load_web(url), url, settings=settings, progress=progress
        )
    raise IngestError(f"Unknown source kind {kind!r}.")


def _wikipedia_identity(url: str) -> tuple[str, str]:
    try:
        return parse_wikipedia_url(url)
    except SourceError as error:
        raise IngestError(str(error)) from error


def ingest_upload(
    path: Path, filename: str, *, settings: Settings, progress: Progress = _silent
) -> IngestResult:
    """Ingests a PDF, EPUB, text, Markdown or HTML file that is already on disk."""
    return ingest_documents(
        "upload",
        f"upload:{filename}".lower(),
        lambda: load_upload(path, filename),
        filename,
        settings=settings,
        progress=progress,
    )
