"""How many excerpts a question deserves: few for a simple fact, more to compare."""

from __future__ import annotations

import re

# Never more than this go to the model, however broad the question.
MAX_CHUNKS = 8
SIMPLE, SYNTHESIS, COMPARE = 3, 5, 8

_COMPARE = re.compile(
    r"\b(compare|comparison|versus|vs\.?|differences?|differ|contrast|pros and cons|"
    r"all (?:the )?(?:ways|options|methods|types)|every)\b",
    re.I,
)
_SYNTHESIS = re.compile(
    r"\b(how|why|explain|walk me through|describe|summari[sz]e|overview|flow|works?|"
    r"architecture|design|steps|process|trade-?offs?)\b",
    re.I,
)


def adaptive_top_k(question: str) -> int:
    """3 for a short factual question, 5 to explain or synthesise, 8 (the cap) to compare
    many things. The cap holds: the spec's 12 for "compare all" would send too much."""
    text = question.strip()
    words = len(text.split())
    if _COMPARE.search(text) or words > 60:
        return COMPARE
    if _SYNTHESIS.search(text) or words > 18:
        return SYNTHESIS
    return SIMPLE


def capped(top_k: int) -> int:
    return max(1, min(top_k, MAX_CHUNKS))
