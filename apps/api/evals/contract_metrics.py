"""The two metrics that keep "never refuse" from becoming "always make something up".

    dead_end_rate           the share of answers that are bare refusals. Target 0.
    unsupported_claim_rate  the share of factual claims with no citation backing them and no
                            provenance label that honestly says what they rest on. Target 0.

Both must be 0. If dead_end_rate is 0 but unsupported_claim_rate rises, the model is
fabricating to satisfy the contract's "never refuse": revert and fix retrieval, do not loosen
the contract.

What they are, exactly (they are heuristics; read the limits at the end):

A bare refusal (a dead end) is an answer that gives the reader nothing to act on:
  - empty;
  - an EVIDENCE_GAP without its report (tools tried, closest match, next step);
  - or a short refusal ("I don't know", "I cannot answer", the banned sentence) that has no
    citation and is not a complete evidence-gap report.

A factual claim is a sentence of six or more words that asserts something: not a question, a
heading, a quotation of a passage, a source list, or one of the contract's own notes. A claim
is supported when
  - it carries a citation that the server verified (the cited lines were shown to the model);
  - or the answer's state is UNVERIFIED or REPORTED and the answer carries that state's label
    (the unverified note; URLs with an as-of date), because the label says what it rests on;
  - or the answer's state is INFERRED, carries the inference label and has at least one verified
    citation to infer from.
For a question the knowledge base cannot answer (`answerable: false`) no citation can back a
claim, so every claim in an answer that is not labelled UNVERIFIED or REPORTED is unsupported,
and an evidence-gap report makes no claims at all.

Limits: sentences are split by punctuation, not parsed; "factual" is a word-count and shape
test, not understanding; a citation is trusted when the server verified it, which checks the
lines were shown, not that they say the claim. A model-graded check of the claims against their
cited lines is the next step. Standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

EVIDENCE_GAP = "EVIDENCE_GAP"
LABELLED = ("UNVERIFIED", "REPORTED")

_CITATION = re.compile(r"\[([^\[\]\n]+?:\d+(?:\s*[-‐-―]\s*\d+)?)\]")
_BACKTICK_CITATION = re.compile(r"`([^`\n]+?:\d+(?:\s*[-‐-―]\s*\d+)?)`")
_FENCE = re.compile(r"```.*?```", re.DOTALL)
_URL = re.compile(r"https?://\S+")
_REFUSAL = re.compile(
    r"don['’]t have that|do not have (?:that|enough|any)|i (?:don['’]t|do not) know|"
    r"not in the knowledge base|i (?:cannot|can['’]t|am unable to) (?:answer|help|find)|"
    r"no (?:information|mention|record) (?:of|about|on)|unable to (?:answer|find)",
    re.IGNORECASE,
)
_NOTE_STEMS = (
    "from my own knowledge, not your sources",
    "i couldn't find this in your sources",
    "this comes from the model's own knowledge",
    "no source states this directly",
    "reported from the web",
    "this is based on secondary sources",
    "confidence too low to answer safely",
)
_LABEL_LINE = re.compile(
    r"^(?:\*\*)?(unverified|inference|evidence gap|tools tried|closest match|next step|"
    r"sources?|reported from the web|tl;?dr|call chain|detail|gotcha|edge case)\b[^.?!]{0,40}:?"
    r"(?:\*\*)?:?\s*$",
    re.IGNORECASE,
)
_SENTENCE_BREAK = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9*`(\"'])")
_REPORT_PARTS = ("tools tried", "closest match", "next step")


def normalise_ref(ref: str) -> str:
    """`[a/b.py:10 – 20]` and `a/b.py:10-20` compare equal."""
    cleaned = ref.strip().strip("[]`").replace(" ", "")
    return re.sub(r"[‐-―]", "-", cleaned).lower()


def verified_refs(citations: Sequence[Mapping]) -> set[str]:
    return {normalise_ref(c.get("ref", "")) for c in citations if c.get("verified")}


def _plain(text: str) -> str:
    """Markdown and citations out, for counting words."""
    text = _CITATION.sub("", text)
    text = _BACKTICK_CITATION.sub("", text)
    text = _URL.sub("", text)
    return re.sub(r"[*_#>`|]+", " ", text).strip()


# --- dead ends ----------------------------------------------------------------------------


def is_dead_end(data: Mapping) -> bool:
    """Whether the answer is a bare refusal."""
    answer = (data.get("answer") or "").strip()
    if not answer:
        return True
    state = data.get("answer_state")
    lowered = answer.lower()
    complete_report = all(part in lowered for part in _REPORT_PARTS) and len(answer.split()) >= 25
    if state == EVIDENCE_GAP:
        gap = data.get("evidence_gap") or {}
        # With the structured report the answer must carry it; without (an older server), the
        # text must carry all three parts.
        if gap:
            return not (gap.get("tools_tried") and gap.get("next_steps") and complete_report)
        return not complete_report
    refusal = bool(_REFUSAL.search(answer))
    cited = bool(_CITATION.search(answer) or _BACKTICK_CITATION.search(answer))
    return refusal and len(answer.split()) < 40 and not cited and not complete_report


# --- claims -------------------------------------------------------------------------------


def _is_note(text: str) -> bool:
    """One of the contract's own notes ("**Unverified:** this comes from the model's own
    knowledge...", "**Inference:** no source states this directly..."): not a claim."""
    plain = re.sub(r"^(?:unverified|inference|reported from the web)\s*[:(]?\s*", "", _plain(text).lower())
    return plain.startswith(_NOTE_STEMS) or _plain(text).lower().startswith(_NOTE_STEMS)


