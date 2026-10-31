"""EXPLORE and AUDIT answers, read straight from the database: the graph around what a
question names, and the knowledge base's health. No model is needed for either."""

from __future__ import annotations

from urllib.parse import quote

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.models import Edge, File, KnowledgeAudit, Symbol
from app.schemas import CodeChunk
from app.services.knowledge import health_note, knowledge_health

# Neighbours listed per direction.
NEIGHBOURS = 12


def explore(db: Session, anchors: list[CodeChunk]) -> str:
    """The graph around the best-matching symbols: what each calls, imports or inherits,
    and what calls, imports or inherits it, each cited, with a link to the graph page."""
    if not anchors:
        return "Nothing in the knowledge base matches that, so there is no graph to show."
    source, target = aliased(Symbol), aliased(Symbol)
    source_file, target_file = aliased(File), aliased(File)
    parts: list[str] = []
    for anchor in anchors[:3]:
        if anchor.symbol_id < 0:
            continue
        out = db.execute(
            select(Edge.kind, target.name, target.start_line, target.end_line, target_file.path)
            .join(target, target.id == Edge.to_symbol_id)
            .join(target_file, target_file.id == target.file_id)
            .where(Edge.from_symbol_id == anchor.symbol_id)
            .limit(NEIGHBOURS)
        ).all()
        into = db.execute(
            select(Edge.kind, source.name, source.start_line, source.end_line, source_file.path)
            .join(source, source.id == Edge.from_symbol_id)
            .join(source_file, source_file.id == source.file_id)
            .where(Edge.to_symbol_id == anchor.symbol_id)
            .limit(NEIGHBOURS)
        ).all()
        cite = f"[{anchor.file}:{anchor.start_line}-{anchor.snippet_end_line}]"
        lines = [f"### `{anchor.name}` ({anchor.kind}) {cite}", ""]
        if out:
            lines.append("**Uses:**")
            lines += [f"- {k} `{n}` [{p}:{s}-{e}]" for k, n, s, e, p in out]
        if into:
            lines.append("**Used by:**")
            lines += [f"- `{n}` {k} it [{p}:{s}-{e}]" for k, n, s, e, p in into]
        if not out and not into:
            lines.append("No calls, imports or inheritance were resolved for it.")
        lines.append(f"\n[Open {anchor.file} in the graph](/graph?file={quote(anchor.file)})")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def audit_answer(db: Session) -> str:
    """The knowledge base's health: the note from the answer log, and the newest audit."""
    parts = [health_note(knowledge_health(db))]
    latest = db.scalars(
        select(KnowledgeAudit).order_by(KnowledgeAudit.created_at.desc(), KnowledgeAudit.id.desc())
    ).first()
    if latest is not None:
        parts.append(
            f"**Audit of {latest.sources} sources** ({latest.created_at:%Y-%m-%d}, "
            f"{latest.model}):\n\n{latest.report}"
        )
    else:
        parts.append("No audit has run yet; one runs every Monday and after each deploy.")
    return "\n\n".join(parts)
