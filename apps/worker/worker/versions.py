"""Ingest versions: each ingest of a source is snapshotted (files, symbols with their
embeddings, edges), the last three are kept, and any of them can be restored."""

from __future__ import annotations

import base64
import json
import zlib
from typing import Any

import numpy as np
from app import models
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

KEEP = 3


def _vector(value: Any) -> str | None:
    if value is None:
        return None
    return base64.b64encode(np.asarray(value, dtype=np.float32).tobytes()).decode("ascii")


def _unvector(value: str | None) -> list[float] | None:
    if value is None:
        return None
    return np.frombuffer(base64.b64decode(value), dtype=np.float32).tolist()


def snapshot(session: Session, source: models.Source) -> None:
    """Keeps the source as it now stands as a version, and only the last three."""
    files = session.scalars(select(models.File).where(models.File.source_id == source.id)).all()
    by_file = {f.id: f for f in files}
    symbols = session.scalars(
        select(models.Symbol).where(models.Symbol.file_id.in_(list(by_file) or [0]))
    ).all()
    index: dict[int, tuple[int, int]] = {}
    out_files: list[dict] = []
    positions = {f.id: i for i, f in enumerate(files)}
    for f in files:
        out_files.append(
            {
                "path": f.path,
                "language": f.language,
                "hash": f.hash,
                "loc": f.loc,
                "content": f.content,
                "symbols": [],
            }
        )
    for s in symbols:
        entries = out_files[positions[s.file_id]]["symbols"]
        index[s.id] = (positions[s.file_id], len(entries))
        entries.append(
            {
                "name": s.name,
                "kind": s.kind,
                "start": s.start_line,
                "end": s.end_line,
                "signature": s.signature,
                "embedding": _vector(s.embedding),
                "minhash": base64.b64encode(s.minhash).decode() if s.minhash else None,
            }
        )
    ids = list(index)
    edges = (
        session.execute(
            select(models.Edge.from_symbol_id, models.Edge.to_symbol_id, models.Edge.kind).where(
                models.Edge.from_symbol_id.in_(ids)
            )
        ).all()
        if ids
        else []
    )
    out_edges = [[*index[a], *index[b], kind] for a, b, kind in edges if a in index and b in index]
    blob = zlib.compress(json.dumps({"files": out_files, "edges": out_edges}).encode(), 6)
    session.add(
        models.SourceVersion(
            source_key=source.key,
            version=source.version,
            kind=source.kind,
            title=source.title,
            url=source.url,
            source_updated_at=source.source_updated_at,
            files=len(files),
            symbols=len(symbols),
            snapshot=blob,
        )
    )
    session.flush()
    kept = select(models.SourceVersion.id).where(models.SourceVersion.source_key == source.key)
    old = session.scalars(kept.order_by(models.SourceVersion.version.desc()).offset(KEEP)).all()
    if old:
        session.execute(delete(models.SourceVersion).where(models.SourceVersion.id.in_(old)))


def next_version(session: Session, key: str) -> int:
    latest = session.scalar(
        select(func.max(models.SourceVersion.version)).where(models.SourceVersion.source_key == key)
    )
    current = session.scalar(select(models.Source.version).where(models.Source.key == key))
    return max(latest or 0, current or 0) + 1


def restore(session: Session, key: str, version: int) -> models.Source:
    """Makes version `version` of the source current again (as a new version, so the
    rollback itself can be undone). The caller owns the transaction."""
    kept = session.scalars(
        select(models.SourceVersion).where(
            models.SourceVersion.source_key == key, models.SourceVersion.version == version
        )
    ).first()
    if kept is None:
        raise LookupError(f"Version {version} of that source is not kept.")
    data = json.loads(zlib.decompress(kept.snapshot))
    current = session.scalars(select(models.Source).where(models.Source.key == key)).first()
    weight = current.weight if current is not None else None
    new_version = next_version(session, key)
    session.execute(delete(models.Source).where(models.Source.key == key))
    paths = [f["path"] for f in data["files"]]
    for start in range(0, len(paths), 500):
        session.execute(delete(models.File).where(models.File.path.in_(paths[start : start + 500])))
    source = models.Source(
        kind=kept.kind,
        key=key,
        title=kept.title,
        url=kept.url,
        source_updated_at=kept.source_updated_at,
        weight=weight,
        version=new_version,
    )
    session.add(source)
    session.flush()
    rows: list[list[models.Symbol]] = []
    for f in data["files"]:
        file_row = models.File(
            source_id=source.id,
            path=f["path"],
            language=f["language"],
            hash=f["hash"],
            loc=f["loc"],
            content=f["content"],
        )
        session.add(file_row)
        session.flush()
        symbols = [
            models.Symbol(
                file_id=file_row.id,
                name=s["name"],
                kind=s["kind"],
                start_line=s["start"],
                end_line=s["end"],
                signature=s["signature"],
                embedding=_unvector(s["embedding"]),
                minhash=base64.b64decode(s["minhash"]) if s.get("minhash") else None,
            )
            for s in f["symbols"]
        ]
        session.add_all(symbols)
        rows.append(symbols)
    session.flush()
    if data["edges"]:
        session.execute(
            insert(models.Edge),
            [
                {"from_symbol_id": rows[a][b].id, "to_symbol_id": rows[c][d].id, "kind": kind}
                for a, b, c, d, kind in data["edges"]
            ],
        )
    from worker.dedupe import link_duplicates

    link_duplicates(session, source)
    snapshot(session, source)
    return source
