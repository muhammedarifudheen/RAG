"""Health per source, live, with an action for each problem, and one overall score.

Per source: coverage (the share of logged answers that cited it), freshness and its trend,
staleness risk (refresh proposals against it), redundancy (its passages also found
elsewhere), trust (its weight and why), retrieval health (how often it is retrieved, how
relevant the judge found it, and how often it was retrieved but not used) and gaps (the
questions it was retrieved for but could not answer). The overall score is a weighted
average, kept over time for its sparkline."""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AnswerLog, File, HealthSnapshot, KnowledgeSignal, Source, Symbol
from app.services.freshness import category, label, threshold
from app.services.weights import LABELS, automatic_weight, source_weight

logger = logging.getLogger("atlas.health")

# How far back answers count, and how often the score is kept.
WINDOW_DAYS = 30
SNAPSHOT_EVERY = timedelta(hours=6)
HISTORY = 30
# Thresholds for the actions.
REDUNDANT = 0.3
LOW_PRECISION = 0.3
MIN_RETRIEVALS = 5

_FRESH_SCORE = {"fresh": 1.0, "recent": 0.7, "stale": 0.3, None: 0.5}


def _trust_evidence(source: Source) -> str:
    if source.weight is not None:
        return "set by the admin"
    host = (urlparse(source.url).hostname or "") if source.url else ""
    weight = automatic_weight(source.kind, source.url, source.title)
    if source.kind == "repo":
        return "source code: primary"
    if source.kind == "wikipedia":
        return "an encyclopedia: secondary"
    if weight == 3:
        return f"official documentation ({host})"
    if weight == 1:
        return "a summary or notes: derived"
    return f"{host or 'an upload'}: secondary"


