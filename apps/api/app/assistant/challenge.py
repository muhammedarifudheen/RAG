"""The self-challenge: the strongest objection to an answer from its own retrieved
context, and the answer revised if the objection holds."""

from __future__ import annotations

import re
from dataclasses import dataclass

# The user's self-challenge prompt, word for word.
SELF_CHALLENGE = """\
Before you finalize, generate the strongest possible objection to your own answer using \
ONLY the retrieved context.

Objection: <one paragraph>

Then decide:
- If the objection is valid → revise the answer.
- If the objection is invalid → state why in one line and keep the answer.

Output the final answer, then a collapsed "self-challenge" note."""

# How to lay the reply out, so the page can show the final answer and fold the note.
CHALLENGE_FORMAT = """\
Reply in exactly these labelled parts, in this order:
OBJECTION: <one paragraph>
DECISION: VALID or INVALID
REASON: <one line why, when INVALID>
FINAL ANSWER:
<the final answer in Markdown, keeping every citation in the form [path:start-end] that \
still holds; the answer as it was if the objection is invalid, revised if it is valid>"""


def challenge_prompt(question: str, answer: str, context: str) -> str:
    return (
        f"Question: {question}\n\nYour answer:\n{answer}\n\nRetrieved context (each block is "
        f"[source_id:lines] then text):\n{context}\n\n{SELF_CHALLENGE}\n\n{CHALLENGE_FORMAT}"
    )


@dataclass
class Challenge:
    objection: str
    valid: bool
    reason: str
    final_answer: str


_PART = re.compile(
    r"^\W*(OBJECTION|DECISION|REASON|FINAL ANSWER)\W*:?\**[ \t]*", re.IGNORECASE | re.MULTILINE
)


def parse_challenge(reply: str, answer: str) -> Challenge | None:
    """The labelled parts of the reply; None without an objection and a decision. An
    invalid objection keeps the answer as it was, whatever the reply repeats of it."""
    parts: dict[str, str] = {}
    marks = list(_PART.finditer(reply or ""))
    for i, mark in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(reply)
        parts.setdefault(mark[1].upper(), reply[mark.end() : end].strip())
    objection, decision = parts.get("OBJECTION", ""), parts.get("DECISION", "").upper()
    if not objection or not decision:
        return None
    valid = decision.startswith("VALID")
    final = parts.get("FINAL ANSWER", "").strip()
    if not valid or not final:
        final = answer
    return Challenge(
        objection=objection[:2000],
        valid=valid and final != answer,
        reason=parts.get("REASON", "").splitlines()[0][:300] if parts.get("REASON") else "",
        final_answer=final,
    )
