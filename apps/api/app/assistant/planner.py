"""Query planning for retrieval: a fast model turns the question into several searches
(the question cleaned up, its keywords, a hypothetical answer for HyDE, and a broader or
narrower variant), and their results are fused into one ranking."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from app.schemas import CodeChunk

MAX_QUERIES = 4
# Reciprocal rank fusion's constant: higher evens out the lists' top places.
RRF_K = 60

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def parse_queries(reply: str, question: str) -> list[str]:
    """The planner's {"queries": [...]}, with the question itself first; just the question
    when the reply is not that JSON."""
    queries: list[str] = []
    found = _OBJECT.search(reply or "")
    if found:
        try:
            planned = json.loads(found.group(0)).get("queries", [])
        except (ValueError, AttributeError):
            planned = []
        if isinstance(planned, list):
            queries = [q.strip() for q in planned if isinstance(q, str) and q.strip()]
    unique: list[str] = []
    seen: set[str] = set()
    for query in [question.strip(), *queries[:MAX_QUERIES]]:
        key = " ".join(re.findall(r"\w+", query.lower()))  # "What is X?" = "what is x"
        if query and key not in seen:
            seen.add(key)
            unique.append(query[:500])
    return unique


def fuse(results: Sequence[Sequence[CodeChunk]], limit: int) -> list[CodeChunk]:
    """One ranking from several searches' results, by reciprocal rank fusion: an excerpt
    found near the top by several queries comes first. Each keeps its best similarity
    score, so relevance thresholds still mean the same."""
    ranked: dict[int, float] = {}
    best: dict[int, CodeChunk] = {}
    for result in results:
        for rank, chunk in enumerate(result):
            ranked[chunk.symbol_id] = ranked.get(chunk.symbol_id, 0.0) + 1 / (RRF_K + rank + 1)
            if chunk.symbol_id not in best or chunk.score > best[chunk.symbol_id].score:
                best[chunk.symbol_id] = chunk
    order = sorted(ranked, key=lambda symbol: (-ranked[symbol], -best[symbol].score))
    return [best[symbol] for symbol in order[:limit]]
