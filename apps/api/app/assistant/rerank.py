"""Reranking: a relevance judge scores each candidate excerpt 0-10 for the question; the
excerpts are then ordered by that score and those under a cut-off are left out."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from app.schemas import CodeChunk

# What the judge sees of an excerpt: its place, then its code, up to this many characters.
CHUNK_CHARS = 1500
# The ranker sees all the excerpts in one message, so less of each.
PASSAGE_CHARS = 1200

_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)
_SCORE = re.compile(r'"score"\s*:\s*"?(\d+(?:\.\d+)?)')


def chunk_text(chunk: CodeChunk, limit: int = CHUNK_CHARS) -> str:
    head = f"{chunk.file}:{chunk.start_line}-{chunk.snippet_end_line} ({chunk.kind} {chunk.name})"
    return f"{head}\n{chunk.snippet[:limit]}"


_LIST = re.compile(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]")
_JUSTIFICATION = re.compile(r"justification\**\s*[:\-—]?\s*(.+)", re.IGNORECASE)


def parse_ranking(reply: str, count: int) -> tuple[list[int], str] | None:
    """The ranker's passage numbers, best first, as 0-based positions: each of the `count`
    passages once (any it left out keep their order at the end); with its justification
    for the top pick. None when the reply holds no list of numbers."""
    reply = reply or ""
    numbers: list[int] | None = None
    justification = ""
    found = re.search(r"\{.*\}", reply, re.DOTALL)
    if found:
        try:
            data = json.loads(found.group(0))
        except ValueError:
            data = None
        if isinstance(data, dict):
            for value in data.values():
                if isinstance(value, list) and numbers is None:
                    numbers = [
                        int(float(v))
                        for v in value
                        if isinstance(v, (int, float))
                        or (isinstance(v, str) and v.strip().isdigit())
                    ]
                elif isinstance(value, str) and not justification:
                    justification = value
    if not numbers:
        listed = _LIST.search(reply)
        if not listed:
            return None
        numbers = json.loads(listed.group(0))
        tail = _JUSTIFICATION.search(reply[listed.end() :])
        justification = tail.group(1) if tail else ""
    order: list[int] = []
    for number in numbers:
        if 1 <= number <= count and number - 1 not in order:
            order.append(number - 1)
    if not order:
        return None
    order += [i for i in range(count) if i not in order]
    return order, justification.strip().strip('"*').strip()[:300]


def parse_judgement(reply: str) -> tuple[int, str] | None:
    """The judge's {"score": <int>, "reason": "..."}, with the score kept to 0-10; None
    when the reply holds no score."""
    for found in _OBJECT.finditer(reply or ""):
        try:
            data = json.loads(found.group(0))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("score"), (int, float, str)):
            try:
                score = round(float(data["score"]))
            except ValueError:
                continue
            reason = data.get("reason")
            return max(0, min(10, score)), (reason.strip()[:300] if isinstance(reason, str) else "")
    # A reason with an unescaped quote breaks the JSON; the score alone still counts.
    found = _SCORE.search(reply or "")
    return (max(0, min(10, round(float(found.group(1))))), "") if found else None


def rerank(
    chunks: Sequence[CodeChunk],
    verdicts: Mapping[int, tuple[int, str]],
    cutoff: int,
    limit: int,
) -> list[CodeChunk]:
    """The judged excerpts scoring at least `cutoff`, best first (ties by similarity), then,
    if the judge reached fewer than half, the others in their search order; at most
    `limit`. Without verdicts, the search order."""
    if not verdicts:
        return list(chunks[:limit])
    judged = [
        chunk.model_copy(
            update={
                "relevance": verdicts[chunk.symbol_id][0],
                "relevance_reason": verdicts[chunk.symbol_id][1] or None,
            }
        )
        for chunk in chunks
        if chunk.symbol_id in verdicts and verdicts[chunk.symbol_id][0] >= cutoff
    ]
    judged.sort(key=lambda c: (-(c.relevance or 0), -c.score))
    # Judged as a fair sample, the rest are no likelier to help than those it turned down.
    unjudged = (
        [c for c in chunks if c.symbol_id not in verdicts]
        if len(verdicts) * 2 < len(chunks)
        else []
    )
    return [*judged, *unjudged][:limit]
