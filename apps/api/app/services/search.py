import re

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.embedding import Embedder
from app.models import File, Symbol
from app.schemas import Citation, CodeChunk

# A citation is `[path:42-58]` or `[path:42]`. Models also put several in one
# bracket, as `[path:5-7, 10-12]` or `[path:5-7, other/path:10-12]`; a range with
# no path belongs to the path before it.
_BRACKET = re.compile(r"\[([^\[\]\n]+)\]")
_ITEM = re.compile(r"^\s*(?:([^\[\]:\n]+?)\s*:\s*)?(\d+)(?:\s*-\s*(\d+))?\s*$")


def parse_citation(content: str) -> list[tuple[str, int, int, str]] | None:
    """The (path, start, end, as written) of each item in a bracket, or None when
    the bracket is not entirely citations, such as `[1, 2, 3]` or a link's text."""
    items: list[tuple[str, int, int, str]] = []
    path: str | None = None
    for raw in re.split(r"[,;]", content):
        match = _ITEM.match(raw)
        if match is None:
            return None
        path = match[1].strip() if match[1] else path
        if path is None:
            return None
        start = int(match[2])
        end = int(match[3]) if match[3] else start
        items.append((path, start, end, f"{match[2]}-{match[3]}" if match[3] else match[2]))
    return items


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
    for bracket in _BRACKET.finditer(answer):
        # Each item of a bracket holding several is checked, and reported, on its own.
        for path, start, end, written in parse_citation(bracket[1]) or []:
            ref = f"[{path}:{written}]"
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
