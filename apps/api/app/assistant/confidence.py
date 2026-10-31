"""How far an answer can be trusted: from how relevant its excerpts were and how much of
it is cited to lines that check out."""

from __future__ import annotations

import re
from collections.abc import Sequence

from app.schemas import Citation, CodeChunk, Confidence

_MARK = "⁣cite⁣"
_CITED = re.compile(r"\[[^\[\]\n]+:\d+(?:-\d+)?[^\[\]\n]*\]")


def coverage(answer: str) -> float:
    """The share of the answer's sentences (of six words or more) that carry a citation."""
    prose = re.sub(r"```.*?```", " ", answer, flags=re.DOTALL)
    # Citations hold full stops ("signer.py"): mark them before splitting sentences.
    marked = _CITED.sub(f" {_MARK} ", prose)
    pieces = [p.strip() for p in re.split(r"(?<=[.!?])\s+|\n+", marked) if p.strip()]
    sentences: list[tuple[int, bool]] = []  # (words, cited)
    for piece in pieces:
        tokens = piece.split()
        lead = 0
        while lead < len(tokens) and tokens[lead] == _MARK:
            lead += 1
        if lead and sentences:
            # A citation just after a full stop belongs to the sentence before it.
            sentences[-1] = (sentences[-1][0], True)
        rest = tokens[lead:]
        words = sum(1 for token in rest if token != _MARK)
        if words:
            sentences.append((words, _MARK in rest))
    stated = [s for s in sentences if s[0] >= 6]
    if not stated:
        return 1.0 if _MARK in marked else 0.0
    return sum(1 for s in stated if s[1]) / len(stated)


def confidence(
    answer: str,
    chunks: Sequence[CodeChunk],
    citations: Sequence[Citation],
    state: str | None = None,
) -> Confidence | None:
    """High, medium or low for an answer from the knowledge base, with why; None for one
    that used no excerpts (general knowledge, chat, pictures) or found nothing. An
    inferred, partial or conflicted answer is never rated high."""
    if not chunks or state == "absent":
        return None
    judged = [c.relevance for c in chunks if c.relevance is not None]
    if judged:
        top = sorted(judged, reverse=True)[:3]
        relevance = sum(top) / len(top) / 10
    else:
        # Cosine similarity: about 0.3 is unrelated, 0.7 a close match.
        relevance = max(0.0, min(1.0, (max(c.score for c in chunks) - 0.3) / 0.4))
    verified = sum(c.verified for c in citations)
    checked = verified / len(citations) if citations else 0.0
    covered = coverage(answer)
    capped = state in ("inferred", "partial", "conflicted")
    if relevance >= 0.7 and covered >= 0.6 and citations and checked == 1.0 and not capped:
        level = "high"
    elif relevance < 0.4 or not citations or checked < 0.5:
        level = "low"
    else:
        level = "medium"
    reason = (
        f"excerpt relevance {relevance:.0%}, {covered:.0%} of sentences cited, "
        f"{verified} of {len(citations)} citations checked"
    ) + (f"; the answer is {state}" if capped else "")
    return Confidence(
        level=level,
        relevance=round(relevance, 3),
        coverage=round(covered, 3),
        verified=verified,
        citations=len(citations),
        reason=reason,
    )
