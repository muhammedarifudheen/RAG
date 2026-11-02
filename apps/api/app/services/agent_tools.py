"""The research agent's tools on Atlas itself: analytics.query, health.check, and
web.fetch on an allowlist (the sites already in the knowledge base)."""

from __future__ import annotations

import hashlib
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source
from app.schemas import CodeChunk
from app.services import analytics
from app.services.source_health import report

FETCH_LINES = 120
FETCH_CHARS = 8000


def analytics_text(db: Session, metric: str, window: int, filter: str | None) -> str:
    try:
        return analytics.as_text(analytics.query(db, metric, window, filter))
    except ValueError as error:
        return str(error)


def health_text(db: Session) -> str:
    data = report(db)
    lines = [
        f"Overall health {data['score']}/100, {len(data['sources'])} sources, {data['answers']} answers in 30 days."
    ]
    for s in data["sources"][:12]:
        actions = "; ".join(a["label"] for a in s["actions"]) or "none"
        lines.append(
            f"- {s['title']}: score {s['score']}, {s['freshness']['label']} ({s['freshness']['trend']}), "
            f"redundancy {round(s['redundancy'] * 100)}%, {s['trust']['label']}; actions: {actions}"
        )
    return "\n".join(lines)


def allowed_hosts(db: Session) -> set[str]:
    """The hosts of the knowledge base's sources: the only places the agent may fetch."""
    return {
        (urlsplit(url).hostname or "").lower()
        for url in db.scalars(select(Source.url).where(Source.url.is_not(None)))
        if url
    } - {""}


def fetch_page(db: Session, url: str) -> CodeChunk | str:
    """A page on an allowlisted site, as an excerpt the answer can cite; or why not."""
    from worker.fetch import FetchError, fetch
    from worker.sources import html_to_document

    host = (urlsplit(url).hostname or "").lower()
    if host not in allowed_hosts(db):
        return f"Not fetched: {host or 'that address'} is not a site in the knowledge base."
    try:
        page = fetch(url)
    except FetchError as error:
        return f"Not fetched: {error}"
    path = f"web/{host}{urlsplit(page.url).path or '/'}"
    if page.content_type == "text/plain":
        text = page.body.decode("utf-8", errors="replace")
    else:
        document = html_to_document(page.body, path, page.url, host)
        if document is None:
            return "Not fetched: no readable text on that page."
        text = document.text
    lines = text[:FETCH_CHARS].split("\n")[:FETCH_LINES]
    digest = int(hashlib.sha256(path.encode()).hexdigest()[:8], 16)
    return CodeChunk(
        symbol_id=-(2 * 10**15 + digest),
        name=path,
        kind="section",
        signature=None,
        file=path,
        language="markdown",
        start_line=1,
        end_line=len(lines),
        score=0.5,
        snippet="\n".join(lines),
        snippet_end_line=len(lines),
        truncated=len(text) > FETCH_CHARS,
        citation=f"[{path}:1-{len(lines)}]",
        weight=2,
        source_url=page.url,
    )
