"""Retrieval and answer metrics: pure functions, no network, so they can be tested."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

KS = (1, 3, 5, 10)

# Phrases with which an answer declines, for a question the knowledge base cannot answer.
_DECLINES = re.compile(
    r"don['’]t have that|do not have|not in the knowledge base|no (?:information|mention)|"
    r"cannot (?:find|answer)|can['’]t (?:find|answer)|doesn['’]t (?:say|cover|contain)|"
    r"not covered",
    re.I,
)


@dataclass(frozen=True)
class Target:
    """Something a good answer must be found in: a file, optionally a line range."""

    file: str
    start: int | None = None
    end: int | None = None

    @classmethod
    def parse(cls, raw: str | dict) -> Target:
        if isinstance(raw, str):
            return cls(raw)
        lines = raw.get("lines") or [None, None]
        return cls(raw["file"], lines[0], lines[1])


@dataclass(frozen=True)
class Hit:
    """A retrieved excerpt."""

    file: str
    start: int
    end: int


def matches(hit: Hit, target: Target) -> bool:
    """The hit is in the target's file (a path suffix, so `search.py` matches
    `apps/api/app/services/search.py`) and, when the target has lines, overlaps them."""
    path, wanted = hit.file.replace("\\", "/"), target.file.replace("\\", "/")
    if not (path == wanted or path.endswith("/" + wanted)):
        return False
    if target.start is None or target.end is None:
        return True
    return hit.start <= target.end and hit.end >= target.start


def found_at(hits: Sequence[Hit], target: Target) -> int | None:
    """The 1-based rank of the first hit matching the target, if any."""
    for rank, hit in enumerate(hits, 1):
        if matches(hit, target):
            return rank
    return None


@dataclass
class Retrieval:
    hit_at: dict[int, float] = field(default_factory=dict)  # 1 if any target in the top k
    recall_at: dict[int, float] = field(default_factory=dict)  # share of targets in the top k
    reciprocal_rank: float = 0.0  # 1 / rank of the first relevant hit
    ndcg_at: dict[int, float] = field(default_factory=dict)


def score_retrieval(
    hits: Sequence[Hit], targets: Sequence[Target], ks: Iterable[int] = KS
) -> Retrieval:
    """Binary-relevance metrics. A hit is relevant if it matches a target not already found by
    a higher-ranked hit; recall counts how many distinct targets were found."""
    result = Retrieval()
    ranks = [found_at(hits, t) for t in targets]
    first = min((r for r in ranks if r is not None), default=None)
    result.reciprocal_rank = 1 / first if first else 0.0
    # A target is credited once, to the first hit that matches it: further excerpts from the
    # same file add nothing, so DCG can never exceed the ideal (one hit per target).
    open_targets = list(targets)
    relevant_flags = []
    for hit in hits:
        gained = next((t for t in open_targets if matches(hit, t)), None)
        if gained is not None:
            open_targets.remove(gained)
        relevant_flags.append(gained is not None)
    for k in ks:
        result.hit_at[k] = 1.0 if first is not None and first <= k else 0.0
        result.recall_at[k] = (
            sum(1 for r in ranks if r is not None and r <= k) / len(targets) if targets else 0.0
        )
        dcg = sum(1 / math.log2(i + 2) for i, rel in enumerate(relevant_flags[:k]) if rel)
        ideal = sum(1 / math.log2(i + 2) for i in range(min(len(targets), k)))
        result.ndcg_at[k] = dcg / ideal if ideal else 0.0
    return result


def must_include_coverage(answer: str, phrases: Sequence[str]) -> float:
    """The share of required phrases present in the answer (case-insensitive)."""
    if not phrases:
        return 1.0
    text = answer.lower()
    return sum(1 for p in phrases if p.lower() in text) / len(phrases)


def declined(answer: str, epistemic: str | None = None, citations: int = 0) -> bool:
    """Whether the answer declines to answer from the sources."""
    if epistemic == "absent":
        return True
    return bool(_DECLINES.search(answer)) and citations == 0


def citation_precision(citations: Sequence[dict], targets: Sequence[Target]) -> float | None:
    """Of the answer's citations, the share that are verified (the cited lines were shown to
    the model) and point at a target. None when the answer cites nothing."""
    if not citations:
        return None
    good = 0
    for c in citations:
        hit = Hit(c["file"], int(c["start_line"]), int(c["end_line"]))
        if c.get("verified") and any(matches(hit, t) for t in targets):
            good += 1
    return good / len(citations)


def percentile(values: Sequence[float], pct: float) -> float:
    """The pct-th percentile (0-100) by linear interpolation; 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    pos = (len(ordered) - 1) * pct / 100
    low, high = math.floor(pos), math.ceil(pos)
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def mean(values: Iterable[float | None]) -> float:
    kept = [v for v in values if v is not None]
    return sum(kept) / len(kept) if kept else 0.0
