"""Reading a span of an ingested file, for the research agent's read tool."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import File, Source
from app.schemas import CodeChunk
from app.services.weights import source_weight

_COLUMNS = (
    File.id,
    File.path,
    File.language,
    File.content,
    *(Source.kind, Source.url, Source.title, Source.weight),
)


def read_span(db: Session, path: str, start: int, end: int) -> CodeChunk | None:
    """Lines `start` to `end` of the file at `path` (or the one file whose path ends with
    it), as an excerpt the answer can cite. None if there is no such file or line."""
    path = path.strip().lstrip("/")
    row = db.execute(
        select(*_COLUMNS).join(Source, Source.id == File.source_id).where(File.path == path)
    ).first()
    if row is None:
        matches = db.execute(
            select(*_COLUMNS)
            .join(Source, Source.id == File.source_id)
            .where(File.path.like(f"%/{_escape(path)}", escape="\\"))
            .limit(2)
        ).all()
        if len(matches) != 1:
            return None
        row = matches[0]
    file_id, file_path, language, content, kind, url, title, override = row
    lines = (content or "").split("\n")
    if start < 1 or start > len(lines):
        return None
    end = min(max(end, start), len(lines))
    return CodeChunk(
        # Negative, so a span never shares an id with a symbol.
        symbol_id=-(file_id * 1_000_000 + start),
        name=f"lines {start}-{end}",
        kind="section",
        signature=None,
        file=file_path,
        language=language,
        start_line=start,
        end_line=end,
        score=1.0,
        snippet="\n".join(lines[start - 1 : end]),
        snippet_end_line=end,
        truncated=False,
        citation=f"[{file_path}:{start}-{end}]",
        weight=source_weight(kind, url, title, override),
    )


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
