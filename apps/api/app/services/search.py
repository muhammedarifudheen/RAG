import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.embedding import Embedder
from app.models import File, Symbol
from app.schemas import Citation, CodeChunk

# `[path:42-58]`, `[path:42]`, and the form models sometimes use for several
# places in one file: `[path:5-7, 10-12]`.
_CITATION = re.compile(r"\[([^\[\]:\n]+):(\d+(?:-\d+)?(?:\s*,\s*\d+(?:-\d+)?)*)\]")
_RANGE = re.compile(r"(\d+)(?:-(\d+))?")


def snippet(content: str, start_line: int, end_line: int, max_lines: int) -> tuple[str, int]:
    """Lines start_line..end_line of a file, capped at max_lines. Returns (text, last line)."""
    # Split on "\n" only: that is what the worker's line numbers count.
    lines = content.split("\n")[start_line - 1 : end_line][:max_lines]
    return "\n".join(line.rstrip("\r") for line in lines), start_line + max(len(lines), 1) - 1


def search_symbols(
    db: Session, embedder: Embedder, query: str, limit: int, max_lines: int
) -> list[CodeChunk]:
    """The `limit` symbols whose embeddings are closest to the query, nearest first."""
    distance = Symbol.embedding.cosine_distance(embedder.embed(query)).label("distance")
    # The HNSW index returns at most ef_search rows (40 by default).
    db.execute(text(f"SET LOCAL hnsw.ef_search = {max(int(limit) * 2, 40)}"))
    rows = db.execute(
        select(Symbol, File.path, File.language, File.content, distance)
        .join(File, File.id == Symbol.file_id)
        .where(Symbol.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    ).all()

    chunks = []
    for symbol, path, language, content, dist in rows:
        code, last_line = snippet(content, symbol.start_line, symbol.end_line, max_lines)
        chunks.append(
            CodeChunk(
                symbol_id=symbol.id,
                name=symbol.name,
                kind=symbol.kind,
                signature=symbol.signature,
                file=path,
                language=language,
                start_line=symbol.start_line,
                end_line=symbol.end_line,
                score=round(1.0 - float(dist), 6),
                snippet=code,
                snippet_end_line=last_line,
                truncated=last_line < symbol.end_line,
                citation=f"[{path}:{symbol.start_line}-{last_line}]",
            )
        )
    return chunks


def extract_citations(answer: str, chunks: list[CodeChunk]) -> list[Citation]:
    """Citations written in an answer, each checked against the chunks the model was given."""
    # The lines the model was shown, per file. A citation is verified when every line
    # it names was shown, even if the range runs across two neighbouring excerpts.
    shown: dict[str, set[int]] = {}
    for chunk in chunks:
        shown.setdefault(chunk.file, set()).update(
            range(chunk.start_line, chunk.snippet_end_line + 1)
        )

    citations: dict[str, Citation] = {}
    for match in _CITATION.finditer(answer):
        path = match[1].strip()
        # Each range of a multi-range citation is checked, and reported, on its own.
        for part in _RANGE.finditer(match[2]):
            start = int(part[1])
            end = int(part[2]) if part[2] else start
            ref = f"[{path}:{part[0]}]"
            citations.setdefault(
                ref,
                Citation(
                    ref=ref,
                    file=path,
                    start_line=start,
                    end_line=end,
                    verified=start <= end
                    and set(range(start, end + 1)) <= shown.get(path, set()),
                ),
            )
    return list(citations.values())