def report(db: Session, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    since = now - timedelta(days=WINDOW_DAYS)
    sources = db.scalars(select(Source).order_by(Source.created_at.desc())).all()
    files = db.execute(select(File.path, File.source_id)).all()
    source_of = dict(files)

    # Passages, and how many are duplicates (or have duplicates pointing at them).
    passages = dict(
        db.execute(
            select(File.source_id, func.count(Symbol.id))
            .join(Symbol, Symbol.file_id == File.id)
            .where(Symbol.kind != "module")
            .group_by(File.source_id)
        ).all()
    )
    duplicated = dict(
        db.execute(
            select(File.source_id, func.count(Symbol.id))
            .join(Symbol, Symbol.file_id == File.id)
            .where(Symbol.duplicate_of.is_not(None))
            .group_by(File.source_id)
        ).all()
    )
    answers = db.scalars(select(AnswerLog).where(AnswerLog.created_at >= since)).all()
    refresh = defaultdict(int)
    for signal in db.scalars(select(KnowledgeSignal).where(KnowledgeSignal.kind == "refresh")):
        refresh[signal.subject] += signal.count

    retrieved = defaultdict(int)
    cited = defaultdict(int)
    relevance = defaultdict(list)
    gaps = defaultdict(list)
    for answer in answers:
        got = {source_of.get(r.get("file")) for r in answer.retrieved or []} - {None}
        used = {source_of.get(c.get("file")) for c in answer.cited or [] if c.get("verified")}
        used.discard(None)
        for r in answer.retrieved or []:
            sid = source_of.get(r.get("file"))
            if sid is not None and r.get("relevance") is not None:
                relevance[sid].append(r["relevance"])
        for sid in got:
            retrieved[sid] += 1
            if answer.state in ("absent", "partial") and sid not in used:
                gaps[sid].append({"question": answer.question, "suggestion": answer.suggestion})
        for sid in used:
            cited[sid] += 1

    total = len(answers)
    out = []
    for source in sources:
        kind = category(source.kind, source.url, "")
        fresh = label(source.created_at, kind, now)
        age = (now - source.created_at).days if source.created_at else None
        if fresh == "stale":
            trend = "degrading"
        elif (source.version or 1) > 1 and age is not None and age <= threshold(kind) / 3:
            trend = "improving"
        else:
            trend = "steady"
        count = passages.get(source.id, 0)
        redundancy = round(duplicated.get(source.id, 0) / count, 2) if count else 0.0
        weight = source_weight(source.kind, source.url, source.title, source.weight)
        hits = retrieved.get(source.id, 0)
        precision = round(cited.get(source.id, 0) / hits, 2) if hits else None
        coverage = round(cited.get(source.id, 0) / total, 2) if total else None
        mean_relevance = (
            round(sum(relevance[source.id]) / len(relevance[source.id]), 1)
            if relevance.get(source.id)
            else None
        )
        risk = refresh.get(source.title, 0)
        missing = gaps.get(source.id, [])[:5]

        actions = []
        if fresh == "stale" or risk:
            actions.append(
                {"kind": "reingest", "label": "Re-ingest", "detail": "Preview the changes first."}
            )
        if redundancy >= REDUNDANT:
            actions.append(
                {
                    "kind": "demote" if weight > 1 else "merge",
                    "label": "Demote to derived" if weight > 1 else "Remove this copy",
                    "detail": f"{round(redundancy * 100)}% of its passages are also in other sources.",
                }
            )
        if weight < 3:
            actions.append(
                {
                    "kind": "primary",
                    "label": "Add a primary source",
                    "detail": f"It is {LABELS[weight]}; find the code, spec or official docs behind it.",
                }
            )
        if missing:
            suggestions = list(dict.fromkeys(g["suggestion"] for g in missing if g["suggestion"]))[
                :3
            ]
            actions.append(
                {
                    "kind": "gap",
                    "label": "Add a source for its gaps",
                    "detail": f"{len(missing)} question(s) it was retrieved for but could not answer.",
                    "candidates": suggestions,
                }
            )
        if precision is not None and hits >= MIN_RETRIEVALS and precision < LOW_PRECISION:
            actions.append(
                {
                    "kind": "chunking",
                    "label": "Tune chunking",
                    "detail": f"Retrieved {hits} times but used in only {round(precision * 100)}%: "
                    "its passages may be too long or mix topics.",
                }
            )

        score = 100 * (
            0.25 * _FRESH_SCORE[fresh]
            + 0.2 * weight / 3
            + 0.2 * (1 - redundancy)
            + 0.2 * (precision if precision is not None else 0.7)
            + 0.15 * (min(1.0, coverage * 5) if coverage is not None else 0.5)
        )
        out.append(
            {
                "id": source.id,
                "title": source.title,
                "kind": source.kind,
                "url": source.url,
                "version": source.version or 1,
                "score": round(score),
                "coverage": coverage,
                "freshness": {"label": fresh, "age_days": age, "trend": trend},
                "staleness_risk": risk,
                "redundancy": redundancy,
                "trust": {
                    "weight": weight,
                    "label": LABELS[weight],
                    "evidence": _trust_evidence(source),
                },
                "retrieval": {
                    "retrieved": hits,
                    "cited": cited.get(source.id, 0),
                    "precision": precision,
                    "mean_relevance": mean_relevance,
                },
                "gaps": missing,
                "actions": actions,
            }
        )

    overall = round(sum(s["score"] for s in out) / len(out)) if out else 0
    history = _keep(db, overall, {"sources": len(out), "answers": total}, now)
    return {"score": overall, "answers": total, "history": history, "sources": out}


def _keep(db: Session, score: int, metrics: dict, now: datetime) -> list[dict]:
    """Keeps the score at most every SNAPSHOT_EVERY; returns the history, oldest first."""
    try:
        latest = db.scalars(select(HealthSnapshot).order_by(HealthSnapshot.at.desc())).first()
        if latest is None or now - latest.at >= SNAPSHOT_EVERY:
            db.add(HealthSnapshot(at=now, score=score, metrics=metrics))
            db.commit()
            if latest is not None and latest.score - score >= 10:
                from app.services.webhooks import emit

                emit("health", {"score": score, "was": latest.score, "metrics": metrics}, db)
        rows = db.scalars(
            select(HealthSnapshot).order_by(HealthSnapshot.at.desc()).limit(HISTORY)
        ).all()
        return [{"at": r.at.isoformat(), "score": r.score} for r in reversed(rows)]
    except Exception:
        logger.exception("could not keep the health score")
        db.rollback()
        return [{"at": now.isoformat(), "score": score}]
