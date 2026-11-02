"""Near-duplicates across sources: the most trusted copy stays canonical, and the others
point at it (symbols.duplicate_of), so answers see a passage once and can say where else
it was seen."""

from __future__ import annotations

from app import models
from app.services.weights import source_weight
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from worker.minhash import pairs


def link_duplicates(session: Session, source: models.Source) -> int:
    """Links the source's passages with near-duplicates in other sources; returns how
    many of its passages were found elsewhere."""
    symbol, file, other = models.Symbol, models.File, models.Source
    new = session.execute(
        select(symbol.id, symbol.minhash)
        .join(file, file.id == symbol.file_id)
        .where(file.source_id == source.id, symbol.minhash.is_not(None))
    ).all()
    if not new:
        return 0
    old = session.execute(
        select(
            symbol.id,
            symbol.minhash,
            symbol.duplicate_of,
            other.kind,
            other.url,
            other.title,
            other.weight,
        )
        .join(file, file.id == symbol.file_id)
        .join(other, other.id == file.source_id)
        .where(other.id != source.id, symbol.minhash.is_not(None))
    ).all()
    if not old:
        return 0
    trust = {row[0]: source_weight(row[3], row[4], row[5], row[6]) for row in old}
    canonical_of = {row[0]: row[2] or row[0] for row in old}
    mine = source_weight(source.kind, source.url, source.title, source.weight)
    linked: set[int] = set()
    for new_id, old_id, _score in sorted(
        pairs([(i, m) for i, m in new], [(r[0], r[1]) for r in old]), key=lambda p: -p[2]
    ):
        if new_id in linked:
            continue
        canonical = canonical_of[old_id]
        if mine > trust.get(canonical, trust[old_id]):
            # This source is more trusted: its copy becomes the canonical one.
            session.execute(
                update(symbol)
                .where((symbol.id == canonical) | (symbol.duplicate_of == canonical))
                .values(duplicate_of=new_id)
            )
            canonical_of.update({k: new_id for k, v in canonical_of.items() if v == canonical})
        else:
            session.execute(
                update(symbol).where(symbol.id == new_id).values(duplicate_of=canonical)
            )
        linked.add(new_id)
    return len(linked)
