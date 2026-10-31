"""The uncertainty budget: units spent on inferences, single sources, resolved conflicts
and secondary sources; over the budget, the answer is withheld."""

from __future__ import annotations

import re

BUDGET = 3
TOO_LOW = "Confidence too low to answer safely. Here's what I found and what's missing:"

# The user's uncertainty-budget rule, word for word.
UNCERTAINTY = """\
You have a fixed uncertainty budget of 3.

Spend 1 unit each time you:
- make an inference not directly stated
- rely on a single source
- resolve a conflict between sources
- answer from a secondary source

If you exceed 3, stop and return:
"Confidence too low to answer safely. Here's what I found and what's missing: ..."

Otherwise, answer and append: [uncertainty spent: N/3]"""

UNCERTAINTY_FORMAT = """\
Write the tag as the last line of the answer, before the follow-up questions."""

_TAG = re.compile(r"\s*\[\s*uncertainty\s+spent\s*:\s*(\d+)\s*/\s*\d+\s*\]\s*", re.IGNORECASE)


def take_tag(answer: str) -> tuple[int | None, str]:
    """(the units the model said it spent, the answer without its tag)."""
    found = list(_TAG.finditer(answer or ""))
    if not found:
        return None, answer
    spent = int(found[-1][1])
    return spent, _TAG.sub("\n", answer).strip()


def server_units(cited_files: set[str], basis: str | None, state: str | None) -> list[str]:
    """The units the server can see for itself: why each was spent."""
    reasons = []
    if state == "inferred":
        reasons.append("an inference the sources do not state")
    if len(cited_files) == 1:
        reasons.append("a single source")
    if state == "conflicted":
        reasons.append("a conflict between sources")
    if basis in ("secondary", "derived"):
        reasons.append("secondary sources only")
    return reasons
