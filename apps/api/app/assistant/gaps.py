"""The gap finder's report: the source it suggests adding, when it gives a link."""

from __future__ import annotations

import re

_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
# The third part of the report: "3.", "### 3", "**3." and the like, to the end.
_THIRD = re.compile(r"^\W*3\W", re.MULTILINE)


def suggested_source(report: str) -> str | None:
    """The first link in the report's third part (the single best source to add next), or
    None if it gives none."""
    third = _THIRD.search(report or "")
    if not third:
        return None
    found = _URL.search(report[third.start() :])
    return found.group(0).rstrip(".,;:!?*_") if found else None
