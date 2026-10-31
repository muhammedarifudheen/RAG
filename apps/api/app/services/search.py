import logging
import re
from collections.abc import Sequence

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.embedding import Embedder
from app.models import File, Source, Symbol
from app.schemas import Citation, CodeChunk
from app.services.weights import source_weight

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


logger = logging.getLogger("atlas.api.search")

# Hybrid search fetches this many candidates from each of vector and keyword search.
CANDIDATES = 20


def search_symbols(
    db: Session,
    embedder: Embedder,
    query: str,
    limit: int,
    max_lines: int,
    vector: Sequence[float] | None = None,
) -> list[CodeChunk]:
    """The `limit` symbols whose embeddings are closest to the query, nearest first."""
    embedded = vector if vector is not None else embedder.embed(query)
    distance = Symbol.embedding.cosine_distance(embedded).label("distance")
    # The HNSW index returns at most ef_search rows.
    db.execute(text(f"SET LOCAL hnsw.ef_search = {max(int(limit) * 2, 64)}"))
    rows = db.execute(
        select(Symbol, File.path, File.language, File.content, distance, *_SOURCE)
        .join(File, File.id == Symbol.file_id)
        .join(Source, Source.id == File.source_id)
        .where(Symbol.embedding.is_not(None))
        .order_by(distance)
        .limit(limit)
    ).all()
    return _chunks(rows, max_lines)


def keyword_symbols(
    db: Session,
    query: str,
    limit: int,
    max_lines: int,
    vector: Sequence[float] | None = None,
) -> list[CodeChunk]:
    """The `limit` symbols whose words best match the query's (full-text search, ranked
    by cover density), best first. With the query's embedding, each keeps its cosine
    similarity as its score, so relevance thresholds mean the same as for vector
    search; without one (vector search failed), the keyword rank stands in."""
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 1][:24]
    if not words:
        return []
    terms = func.to_tsquery("english", " | ".join(words))
    search = literal_column("symbols.search")
    rank = func.ts_rank_cd(search, terms, 1)  # 1: divided by the log of the length
    # A symbol named by the query's words comes before one that only mentions them, so
    # format_name ranks above the module that calls it.
    named = func.to_tsvector("english", func.regexp_replace(Symbol.name, "[_./-]+", " ", "g")).op(
        "@@"
    )(terms)
    score = (
        func.coalesce(Symbol.embedding.cosine_distance(vector), 1.0).label("distance")
        if vector is not None
        else (1.0 - func.least(rank, 1.0)).label("distance")
    )
    rows = db.execute(
        select(Symbol, File.path, File.language, File.content, score, *_SOURCE)
        .join(File, File.id == Symbol.file_id)
        .join(Source, Source.id == File.source_id)
        .where(search.op("@@")(terms))
        .order_by(named.desc(), rank.desc(), Symbol.id)
        .limit(limit)
    ).all()
    return _chunks(rows, max_lines)


def hybrid_search(
    db: Session, embedder: Embedder, query: str, limit: int, max_lines: int
) -> tuple[list[CodeChunk], str | None]:
    """Vector and keyword search, CANDIDATES each, fused by reciprocal rank: an excerpt
    both find comes first. If vector search fails (the embedder or the index), keyword
    search alone; if keyword search fails, vector alone. Returns the excerpts and a
    notice for the user when one of them failed."""
    from app.assistant.planner import fuse  # the assistant's fusion, kept in one place

    pool = max(limit, CANDIDATES)
    vector: Sequence[float] | None = None
    try:
        vector = embedder.embed(query)
        semantic = search_symbols(db, embedder, query, pool, max_lines, vector=vector)
    except Exception:
        logger.exception("vector search failed; keyword search only")
        db.rollback()
        try:
            return keyword_symbols(db, query, limit, max_lines), (
                "Retrieval failed, so this answer used keyword search."
            )
        except Exception:
            logger.exception("keyword search failed too")
            db.rollback()
            raise
    try:
        keyword = keyword_symbols(db, query, pool, max_lines, vector=vector)
    except Exception:
        logger.exception("keyword search failed; vector search only")
        db.rollback()
        return semantic[:limit], None
    return fuse([semantic, keyword], limit), None


# What each excerpt's source counts for (see app/services/weights.py).
_SOURCE = (Source.kind, Source.url, Source.title, Source.weight)


def _chunks(rows: Sequence, max_lines: int) -> list[CodeChunk]:
    chunks = []
    for symbol, path, language, content, dist, kind, url, title, override in rows:
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
                weight=source_weight(kind, url, title, override),
            )
        )
    return chunks


# Hyphens models put in line ranges: non-breaking, and en and figure dashes.
_DASHES = str.maketrans({"‐": "-", "‑": "-", "‒": "-", "–": "-"})
_CODE_SPAN = re.compile(r"`([^`\n]+?):(\d+)(?:\s*[-‐-–]\s*(\d+))?`")


def tidy_citations(answer: str, chunks: Sequence[CodeChunk]) -> str:
    """Citations as [path:start-end] however a model wrote them: in a code span
    (`path:42-58`), or with a non-breaking or en dash. Only paths of excerpts the model
    was shown are changed, so other code spans stay as written."""
    paths = {chunk.file for chunk in chunks}
    if not paths:
        return answer

    def bracket(match: re.Match) -> str:
        path, start, end = match[1].strip(), match[2], match[3]
        if path not in paths:
            return match[0]
        return f"[{path}:{start}-{end}]" if end else f"[{path}:{start}]"

    # Zero-width characters some models put inside brackets break the path.
    answer = re.sub("\\[[\u200b\u200c\u200d\u2060\ufeff]+", "[", answer)
    # HTML code tags (in tables) count as code spans.
    answer = re.sub(r"<code>([^<>\n]+?)</code>", r"`\1`", answer)
    answer = _CODE_SPAN.sub(bracket, answer)
    # A code span already in brackets, [`path:1-2`], is now doubled: one pair.
    answer = re.sub(r"\[\[([^\[\]\n]+)\]\]", r"[\1]", answer)
    # Dashes inside the brackets that cite a shown path.
    return _BRACKET.sub(
        lambda m: f"[{m[1].translate(_DASHES)}]" if any(p in m[1] for p in paths) else m[0],
        answer,
    )


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
                    verified=start <= end and set(range(start, end + 1)) <= shown.get(path, set()),
                ),
            )
    return list(citations.values())
