"""The relevance gate: what to do when the best excerpt for a question scores poorly.

Two gates sit between retrieval and the model: the relevance judge's per-excerpt cut-off (an
LLM's 0-10 score; excerpts under it are dropped) and the similarity floor (cosine, 0.3). When
every excerpt is under them the model used to get an empty context, and the answer was a
refusal. The low-confidence path keeps the best few and says they are weak, so the model can
use one that does answer, or say what is missing, instead of being handed nothing.

The scores here are the judge's integers, not a calibrated probability, and the cosine
similarities of a small embedding model; neither means "0.5 is half right". The gate is set
from the scores observed on real queries (see evals/calibrate_gate.py), not from a guess.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from app.schemas import CodeChunk

# How many excerpts a low-confidence answer is given.
LOW_CONFIDENCE_CHUNKS = 3

LOW_CONFIDENCE_NOTE = """\
<low_confidence>
The excerpts below scored under Atlas's relevance gate for this question, so none of them may \
answer it. Use an excerpt only if it really does, cite it, and say the match is weak. If none \
answers the question, say what is missing and what came closest; if you are asked for a \
STATE, write STATE: ABSENT. Do not stretch an excerpt to fit the question.
</low_confidence>"""


def summarise(
    verdicts: Mapping[int, tuple[int, str]], candidates: Sequence[CodeChunk]
) -> tuple[int | None, float | None, list[int]]:
    """The best judge score, the best similarity, and every judge score (high to low)."""
    scores = sorted((v[0] for v in verdicts.values()), reverse=True)
    top_similarity = max((c.score for c in candidates), default=None)
    return (scores[0] if scores else None), top_similarity, scores


def is_low(top_score: int | None, gate: int) -> bool:
    """True when the best excerpt the judge saw scored under the gate. Nothing judged is not
    low: the judge being down says nothing about the excerpts."""
    return top_score is not None and top_score < gate


def low_confidence_pick(
    candidates: Sequence[CodeChunk],
    verdicts: Mapping[int, tuple[int, str]],
    limit: int = LOW_CONFIDENCE_CHUNKS,
) -> list[CodeChunk]:
    """The best few candidates, by judge score then similarity, with their scores set, for
    the model to be given although they scored low."""
    ranked = sorted(
        candidates,
        key=lambda c: (-(verdicts[c.symbol_id][0] if c.symbol_id in verdicts else -1), -c.score),
    )
    picked = []
    for chunk in ranked[:limit]:
        verdict = verdicts.get(chunk.symbol_id)
        picked.append(
            chunk.model_copy(
                update={"relevance": verdict[0], "relevance_reason": verdict[1] or None}
            )
            if verdict
            else chunk
        )
    return picked


def percentile(values: Sequence[float], pct: float) -> float:
    """The `pct`-th percentile (0-100) by linear interpolation; 0 for no values."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * pct / 100
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)
