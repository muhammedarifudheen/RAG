"""What re-ingesting a source would change, without changing anything: its files are
fetched again and hashed, and compared with what is stored."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session
from worker.clone import clone_repo, parse_github_url, remove_clone
from worker.config import Settings as WorkerSettings
from worker.documents import build_extraction
from worker.pipeline import discover
from worker.sources import SourceError, load_crawl, load_web, load_wikipedia

from app.config import settings
from app.models import File, Source


class PreviewError(Exception):
    pass


def _stored(db: Session, source: Source) -> dict[str, str]:
    return dict(db.execute(select(File.path, File.hash).where(File.source_id == source.id)).all())


def _repo_hashes(url: str) -> dict[str, str]:
    owner, name = parse_github_url(url)
    worker = WorkerSettings(database_url=settings.database_url)
    cloned = clone_repo(url, worker.clone_dir, worker.github_token)
    try:
        files, _ = discover(cloned.path)
        out = {}
        for path in files:
            if path.stat().st_size > worker.max_file_bytes:
                continue
            relative = path.relative_to(cloned.path).as_posix()
            out[f"{owner}/{name}/{relative}"] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        return out
    finally:
        remove_clone(cloned.path)


def _document_hashes(source: Source, pages: int) -> dict[str, str]:
    if source.kind == "wikipedia":
        loaded = load_wikipedia(source.url)
    elif source.kind == "crawl":
        loaded = load_crawl(source.url, max(pages, 1), lambda _message: None)
    else:
        loaded = load_web(source.url)
    out = {}
    for document in loaded.documents:
        try:
            out[document.path] = build_extraction(document).hash
        except ValueError:
            continue
    return out


def preview(db: Session, source: Source) -> dict:
    """{added, changed, removed: [paths], unchanged: n} if the source were re-ingested now."""
    if source.kind == "upload" or not source.url:
        raise PreviewError("An uploaded file cannot be fetched again: upload it again instead.")
    stored = _stored(db, source)
    try:
        fresh = (
            _repo_hashes(source.url)
            if source.kind == "repo"
            else _document_hashes(source, len(stored))
        )
    except (SourceError, ValueError, OSError) as error:
        raise PreviewError(str(error)) from error
    return {
        "added": sorted(set(fresh) - set(stored)),
        "changed": sorted(p for p in set(fresh) & set(stored) if fresh[p] != stored[p]),
        "removed": sorted(set(stored) - set(fresh)),
        "unchanged": sum(1 for p in set(fresh) & set(stored) if fresh[p] == stored[p]),
    }
