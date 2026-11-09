import logging
import re
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, literal_column, select, text
from sqlalchemy.orm import Session

from app.embedding import Embedder
from app.models import File, Source, Symbol
from app.retrieval.budget import Budget, stage_timer
from app.schemas import Citation, CodeChunk
from app.services.freshness import category, prefer_newer
from app.services.freshness import label as freshness_label
from app.services.weights import source_license, source_weight

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
    as_of: datetime | None = None,
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
        .where(Symbol.embedding.is_not(None), *_current(as_of))
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
    as_of: datetime | None = None,
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
        .where(search.op("@@")(terms), *_current(as_of))
        .order_by(named.desc(), rank.desc(), Symbol.id)
        .limit(limit)
    ).all()
    return _chunks(rows, max_lines)


def _current(as_of: datetime | None) -> list:
    """Filters for what retrieval sees: one copy of each passage (near-duplicates in
    other sources point to the canonical one), and with `as_of`, only sources ingested by
    then."""
    filters = [Symbol.duplicate_of.is_(None)]
    if as_of is not None:
        filters.append(Source.created_at <= as_of)
    return filters


def also_seen_in(db: Session, chunks: list[CodeChunk]) -> list[CodeChunk]:
    """Each excerpt with the other sources its passage was also found in."""
    ids = [c.symbol_id for c in chunks if c.symbol_id > 0]
    if not ids:
        return chunks
    rows = db.execute(
        select(Symbol.duplicate_of, Source.title)
        .join(File, File.id == Symbol.file_id)
        .join(Source, Source.id == File.source_id)
        .where(Symbol.duplicate_of.in_(ids))
    ).all()
    seen: dict[int, list[str]] = {}
    for canonical, title in rows:
        if title not in seen.setdefault(canonical, []):
            seen[canonical].append(title)
    return [
        c.model_copy(update={"also_seen_in": seen[c.symbol_id]}) if c.symbol_id in seen else c
        for c in chunks
    ]


def hybrid_search(
    db: Session,
    embedder: Embedder,
    query: str,
    limit: int,
    max_lines: int,
    as_of: datetime | None = None,
    budget: Budget | None = None,
) -> tuple[list[CodeChunk], str | None]:
    """Vector and keyword search, CANDIDATES each, fused by reciprocal rank: an excerpt
    both find comes first. If vector search fails (the embedder or the index), keyword
    search alone; if keyword search fails, vector alone. Returns the excerpts and a
    notice for the user when one of them failed."""
    from app.assistant.planner import fuse  # the assistant's fusion, kept in one place

    pool = max(limit, CANDIDATES)
    vector: Sequence[float] | None = None
    try:
        with stage_timer(budget, "embed"):
            vector = embedder.embed(query)
        with stage_timer(budget, "vector"):
            semantic = search_symbols(
                db, embedder, query, pool, max_lines, vector=vector, as_of=as_of
            )
    except Exception:
        logger.exception("vector search failed; keyword search only")
        db.rollback()
        try:
            return keyword_symbols(db, query, limit, max_lines, as_of=as_of), (
                "Retrieval failed, so this answer used keyword search."
            )
        except Exception:
            logger.exception("keyword search failed too")
            db.rollback()
            raise
    try:
        with stage_timer(budget, "bm25"):
            keyword = keyword_symbols(db, query, pool, max_lines, vector=vector, as_of=as_of)
    except Exception:
        logger.exception("keyword search failed; vector search only")
        db.rollback()
        return also_seen_in(db, semantic[:limit]), None
    # Twice as many fused; near-duplicates then give way to others (MMR), and of
    # near-equal ones the newer source goes first.
    with stage_timer(budget, "fuse"):
        fused = prefer_newer(diversify(fuse([semantic, keyword], limit * 2), limit))
    return also_seen_in(db, fused), None


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]{2,}", text.lower()))


def diversify(chunks: Sequence[CodeChunk], limit: int, weight: float = 0.7) -> list[CodeChunk]:
    """Maximal marginal relevance: each next excerpt scores `weight` x its relevance (by
    rank) less (1 - weight) x its likeness (word overlap) to one already chosen. The best
    stays first; only near-duplicates give way."""
    pool = list(chunks)
    words = {c.symbol_id: _tokens(c.snippet) for c in pool}
    relevance = {c.symbol_id: 1 / (1 + rank) for rank, c in enumerate(pool)}
    chosen: list[CodeChunk] = []

    def gain(chunk: CodeChunk) -> float:
        mine = words[chunk.symbol_id]
        likeness = max(
            (
                len(mine & words[c.symbol_id]) / (len(mine | words[c.symbol_id]) or 1)
                for c in chosen
            ),
            default=0.0,
        )
        return weight * relevance[chunk.symbol_id] - (1 - weight) * likeness

    while pool and len(chosen) < limit:
        best = max(pool, key=gain)
        chosen.append(best)
        pool.remove(best)
    return chosen


# What each excerpt's source counts for (see app/services/weights.py).
_SOURCE = (
    Source.kind,
    Source.url,
    Source.title,
    Source.weight,
    Source.id,
    Source.created_at,
    Source.source_updated_at,
)


def _chunks(rows: Sequence, max_lines: int) -> list[CodeChunk]:
    chunks = []
    for row in rows:
        symbol, path, language, content, dist, kind, url, title, override = row[:9]
        source_id, ingested, updated = row[9:12]
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
                license=source_license(kind, url),
                source_url=url,
                source_title=title,
                source_id=source_id,
                ingested_at=ingested,
                source_updated_at=updated,
                freshness=freshness_label(ingested, category(kind, url, path)),
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
    answer = _cite_prose(answer, paths)
    # Dashes inside the brackets that cite a shown path.
    return _BRACKET.sub(
        lambda m: f"[{m[1].translate(_DASHES)}]" if any(p in m[1] for p in paths) else m[0],
        answer,
    )


_DASH = "[-" + "".join(chr(code) for code in _DASHES) + "]"
# "signer.py (lines 227-242)", "`timed.py`, lines 72–90", "signer.py line 40".
_PROSE = re.compile(
    r"(`?)([\w./-]+\.\w+)\1(\s*,?\s*\(?\s*lines?\s+(\d+)(?:\s*" + _DASH + r"\s*(\d+))?\s*\)?)",
    re.IGNORECASE,
)


def _cite_prose(answer: str, paths: set[str]) -> str:
    """A file and lines named in prose become a citation after the file's name, when the
    name is one shown file's path or the end of exactly one."""

    def cite(match: re.Match) -> str:
        name, start, end = match[2], match[4], match[5]
        found = [p for p in paths if p == name or p.endswith("/" + name.lstrip("./"))]
        if len(found) != 1:
            return match[0]
        span = f"{start}-{end}" if end else start
        return f"{match[1]}{name}{match[1]} [{found[0]}:{span}]"

    return _PROSE.sub(cite, answer)


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
