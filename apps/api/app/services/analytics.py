"""Analytics over the answer log, queryable: analytics.query(metric, window, filter).

Metrics:
- top_questions: the most asked (candidates to cache or document better);
- failing: thumbs down, or citations that did not check out (candidates to fix);
- gaps: answered partly or not at all (candidates to ingest);
- slowest: by latency (candidates to optimise);
- sources: how often each source was retrieved and cited (to prune or promote);
- drift: week over week, the hit rate (answers with a checked citation), latency,
  faithfulness (checked / all citations) and approval (thumbs up / all feedback);
- feedback: the thumbs, with their reasons;
- budget: the latency budget: how many answers degraded, and per stage how often it was the
  first to breach and its median and 95th-percentile time (where to optimise first).
`filter` narrows by mode or state ("mode:ASK", "state:absent") or by words in the
question."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AnswerLog, File, Source

METRICS = ("top_questions", "failing", "gaps", "slowest", "sources", "drift", "feedback", "budget")


def _normal(question: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", question.lower())).strip()


def _rows(db: Session, window: int, filter: str | None) -> list[AnswerLog]:
    since = datetime.now(UTC) - timedelta(days=window)
    query = select(AnswerLog).where(AnswerLog.created_at >= since).order_by(AnswerLog.id.desc())
    rows = db.scalars(query.limit(20_000)).all()
    if not filter:
        return list(rows)
    field, _, value = filter.partition(":")
    if field == "mode" and value:
        return [r for r in rows if (r.mode or "").lower() == value.lower()]
    if field == "state" and value:
        return [r for r in rows if (r.state or "").lower() == value.lower()]
    words = filter.lower()
    return [r for r in rows if words in r.question.lower()]


def _failed(row: AnswerLog) -> str | None:
    if row.feedback == -1:
        return f"thumbs down{f': {row.feedback_reason}' if row.feedback_reason else ''}"
    if row.citations and row.verified < row.citations:
        return f"{row.citations - row.verified} of {row.citations} citations unchecked"
    return None


def query(
    db: Session, metric: str, window: int = 7, filter: str | None = None, limit: int = 10
) -> dict:
    if metric not in METRICS:
        raise ValueError(f"metric must be one of {', '.join(METRICS)}")
    window = max(1, min(window, 365))
    limit = max(1, min(limit, 100))
    if metric == "drift":
        return {"metric": metric, "window": window, "rows": _drift(db, window, filter)}
    rows = _rows(db, window, filter)
    out: list[dict]
    if metric == "top_questions":
        counts = Counter(_normal(r.question) for r in rows)
        example = {}
        for r in rows:
            example.setdefault(_normal(r.question), r.question)
        out = [{"question": example[q], "count": n} for q, n in counts.most_common(limit)]
    elif metric == "failing":
        out = [
            {"question": r.question, "why": why, "state": r.state, "at": r.created_at.isoformat()}
            for r in rows
            if (why := _failed(r))
        ][:limit]
    elif metric == "gaps":
        counts = Counter(_normal(r.question) for r in rows if r.state in ("absent", "partial"))
        example = {_normal(r.question): r for r in rows}
        out = [
            {
                "question": example[q].question,
                "count": n,
                "state": example[q].state,
                "suggestion": example[q].suggestion,
            }
            for q, n in counts.most_common(limit)
        ]
    elif metric == "budget":
        return {
            "metric": metric,
            "window": window,
            "filter": filter,
            "summary": _budget_summary(rows),
            "rows": _budget_stages(rows)[:limit],
        }
    elif metric == "slowest":
        timed = sorted((r for r in rows if r.latency_ms), key=lambda r: -r.latency_ms)
        out = [
            {"question": r.question, "latency_ms": r.latency_ms, "mode": r.mode}
            for r in timed[:limit]
        ]
    elif metric == "sources":
        out = _sources(db, rows)[:limit]
    else:  # feedback
        rated = [r for r in rows if r.feedback]
        out = [
            {
                "question": r.question,
                "rating": "up" if r.feedback > 0 else "down",
                "reason": r.feedback_reason,
            }
            for r in rated[:limit]
        ]
    return {"metric": metric, "window": window, "filter": filter, "rows": out}


def _percentile(values: list[float], pct: float) -> float:
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100
    low, high = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def _budget_summary(rows: list[AnswerLog]) -> dict:
    stats = [r.stats for r in rows if r.stats]
    degraded = sum(1 for s in stats if s.get("degraded"))
    breached = sum(1 for s in stats if s.get("budget_breached"))
    return {
        "answers": len(rows),
        "with_stats": len(stats),
        "degraded": degraded,
        "degraded_pct": round(100 * degraded / len(stats), 1) if stats else None,
        "over_budget_pct": round(100 * breached / len(stats), 1) if stats else None,
    }


def _budget_stages(rows: list[AnswerLog]) -> list[dict]:
    """Per stage: answers where it breached, how often it was the first to, the median and p95
    of its time, and its budget now. Most-breached first."""
    from app.config import settings

    stats = [r.stats for r in rows if r.stats]
    first = Counter(s["budget_breached"] for s in stats if s.get("budget_breached"))
    breached = Counter(b for s in stats for b in set(s.get("breaches") or []))
    times: dict[str, list[float]] = defaultdict(list)
    for s in stats:
        for stage, ms in (s.get("stage_ms") or {}).items():
            times[stage].append(float(ms))
    out = []
    for stage in sorted(set(breached) | set(times), key=lambda x: (-breached.get(x, 0), x)):
        values = times.get(stage, [])
        out.append(
            {
                "stage": stage,
                "breached": breached.get(stage, 0),
                "breached_pct": round(100 * breached.get(stage, 0) / len(stats), 1)
                if stats
                else None,
                "first_breach": first.get(stage, 0),
                "p50_ms": round(_percentile(values, 50), 1) if values else None,
                "p95_ms": round(_percentile(values, 95), 1) if values else None,
                "budget_ms": getattr(settings, f"budget_{stage}_ms", None),
            }
        )
    return out


def _sources(db: Session, rows: list[AnswerLog]) -> list[dict]:
    owner = dict(
        db.execute(select(File.path, Source.title).join(Source, Source.id == File.source_id)).all()
    )
    retrieved: Counter[str] = Counter()
    cited: Counter[str] = Counter()
    for r in rows:
        for title in {owner.get(x.get("file")) for x in r.retrieved or []} - {None}:
            retrieved[title] += 1
        for title in {owner.get(c.get("file")) for c in r.cited or [] if c.get("verified")} - {
            None
        }:
            cited[title] += 1
    titles = set(owner.values())
    return sorted(
        (
            {
                "source": t,
                "retrieved": retrieved[t],
                "cited": cited[t],
                "precision": round(cited[t] / retrieved[t], 2) if retrieved[t] else None,
            }
            for t in titles
        ),
        key=lambda x: (-x["cited"], -x["retrieved"], x["source"]),
    )


def _drift(db: Session, window: int, filter: str | None) -> list[dict]:
    """Week by week over the window: answers, hit rate, mean latency, faithfulness and
    approval, and each one's change from the week before."""
    rows = _rows(db, max(window, 14), filter)
    weeks: dict[str, list[AnswerLog]] = defaultdict(list)
    for r in rows:
        year, week, _ = r.created_at.isocalendar()
        weeks[f"{year}-W{week:02d}"].append(r)
    out = []
    for name in sorted(weeks):
        group = weeks[name]
        citations = sum(r.citations for r in group)
        timed = [r.latency_ms for r in group if r.latency_ms]
        rated = [r.feedback for r in group if r.feedback]
        out.append(
            {
                "week": name,
                "answers": len(group),
                "hit_rate": round(sum(1 for r in group if r.verified) / len(group), 2),
                "latency_ms": round(sum(timed) / len(timed)) if timed else None,
                "faithfulness": round(sum(r.verified for r in group) / citations, 2)
                if citations
                else None,
                "approval": round(sum(1 for f in rated if f > 0) / len(rated), 2)
                if rated
                else None,
            }
        )
    for previous, current in pairwise(out):
        current["change"] = {
            k: round(current[k] - previous[k], 2)
            for k in ("hit_rate", "latency_ms", "faithfulness", "approval")
            if current[k] is not None and previous[k] is not None
        }
    return out


def as_text(result: dict) -> str:
    """A query's result as lines, for the research agent."""
    rows = result["rows"]
    if not rows:
        return f"No data for {result['metric']} in the last {result['window']} days."
    head = f"{result['metric']} over the last {result['window']} days:"
    return "\n".join(
        [
            head,
            *(
                "- " + ", ".join(f"{k}: {v}" for k, v in row.items() if v is not None)
                for row in rows
            ),
        ]
    )


def as_csv(result: dict) -> str:
    rows = result["rows"]
    buffer = io.StringIO()
    if rows:
        keys = list(dict.fromkeys(k for row in rows for k in row if k != "change"))
        writer = csv.DictWriter(buffer, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return buffer.getvalue()
