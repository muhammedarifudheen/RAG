"""The knowledge graph beyond code, found by heuristics at ingest (no model): for each
passage of a document,
- concepts: its heading, and terms it puts in bold;
- entities and people: capitalised names (people by the words around them);
- references to code: names in `backticks` that match a code symbol;
- examples of code: code blocks that use a code symbol.
Each becomes an edge with its confidence and its evidence (the passage and its lines)."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app import models
from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

MAX_PER_PASSAGE = 8

_BOLD = re.compile(r"\*\*([^*\n]{2,60}?)\*\*")
_TICKED = re.compile(r"`([A-Za-z_][\w.]{1,80}?)(?:\(\))?`")
_FENCE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_CODE_NAME = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*\b")
_NAME = re.compile(r"\b([A-Z][a-z]+(?:[ -](?:[A-Z][a-z]+|de|van|von|of|la|du)){1,4})\b")
_STOP = {
    "The", "A", "An", "This", "That", "These", "Those", "In", "On", "For", "It", "If", "When",
    "Its", "As", "At", "By", "From", "With", "Some", "Many", "Most", "All", "Each", "After",
    "Before", "During", "Since", "While", "His", "Her", "Their", "Our", "Your", "See", "Use",
}  # fmt: skip
_PERSON_BEFORE = re.compile(r"(?:\bby|\bDr\.|\bProf\.|\bProfessor|\bSir|\bMr\.|\bMrs\.|\bMs\.)\s*$")
_PERSON_AFTER = re.compile(
    r"^\s*(?:\((?:born|\d{4})|was an? (?:\w+ )?(?:mathematician|scientist|engineer|"
    r"programmer|logician|philosopher|cryptographer|physicist|author|researcher|developer))"
)
_SKIP = re.compile(
    r"^(?:Page \d+|Overview|Introduction|Summary|Contents|References|See also)$", re.IGNORECASE
)


@dataclass(frozen=True)
class Fact:
    kind: str  # "mentioned_in", "references" or "example_of"
    node: str  # "concept", "entity", "person" or "code"
    name: str
    confidence: float


def _looks_like_code(name: str) -> bool:
    return "_" in name or "." in name or bool(re.search(r"[a-z][A-Z]", name)) or name[:1].isupper()


def facts(text: str, heading: str | None) -> list[Fact]:
    """What a passage mentions: concepts, entities, people, and code it names or shows."""
    found: dict[tuple[str, str], Fact] = {}

    def add(fact: Fact) -> None:
        key = (fact.node, fact.name.lower())
        if key not in found or found[key].confidence < fact.confidence:
            found[key] = fact

    if heading:
        last = heading.split(" › ")[-1].strip()
        if 2 <= len(last) <= 80 and not _SKIP.match(last):
            add(Fact("mentioned_in", "concept", last, 0.9))
    for term in _BOLD.findall(text)[:MAX_PER_PASSAGE]:
        add(Fact("mentioned_in", "concept", term.strip(), 0.7))
    for name in _TICKED.findall(text)[: MAX_PER_PASSAGE * 2]:
        add(Fact("references", "code", name, 0.8))
    for block in _FENCE.findall(text):
        for name in {n for n in _CODE_NAME.findall(block) if _looks_like_code(n)}:
            add(Fact("example_of", "code", name, 0.7))
    prose = _FENCE.sub(" ", text)
    names = 0
    for match in _NAME.finditer(prose):
        name = match.group(1)
        first, _, rest = name.partition(" ")
        if first in _STOP:
            if " " not in rest:
                continue
            name = rest
        before = prose[max(0, match.start() - 14) : match.start()]
        after = prose[match.end() : match.end() + 60]
        person = bool(_PERSON_BEFORE.search(before) or _PERSON_AFTER.match(after))
        add(Fact("mentioned_in", "person" if person else "entity", name, 0.6 if person else 0.5))
        names += 1
        if names >= MAX_PER_PASSAGE:
            break
    return list(found.values())


def link_knowledge(session: Session, source: models.Source) -> int:
    """Finds the facts in the source's passages and stores them as nodes and edges.
    Returns how many edges were added."""
    symbol, file = models.Symbol, models.File
    passages = session.execute(
        select(symbol.id, symbol.signature, symbol.start_line, symbol.end_line, file.content)
        .join(file, file.id == symbol.file_id)
        .where(file.source_id == source.id, symbol.kind == "section")
    ).all()
    edges: list[dict] = []
    wanted: dict[str, tuple[str, str]] = {}  # node key -> (kind, name)
    code_names: set[str] = set()
    per_passage: list[tuple[int, int, int, list[Fact]]] = []
    for sid, heading, start, end, content in passages:
        text = "\n".join((content or "").split("\n")[start - 1 : end])
        found = facts(text, heading)
        per_passage.append((sid, start, end, found))
        for fact in found:
            if fact.node == "code":
                code_names.add(fact.name.split(".")[-1])
            else:
                wanted[f"{fact.node}:{fact.name.lower()}"] = (fact.node, fact.name)
    if not per_passage:
        return 0

    nodes: dict[str, int] = {}
    if wanted:
        session.execute(
            insert(models.KgNode)
            .values([{"key": k, "kind": kind, "name": name} for k, (kind, name) in wanted.items()])
            .on_conflict_do_nothing(index_elements=["key"])
        )
        nodes = dict(
            session.execute(
                select(models.KgNode.key, models.KgNode.id).where(
                    models.KgNode.key.in_(list(wanted))
                )
            ).all()
        )
    # Code the passages name: functions, methods and classes, anywhere in the knowledge base.
    targets: dict[str, int] = {}
    if code_names:
        rows = session.execute(
            select(symbol.id, symbol.name)
            .where(
                symbol.kind.in_(("function", "method", "class")),
                or_(
                    symbol.name.in_(code_names),
                    *(symbol.name.like(f"%.{n}") for n in list(code_names)[:200]),
                ),
            )
            .order_by(symbol.id)
        ).all()
        for target_id, name in rows:
            targets.setdefault(name.split(".")[-1].lower(), target_id)
            targets.setdefault(name.lower(), target_id)

    for sid, start, end, found in per_passage:
        for fact in found:
            if fact.node == "code":
                target = targets.get(fact.name.lower()) or targets.get(
                    fact.name.split(".")[-1].lower()
                )
                if target is None or target == sid:
                    continue
                edge = (f"symbol:{sid}", f"symbol:{target}")
            else:
                node = nodes.get(f"{fact.node}:{fact.name.lower()}")
                if node is None:
                    continue
                edge = (f"{fact.node}:{node}", f"symbol:{sid}")
            edges.append(
                {
                    "kind": fact.kind,
                    "from_ref": edge[0],
                    "to_ref": edge[1],
                    "confidence": fact.confidence,
                    "source_id": source.id,
                    "symbol_id": sid,
                    "start_line": start,
                    "end_line": end,
                }
            )
    if edges:
        session.execute(
            insert(models.KgEdge)
            .values(edges)
            .on_conflict_do_nothing(constraint="uq_kg_edges_kind_from_to")
        )
    return len(edges)