def extract_claims(answer: str) -> list[str]:
    """The factual claims of an answer: its sentences of six or more words that assert."""
    text = _FENCE.sub("\n", answer)
    claims: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith((">", "|")):
            continue  # a quoted passage or a table row
        line = re.sub(r"^(?:[-*+]\s+|\d+[.)]\s+)", "", line)
        if _LABEL_LINE.match(line) or _is_note(line):
            continue
        for sentence in _SENTENCE_BREAK.split(line):
            if _is_note(sentence):
                continue
            sentence = re.sub(r"^\W*(?:tl;?dr)\W*", "", sentence, flags=re.IGNORECASE).strip()
            words = _plain(sentence).split()
            if (
                len(words) >= 6
                and not sentence.rstrip("*_ ").endswith("?")
                and sum(1 for w in words if re.search(r"[A-Za-z]{2}", w)) >= 4
            ):
                claims.append(sentence)
    return claims


def _label_present(answer: str, state: str | None) -> bool:
    lowered = answer.lower()
    if state == "UNVERIFIED":
        return "unverified" in lowered[:400]
    if state == "REPORTED":
        return bool(_URL.search(answer)) and "as of" in lowered
    if state == "INFERRED":
        return lowered.lstrip().startswith(("**inference", "inference", "based on")) or (
            "inference:" in lowered[:400]
        )
    return False


def score_claims(
    answer: str,
    state: str | None,
    citations: Sequence[Mapping],
    *,
    answerable: bool = True,
) -> tuple[int, int]:
    """(claims, unsupported claims) for one answer."""
    if state == EVIDENCE_GAP:
        return 0, 0  # a report of what was not found asserts nothing
    claims = extract_claims(answer)
    verified = verified_refs(citations)
    labelled = state in LABELLED and _label_present(answer, state)
    inferred = state == "INFERRED" and _label_present(answer, state) and bool(verified)
    unsupported = 0
    for claim in claims:
        refs = {normalise_ref(m) for m in _CITATION.findall(claim)}
        refs |= {normalise_ref(m) for m in _BACKTICK_CITATION.findall(claim)}
        cited = bool(refs & verified)
        if labelled:
            continue  # the label says it rests on the model or on the web, which is honest
        if not answerable:
            unsupported += 1  # nothing in the sources can back it, cited or not
        elif not (cited or inferred):
            unsupported += 1
    return len(claims), unsupported


def evaluate_response(item: Mapping, data: Mapping) -> dict:
    """Both metrics for one answer: `item` is the golden question, `data` the /ask response."""
    answerable = item.get("answerable", True)
    state = data.get("answer_state")
    claims, unsupported = score_claims(
        data.get("answer") or "", state, data.get("citations") or [], answerable=answerable
    )
    return {
        "dead_end": is_dead_end(data),
        "claims": claims,
        "unsupported_claims": unsupported,
        "answer_state": state,
    }


def summarise(rows: Sequence[Mapping]) -> dict[str, float]:
    """The two rates (and their counts) over rows that carry `dead_end` and `claims`."""
    judged = [r for r in rows if "dead_end" in r]
    claims = sum(r["claims"] for r in judged)
    unsupported = sum(r["unsupported_claims"] for r in judged)
    return {
        "dead_end_rate": sum(1 for r in judged if r["dead_end"]) / len(judged) if judged else 0.0,
        "unsupported_claim_rate": unsupported / claims if claims else 0.0,
        "unsupported_answer_rate": (
            sum(1 for r in judged if r["unsupported_claims"]) / len(judged) if judged else 0.0
        ),
        "claims_judged": float(claims),
        "unsupported_claims": float(unsupported),
        "answers_judged": float(len(judged)),
    }
