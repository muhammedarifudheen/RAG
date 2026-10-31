"""The knowledge base improving itself: every answer is logged (question, sources, how well
they answered it); topics answered partly or not at all three times or more become wanted
sources; an outdated source beside a newer one on the same topic is proposed for refresh;
and a short knowledge-health note is read from all of it."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from contextlib import suppress
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.embedding import Embedder
from app.models import AnswerLog, File, KnowledgeSignal, Source

logger = logging.getLogger("atlas.api.knowledge")

# Questions this close in meaning (cosine distance) are the same topic.
SAME_TOPIC = 0.2
# A topic answered partly or not at all this many times becomes a wanted source.
WANTED_AFTER = 3
# A source this much older than another on the same topic is proposed for refresh.
OUTDATED = timedelta(days=180)
SHORT = ("partial", "absent")


def log_answer(
    db: Session, embedder: Embedder, data: dict, chat_id: str | None
) -> AnswerLog | None:
    """Logs a finished answer and updates the signals it adds to. Never raises: the
    answer matters more than its log."""
    question = (data.get("question") or "").strip()
    if not question or data.get("route") in ("image", "chat"):
        return None
    try:
        chunks = data.get("chunks") or []
        files = sorted({c["file"] for c in chunks})
        titles = _titles(db, files)
        citations = data.get("citations") or []
        row = AnswerLog(
            chat_id=(chat_id or "")[:64] or None,
            question=question[:2000],
            state=data.get("epistemic"),
            route=data.get("route"),
            sources=[{"file": f, "title": titles.get(f)} for f in files],
            top_score=max((c.get("score", 0) for c in chunks), default=None),
            confidence=(data.get("confidence") or {}).get("level"),
            verified=sum(1 for c in citations if c.get("verified")),
            citations=len(citations),
            embedding=embedder.embed(question),
        )
        db.add(row)
        db.flush()
        if row.state in SHORT:
            _signal_wanted(db, row)
        _propose_refresh(db, files, row.state)
        db.commit()
        return row
    except Exception:
        logger.exception("could not log the answer")
        _rollback(db)
        return None


def note_suggestion(db: Session, question: str, chat_id: str | None, url: str | None) -> None:
    """Keeps the gap finder's suggested source with the latest log of the question."""
    if not url:
        return
    try:
        row = db.scalars(
            select(AnswerLog)
            .where(AnswerLog.question == question.strip()[:2000])
            .order_by(AnswerLog.id.desc())
        ).first()
        if row is not None:
            row.suggestion = url
            db.commit()
    except Exception:
        logger.exception("could not keep the suggestion")
        _rollback(db)


def _rollback(db: Session) -> None:
    with suppress(Exception):
        db.rollback()


def _titles(db: Session, files: Sequence[str]) -> dict[str, str]:
    if not files:
        return {}
    rows = db.execute(
        select(File.path, Source.title)
        .join(Source, Source.id == File.source_id)
        .where(File.path.in_(files))
    ).all()
    return dict(rows)


def _signal_wanted(db: Session, row: AnswerLog) -> None:
    """Three or more partial or absent answers on the topic: a wanted source."""
    distance = AnswerLog.embedding.cosine_distance(row.embedding)
    times = db.scalar(
        select(func.count(AnswerLog.id)).where(
            AnswerLog.state.in_(SHORT), AnswerLog.embedding.is_not(None), distance < SAME_TOPIC
        )
    )
    if (times or 0) < WANTED_AFTER:
        return
    near = KnowledgeSignal.embedding.cosine_distance(row.embedding)
    signal = db.scalars(
        select(KnowledgeSignal)
        .where(KnowledgeSignal.kind == "wanted", near < SAME_TOPIC)
        .order_by(near)
    ).first()
    if signal is None:
        db.add(
            KnowledgeSignal(
                kind="wanted",
                subject=row.question[:500],
                detail="Answered partly or not at all",
                count=times,
                embedding=row.embedding,
            )
        )
    else:
        signal.count = times
        signal.last_seen = datetime.now(UTC)


def _propose_refresh(db: Session, files: Sequence[str], state: str | None) -> None:
    """Sources on the same answer added far apart in time, or disagreeing: refresh the older."""
    if not files:
        return
    sources = db.execute(
        select(Source.title, Source.created_at, Source.url)
        .join(File, File.source_id == Source.id)
        .where(File.path.in_(files))
        .distinct()
    ).all()
    if len(sources) < 2:
        return
    sources = sorted(sources, key=lambda s: s.created_at)
    oldest, newest = sources[0], sources[-1]
    if state == "conflicted":
        why = f"Disagrees with {newest.title}, which is newer"
    elif newest.created_at - oldest.created_at > OUTDATED:
        why = f"Added {(newest.created_at - oldest.created_at).days} days before {newest.title}"
    else:
        return
    signal = db.scalars(
        select(KnowledgeSignal).where(
            KnowledgeSignal.kind == "refresh", KnowledgeSignal.subject == oldest.title
        )
    ).first()
    if signal is None:
        db.add(KnowledgeSignal(kind="refresh", subject=oldest.title, detail=why))
    else:
        signal.count += 1
        signal.detail = why
        signal.last_seen = datetime.now(UTC)


