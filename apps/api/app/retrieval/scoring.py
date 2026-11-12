"""The final ranking of retrieved excerpts: several signals, never similarity alone.

    final = 0.45 * rerank + 0.20 * rrf + 0.15 * trust + 0.10 * freshness + 0.10 * hit_rate

Ties break by the newer source, the higher trust tier, the shorter excerpt, then an exact
match of an identifier in the query. Pure functions: no database, no clock but `now`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from app.schemas import CodeChunk

WEIGHTS = {"rerank": 0.45, "rrf": 0.20, "trust": 0.15, "freshness": 0.10, "hit_rate": 0.10}

# Source weight (3 primary, 2 secondary, 1 derived) as a 0-1 trust.
TRUST = {3: 1.0, 2: 0.7, 1: 0.4}
# Half-life of an excerpt's freshness, in days: code changes faster than prose.
HALF_LIFE_DAYS = {"code": 30.0, "docs": 90.0}
# Used when a source has no history of feedback yet.
NEUTRAL_HIT_RATE = 0.5
RRF_K = 60

_CODE_KINDS = {"function", "class", "method"}
# snake_case, CamelCase, dotted names and file paths: what a person pastes to find one thing.
_IDENTIFIER = re.compile(
    r"[A-Za-z_][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+"  # snake_case
    r"|[a-z]+[A-Z][A-Za-z0-9]*|[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+"  # camelCase, PascalCase
    r"|[\w-]+(?:\.[\w-]+)+(?:/[\w.-]+)*|[\w.-]+/[\w./-]+"  # a.b.c, path/to/file.py
)


def identifiers(query: str) -> set[str]:
    """Names in the query that look like code identifiers or file paths."""
    found: set[str] = set()
    for match in _IDENTIFIER.finditer(query):
        name = match.group(0).lower()
        if len(name) > 2:
            found.add(name)
        if "." in name and "/" not in name:  # Signer.derive_key also names derive_key
            found.update(part for part in name.split(".") if len(part) > 2)
    return found


def _aware(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def is_code(chunk: CodeChunk) -> bool:
    return chunk.kind in _CODE_KINDS


def freshness_weight(chunk: CodeChunk, now: datetime) -> float:
    """1 for something that changed just now, halving every half-life (30 days for code,
    90 for documents); 0.5 when nothing is known of its age."""
    changed = _aware(chunk.source_updated_at) or _aware(chunk.ingested_at)
    if changed is None:
        return 0.5
    age_days = max((now - changed).total_seconds() / 86400, 0.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS["code" if is_code(chunk) else "docs"])


def trust_weight(chunk: CodeChunk) -> float:
    return TRUST.get(chunk.weight or 2, TRUST[2])


def rrf_scores(chunks: Sequence[CodeChunk]) -> dict[int, float]:
    """Each excerpt's reciprocal-rank score from its place in `chunks` (the fused retrieval
    order), scaled so the top one is 1."""
    top = 1 / (RRF_K + 1)
    return {c.symbol_id: (1 / (RRF_K + rank + 1)) / top for rank, c in enumerate(chunks)}


def rerank_score(chunk: CodeChunk) -> float:
    """The cross-encoder's score (a logit) as 0-1, else the relevance judge's 0-10 score as
    0-1, else the similarity."""
    if chunk.rerank_score is not None:
        return 1 / (1 + math.exp(-max(min(chunk.rerank_score, 50.0), -50.0)))
    if chunk.relevance is not None:
        return max(0.0, min(chunk.relevance / 10, 1.0))
    return max(0.0, min(chunk.score, 1.0))


def final_score(
    chunk: CodeChunk,
    rrf: float,
    now: datetime,
    hit_rate: float = NEUTRAL_HIT_RATE,
) -> float:
    return (
        WEIGHTS["rerank"] * rerank_score(chunk)
        + WEIGHTS["rrf"] * rrf
        + WEIGHTS["trust"] * trust_weight(chunk)
        + WEIGHTS["freshness"] * freshness_weight(chunk, now)
        + WEIGHTS["hit_rate"] * hit_rate
    )


def rank(
    chunks: Sequence[CodeChunk],
    query: str,
    *,
    candidates: Sequence[CodeChunk] | None = None,
    hit_rates: Mapping[int, float] | None = None,
    now: datetime | None = None,
) -> list[tuple[CodeChunk, float]]:
    """`chunks` ordered best first, each with its final score. `candidates` is the fused
    retrieval order the RRF signal is read from (default: `chunks` themselves);
    `hit_rates` maps a source id to its historical precision, 0-1."""
    now = now or datetime.now(UTC)
    rrf = rrf_scores(candidates if candidates is not None else chunks)
    wanted = identifiers(query)
    rates = hit_rates or {}

    def has_identifier(chunk: CodeChunk) -> bool:
        if not wanted:
            return False
        haystack = f"{chunk.name}\n{chunk.file}\n{chunk.snippet}".lower()
        return any(name in haystack for name in wanted)

    scored = [
        (
            chunk,
            final_score(
                chunk,
                rrf.get(chunk.symbol_id, 0.0),
                now,
                rates.get(chunk.source_id or -1, NEUTRAL_HIT_RATE),
            ),
        )
        for chunk in chunks
    ]

    def order(item: tuple[CodeChunk, float]):
        chunk, score = item
        changed = _aware(chunk.source_updated_at) or _aware(chunk.ingested_at)
        return (
            -round(score, 6),  # equal scores, to six places, are ties
            -(changed.timestamp() if changed else 0.0),  # 1. the newer source
            -trust_weight(chunk),  # 2. the higher trust tier
            len(chunk.snippet),  # 3. the shorter excerpt: less noise
            0 if has_identifier(chunk) else 1,  # 4. an exact identifier match
        )

    return sorted(scored, key=order)


def smoothed_hit_rate(up: int, down: int) -> float:
    """A source's precision from the thumbs on answers that used it, with Laplace smoothing
    so a single vote does not decide: (up + 1) / (up + down + 2)."""
    return (up + 1) / (up + down + 2)
