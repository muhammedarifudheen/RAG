"""Fact-checking an answer against its sources: reading the checker's verdict."""

from __future__ import annotations

import json
import re

from app.schemas import FactCheck

_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def _strings(value: object, limit: int = 20) -> list[str]:
    if not isinstance(value, list):
        return []
    found = []
    for item in value:
        if isinstance(item, str) and item.strip():
            found.append(item.strip()[:500])
        elif isinstance(item, dict):  # {"sentence": ..., "reason": ...} and the like
            found.append("; ".join(str(v) for v in item.values() if v)[:500])
    return found[:limit]


def parse_fact_check(reply: str) -> FactCheck | None:
    """The checker's {"faithful", "unsupported", "citation_errors", "verdict"}; None when
    the reply holds no such object."""
    found = _OBJECT.search(reply or "")
    if not found:
        return None
    try:
        data = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(data, dict) or "faithful" not in data:
        return None
    faithful = data["faithful"]
    if isinstance(faithful, str):
        faithful = faithful.strip().lower() == "true"
    unsupported = _strings(data.get("unsupported"))
    errors = _strings(data.get("citation_errors"))
    verdict = data.get("verdict")
    return FactCheck(
        # Faithful with problems listed is not faithful.
        faithful=bool(faithful) and not unsupported and not errors,
        unsupported=unsupported,
        citation_errors=errors,
        verdict=verdict.strip()[:300] if isinstance(verdict, str) else "",
    )