def knowledge_health(db: Session, chat_id: str | None = None) -> dict:
    """The note: the top 3 recurring gaps, the top 3 sources to add or refresh, and one
    question answered surprisingly well; for one chat, or for everything logged."""
    logs = select(AnswerLog)
    if chat_id:
        logs = logs.where(AnswerLog.chat_id == chat_id)
    rows = db.scalars(logs.order_by(AnswerLog.id.desc()).limit(500)).all()

    signals = db.scalars(
        select(KnowledgeSignal).order_by(KnowledgeSignal.count.desc(), KnowledgeSignal.id)
    ).all()
    wanted = [s for s in signals if s.kind == "wanted"]
    gaps: list[dict] = []
    if chat_id:
        for row in rows:
            if row.state in SHORT and all(g["question"] != row.question for g in gaps):
                gaps.append({"question": row.question, "times": _times(db, row)})
        gaps.sort(key=lambda g: -g["times"])
    else:
        gaps = [{"question": s.subject, "times": s.count} for s in wanted]
    gaps = gaps[:3]

    to_add: list[dict] = []
    suggested: dict[str, int] = {}
    for row in rows:
        if row.suggestion:
            suggested[row.suggestion] = suggested.get(row.suggestion, 0) + 1
    for url, times in sorted(suggested.items(), key=lambda item: -item[1]):
        to_add.append({"action": "add", "source": url, "why": f"Suggested for {times} gap(s)"})
    for signal in signals:
        if signal.kind == "refresh":
            to_add.append({"action": "refresh", "source": signal.subject, "why": signal.detail})
    to_add = to_add[:3]

    # Surprisingly well: known and fully checked, from the least similar excerpts.
    good = [
        r
        for r in rows
        if r.state == "known" and r.citations and r.verified == r.citations and r.top_score
    ]
    best = min(good, key=lambda r: r.top_score, default=None)
    return {
        "scope": "chat" if chat_id else "all",
        "answers": len(rows),
        "gaps": gaps,
        "sources": to_add,
        "well_answered": {"question": best.question, "score": round(best.top_score, 2)}
        if best
        else None,
    }


def _times(db: Session, row: AnswerLog) -> int:
    if row.embedding is None:
        return 1
    distance = AnswerLog.embedding.cosine_distance(row.embedding)
    return (
        db.scalar(
            select(func.count(AnswerLog.id)).where(
                AnswerLog.state.in_(SHORT), AnswerLog.embedding.is_not(None), distance < SAME_TOPIC
            )
        )
        or 1
    )


def health_note(health: dict) -> str:
    """The knowledge-health note in Markdown."""
    lines = ["**Knowledge health**", "", "Top recurring gaps:"]
    lines += [f"- {g['question']} ({g['times']}×)" for g in health["gaps"]] or ["- none yet"]
    lines += ["", "Sources to add or refresh:"]
    lines += [
        f"- {'Add' if s['action'] == 'add' else 'Refresh'} {s['source']}: {s['why']}"
        for s in health["sources"]
    ] or ["- none yet"]
    well = health["well_answered"]
    lines += ["", "Answered surprisingly well:"]
    lines += [f"- {well['question']}" if well else "- nothing stands out yet"]
    return "\n".join(lines)


def export_log(db: Session) -> dict:
    """The log and signals, without embeddings (recomputed on import)."""
    answers = db.scalars(select(AnswerLog).order_by(AnswerLog.id)).all()
    signals = db.scalars(select(KnowledgeSignal).order_by(KnowledgeSignal.id)).all()
    return {
        "answers": [
            {
                "created_at": a.created_at.isoformat(),
                "chat_id": a.chat_id,
                "question": a.question,
                "state": a.state,
                "route": a.route,
                "sources": a.sources,
                "top_score": a.top_score,
                "confidence": a.confidence,
                "verified": a.verified,
                "citations": a.citations,
                "suggestion": a.suggestion,
            }
            for a in answers
        ],
        "signals": [
            {
                "kind": s.kind,
                "subject": s.subject,
                "detail": s.detail,
                "count": s.count,
                "created_at": s.created_at.isoformat(),
                "last_seen": s.last_seen.isoformat(),
            }
            for s in signals
        ],
    }


def import_log(db: Session, embedder: Embedder, payload: dict) -> int:
    """Restores an exported log into an empty one (after the free server starts afresh);
    returns how many answers were restored, 0 if the log already holds some."""
    if db.scalar(select(func.count(AnswerLog.id))):
        return 0
    answers = payload.get("answers") or []
    for a in answers:
        db.add(
            AnswerLog(
                created_at=datetime.fromisoformat(a["created_at"]),
                chat_id=a.get("chat_id"),
                question=a["question"],
                state=a.get("state"),
                route=a.get("route"),
                sources=a.get("sources") or [],
                top_score=a.get("top_score"),
                confidence=a.get("confidence"),
                verified=a.get("verified") or 0,
                citations=a.get("citations") or 0,
                suggestion=a.get("suggestion"),
                embedding=embedder.embed(a["question"]),
            )
        )
    for s in payload.get("signals") or []:
        db.add(
            KnowledgeSignal(
                kind=s["kind"],
                subject=s["subject"],
                detail=s.get("detail"),
                count=s.get("count") or 1,
                created_at=datetime.fromisoformat(s["created_at"]),
                last_seen=datetime.fromisoformat(s["last_seen"]),
                embedding=embedder.embed(s["subject"]) if s["kind"] == "wanted" else None,
            )
        )
    db.commit()
    return len(answers)
