"""How much a source counts: PRIMARY (code, specs, official docs) 3, SECONDARY (Wikipedia,
tutorials, blog posts) 2, DERIVED (summaries, chat logs) 1. Automatic from what the source
is, unless the admin set it."""

from __future__ import annotations

import re
from urllib.parse import urlparse

PRIMARY, SECONDARY, DERIVED = 3, 2, 1
LABELS = {PRIMARY: "primary", SECONDARY: "secondary", DERIVED: "derived"}

# Hosts of specifications and official documentation.
_OFFICIAL = re.compile(
    r"(^|\.)("
    r"docs\.[\w.-]+|[\w-]+\.readthedocs\.(io|org)|python\.org|rfc-editor\.org|ietf\.org|"
    r"w3\.org|whatwg\.org|developer\.mozilla\.org|learn\.microsoft\.com|docs\.github\.com|"
    r"pkg\.go\.dev|go\.dev|doc\.rust-lang\.org|docs\.rs|nodejs\.org|postgresql\.org|"
    r"palletsprojects\.com|kubernetes\.io|react\.dev|nextjs\.org|github\.com"
    r")$"
)
# Titles of uploads that summarise or record other material.
_DERIVED = re.compile(
    r"\b(summary|summaries|notes?|chat[ _-]?log|transcript|digest)\b", re.IGNORECASE
)


def automatic_weight(kind: str, url: str | None, title: str = "") -> int:
    if kind == "repo":
        return PRIMARY
    if kind == "wikipedia":
        return SECONDARY
    if kind in ("web", "crawl") and url:
        host = (urlparse(url).hostname or "").lower()
        return PRIMARY if _OFFICIAL.search(host) else SECONDARY
    if kind == "upload" and _DERIVED.search(title):
        return DERIVED
    return SECONDARY


def source_weight(kind: str, url: str | None, title: str, override: int | None) -> int:
    return override if override in LABELS else automatic_weight(kind, url, title)


# Wikipedia's text is licensed CC BY-SA 4.0: reuse must credit it and keep the licence.
WIKIPEDIA_LICENSE = "CC BY-SA 4.0"
_WIKIMEDIA = re.compile(r"(^|\.)(wikipedia|wikibooks|wikiversity|wikivoyage|wikinews)\.org$")


def source_license(kind: str, url: str | None) -> str | None:
    """The licence a citation of the source must carry, if one is known."""
    host = (urlparse(url).hostname or "").lower() if url else ""
    if kind == "wikipedia" or _WIKIMEDIA.search(host):
        return WIKIPEDIA_LICENSE
    return None
