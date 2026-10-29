"""Reranking: a relevance judge scores each candidate excerpt 0-10 for the question; the
excerpts are then ordered by that score and those under a cut-off are left out."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence

from app.schemas import CodeChunk

# What the judge sees of an excerpt: its place, then its code, up to this many characters.
CHUNK_CHARS = 3000

_OBJECT = re.compile(r"\{.*?\}", re.DOTALL)
_SCORE = re.compile(r'"score"\s*:\s*"?(\d+(?:\.\d+)?)')


def chunk_text(chunk: CodeChunk) -> str:
    head = f"{chunk.file}:{chunk.start_line}-{chunk.snippet_end_line} ({chunk.kind} {chunk.name})"
    return f"{head}\n{chunk.snippet[:CHUNK_CHARS]}"


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
    """The judged excerpts scoring at least `cutoff`, best first (ties by similarity), then
    any the judge did not reach in their search order; at most `limit`. Without verdicts,
    the search order."""
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
    unjudged = [c for c in chunks if c.symbol_id not in verdicts]
    return [*judged, *unjudged][:limit]
