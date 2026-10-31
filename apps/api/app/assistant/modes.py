"""Atlas's modes, chosen by intent before anything else: ASK (grounded Q&A, the default),
EXPLORE (the graph around an entity), COMPARE (sources side by side, conflicts flagged),
BUILD (code-aware traces), AUDIT (the knowledge base's health), AGENT (multi-hop
research) and TEACH (a topic at three depths)."""

from __future__ import annotations

import re
from typing import Literal

from .router import _CODE_TEXT, wants_research

Mode = Literal["ASK", "EXPLORE", "COMPARE", "BUILD", "AUDIT", "AGENT", "TEACH"]
MODES: tuple[Mode, ...] = ("ASK", "EXPLORE", "COMPARE", "BUILD", "AUDIT", "AGENT", "TEACH")

_COMPARE = re.compile(r"\b(compare|comparison|versus|vs\.?)(?=\W|$)", re.IGNORECASE)
_TEACH = re.compile(r"\bhow\s+(does|do|did)\b.{1,120}?\bwork\b", re.IGNORECASE)
_AUDIT = re.compile(
    r"\b(audit|health\s+check|coverage|stale|outdated|redundan\w*|gaps?)\b.{0,60}?"
    r"\b(knowledge\s*base|kb|sources?|corpus)\b"
    r"|\b(knowledge\s*base|kb|sources?)\b.{0,40}?\b(audit|health|coverage|gaps?)\b",
    re.IGNORECASE,
)
_EXPLORE = re.compile(
    r"\b(explore|graph\s+of|call\s+graph|who\s+calls|what\s+calls|callers?\s+of|callees?|"
    r"depends\s+on|dependencies\s+of|map\s+(out\s+)?the|show\s+me\s+the\s+graph)\b",
    re.IGNORECASE,
)


def classify_mode(question: str) -> Mode:
    """The user's router, in their order: code → BUILD, compare/versus/vs → COMPARE,
    "how does X work" → TEACH; then the knowledge base's health → AUDIT, the graph around
    something → EXPLORE, a many-step question → AGENT; otherwise ASK."""
    if _CODE_TEXT.search(question):
        return "BUILD"
    if _COMPARE.search(question):
        return "COMPARE"
    if _TEACH.search(question):
        return "TEACH"
    if _AUDIT.search(question):
        return "AUDIT"
    if _EXPLORE.search(question):
        return "EXPLORE"
    if wants_research(question):
        return "AGENT"
    return "ASK"


COMPARE = """\
This is a COMPARE question. Compare what the sources say, side by side: a Markdown table \
with one column per source (or per thing compared), one row per aspect, each cell cited \
[path:start-end]. Under it, a "Conflicts" list: each point where sources disagree, flagged \
⚠, citing both and saying which is newer or carries more weight. Then a short verdict. If \
only one source covers the topic, say so instead of inventing a second side."""

TEACH = """\
This is a TEACH question: explain it at three depths, under these headings, each with its \
own citations [path:start-end]:
### One line
One sentence a newcomer would understand.
### In a paragraph
How it works, in a short paragraph.
### Deep dive
The mechanism step by step, with the code or text that implements each step."""
