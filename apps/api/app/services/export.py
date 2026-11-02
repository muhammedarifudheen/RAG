"""Exports: the answers as JSONL (question, answer, citations) for evaluation, and the
AUDIT mode's report as Markdown."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnswerLog, File, Source
from app.services.explore import audit_answer
from app.services.weights import LABELS, source_weight


def qa_lines(db: Session, since: datetime | None = None, limit: int = 10_000) -> Iterator[str]:
    """One JSON object a line, oldest first: id, created_at, question, answer, state,
    confidence, mode, citations ({ref, file, start_line, end_line, verified}) and the
    sources the answer was given."""
    query = select(AnswerLog).order_by(AnswerLog.id)
    if since is not None:
        query = query.where(AnswerLog.created_at >= since)
    for row in db.scalars(query.limit(limit)):
        yield (
            json.dumps(
                {
                    "id": row.id,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "question": row.question,
                    "answer": row.answer,
                    "state": row.state,
                    "confidence": row.confidence,
                    "mode": row.mode,
                    "route": row.route,
                    "citations": row.cited or [],
                    "sources": row.sources or [],
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def audit_markdown(db: Session) -> str:
    """The knowledge base's report: what it holds, its health, and the latest audit."""
    rows = db.execute(
        select(
            Source.title, Source.kind, Source.url, Source.weight, Source.created_at,
            func.count(File.id),
        )
        .outerjoin(File, File.source_id == Source.id)
        .group_by(Source.id)
        .order_by(Source.created_at)
    ).all()  # fmt: skip
    lines = [
        "# Atlas knowledge audit",
        "",
        f"Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC.",
        "",
        f"## Sources ({len(rows)})",
        "",
    ]
    if rows:
        lines += ["| Source | Kind | Weight | Files | Added |", "| --- | --- | --- | --- | --- |"]
        for title, kind, url, override, created, files in rows:
            weight = source_weight(kind, url, title, override)
            name = f"[{title}]({url})" if url else title
            lines.append(
                f"| {name.replace('|', '/')} | {kind} | {weight} {LABELS[weight]} | {files} "
                f"| {created:%Y-%m-%d} |"
            )
    else:
        lines.append("Nothing has been ingested yet.")
    lines += ["", "## Health", "", audit_answer(db), ""]
    return "\n".join(lines)
