"""The knowledge graph: the code graph (calls, imports, inherits), what defines what
(source → file → symbol), and the knowledge edges (references, mentioned_in, example_of,
contradicts, supersedes, derived_from), queried as one graph.

Nodes are named by reference: "source:2", "file:7", "symbol:12", "concept:3",
"entity:5", "person:9". Every edge carries its kind, its confidence and, where it has
one, its evidence: the source and the passage and lines it was found in."""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import Edge, File, KgEdge, KgNode, Source, Symbol
from app.schemas import CodeChunk
from app.services.search import snippet

CODE_EDGES = ("calls", "imports", "inherits")
ALL_EDGES = (
    *CODE_EDGES,
    "defines",
    "references",
    "mentioned_in",
    "example_of",
    "contradicts",
    "supersedes",
    "derived_from",
)
MAX_NODES = 300


@dataclass(frozen=True)
class Link:
    source: str
    target: str
    kind: str
    confidence: float = 1.0
    evidence: str | None = None  # "[path:start-end]"


@dataclass
class Graph:
    nodes: dict[str, dict] = field(default_factory=dict)
    links: set[Link] = field(default_factory=set)
    truncated: bool = False

    def as_dict(self) -> dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": [
                {
                    "source": link.source,
                    "target": link.target,
                    "kind": link.kind,
                    "confidence": round(link.confidence, 2),
                    "evidence": link.evidence,
                }
                for link in sorted(self.links, key=lambda x: (x.source, x.target, x.kind))
            ],
            "truncated": self.truncated,
        }


def _split(ref: str) -> tuple[str, int]:
    kind, _, value = ref.partition(":")
    return kind, int(value)


# --- Resolving names to nodes --------------------------------------------------------


def resolve(db: Session, name: str) -> str | None:
    """A node for a name: a reference as is, else a code symbol (exact name, or ending
    in it), a file path, a source title, or a concept, entity or person."""
    name = name.strip().strip("`'\"")
    if not name:
        return None
    kind, _, value = name.partition(":")
    if kind in ("source", "file", "symbol", "concept", "entity", "person") and value.isdigit():
        return name
    found = db.scalars(
        select(Symbol.id)
        .where(
            Symbol.kind != "module",
            or_(Symbol.name == name, Symbol.name.like(f"%.{name}")),
            Symbol.duplicate_of.is_(None),
        )
        .order_by(Symbol.kind.in_(("section",)), Symbol.id)
    ).first()
    if found is not None:
        return f"symbol:{found}"
    path = db.scalars(
        select(File.id).where(or_(File.path == name, File.path.like(f"%/{name}")))
    ).first()
    if path is not None:
        return f"file:{path}"
    source = db.scalars(select(Source.id).where(Source.title.ilike(name))).first()
    if source is not None:
        return f"source:{source}"
    node = db.scalars(select(KgNode).where(KgNode.name.ilike(name)).order_by(KgNode.id)).first()
    if node is not None:
        return f"{node.kind}:{node.id}"
    return None


# --- One step out from a node --------------------------------------------------------


def _evidence(db: Session, symbol_id: int | None, start: int | None, end: int | None) -> str | None:
    if symbol_id is None:
        return None
    path = db.scalar(
        select(File.path).join(Symbol, Symbol.file_id == File.id).where(Symbol.id == symbol_id)
    )
    return f"[{path}:{start}-{end}]" if path and start else None


def step(db: Session, refs: list[str], kinds: tuple[str, ...] = ALL_EDGES) -> list[Link]:
    """Every edge touching any of `refs`, of the given kinds, in both directions."""
    links: list[Link] = []
    symbols = [_split(r)[1] for r in refs if r.startswith("symbol:")]
    files = [_split(r)[1] for r in refs if r.startswith("file:")]
    sources = [_split(r)[1] for r in refs if r.startswith("source:")]
    code = [k for k in kinds if k in CODE_EDGES]
    if symbols and code:
        for a, b, kind in db.execute(
            select(Edge.from_symbol_id, Edge.to_symbol_id, Edge.kind).where(
                Edge.kind.in_(code),
                or_(Edge.from_symbol_id.in_(symbols), Edge.to_symbol_id.in_(symbols)),
            )
        ):
            links.append(Link(f"symbol:{a}", f"symbol:{b}", kind))
    if "defines" in kinds:
        if symbols:
            for sid, fid in db.execute(
                select(Symbol.id, Symbol.file_id).where(Symbol.id.in_(symbols))
            ):
                links.append(Link(f"file:{fid}", f"symbol:{sid}", "defines"))
        if files:
            for fid, sid, src in db.execute(
                select(File.id, Symbol.id, File.source_id)
                .join(Symbol, Symbol.file_id == File.id)
                .where(File.id.in_(files), Symbol.kind != "module")
                .limit(MAX_NODES)
            ):
                links.append(Link(f"file:{fid}", f"symbol:{sid}", "defines"))
                links.append(Link(f"source:{src}", f"file:{fid}", "defines"))
        if sources:
            for src, fid in db.execute(
                select(File.source_id, File.id).where(File.source_id.in_(sources)).limit(MAX_NODES)
            ):
                links.append(Link(f"source:{src}", f"file:{fid}", "defines"))
    if "derived_from" in kinds and symbols:
        for dup, canonical in db.execute(
            select(Symbol.id, Symbol.duplicate_of).where(
                Symbol.duplicate_of.is_not(None),
                or_(Symbol.id.in_(symbols), Symbol.duplicate_of.in_(symbols)),
            )
        ):
            links.append(Link(f"symbol:{dup}", f"symbol:{canonical}", "derived_from", 0.8))
    stored = [k for k in kinds if k not in CODE_EDGES and k != "defines"]
    if stored:
        for edge in db.scalars(
            select(KgEdge)
            .where(KgEdge.kind.in_(stored), or_(KgEdge.from_ref.in_(refs), KgEdge.to_ref.in_(refs)))
            .limit(MAX_NODES * 2)
        ):
            links.append(
                Link(
                    edge.from_ref,
                    edge.to_ref,
                    edge.kind,
                    edge.confidence,
                    _evidence(db, edge.symbol_id, edge.start_line, edge.end_line),
                )
            )
    return links


# --- Describing nodes ----------------------------------------------------------------


def describe(db: Session, refs: set[str]) -> dict[str, dict]:
    """Each node's label, type, cluster (its source) and, for code and passages, where
    it is."""
    out: dict[str, dict] = {}
    symbols = [_split(r)[1] for r in refs if r.startswith("symbol:")]
    for sid, name, kind, path, start, end, src, title in db.execute(
        select(
            Symbol.id,
            Symbol.name,
            Symbol.kind,
            File.path,
            Symbol.start_line,
            Symbol.end_line,
            Source.id,
            Source.title,
        )
        .join(File, File.id == Symbol.file_id)
        .join(Source, Source.id == File.source_id)
        .where(Symbol.id.in_(symbols or [0]))
    ):
        out[f"symbol:{sid}"] = {
            "id": f"symbol:{sid}",
            "label": name,
            "type": kind,
            "source_id": src,
            "source": title,
            "citation": f"[{path}:{start}-{end}]",
        }
    files = [_split(r)[1] for r in refs if r.startswith("file:")]
    for fid, path, src, title in db.execute(
        select(File.id, File.path, Source.id, Source.title)
        .join(Source, Source.id == File.source_id)
        .where(File.id.in_(files or [0]))
    ):
        out[f"file:{fid}"] = {
            "id": f"file:{fid}",
            "label": path,
            "type": "file",
            "source_id": src,
            "source": title,
        }
    sources = [_split(r)[1] for r in refs if r.startswith("source:")]
    for src, title, kind in db.execute(
        select(Source.id, Source.title, Source.kind).where(Source.id.in_(sources or [0]))
    ):
        out[f"source:{src}"] = {
            "id": f"source:{src}",
            "label": title,
            "type": "source",
            "source_id": src,
            "source": title,
            "kind": kind,
        }
    others = [_split(r)[1] for r in refs if r.split(":")[0] in ("concept", "entity", "person")]
    for node in db.scalars(select(KgNode).where(KgNode.id.in_(others or [0]))):
        ref = f"{node.kind}:{node.id}"
        out[ref] = {
            "id": ref,
            "label": node.name,
            "type": node.kind,
            "source_id": None,
            "source": None,
        }
    return {r: out[r] for r in refs if r in out}


# --- Queries -------------------------------------------------------------------------


def neighbors(db: Session, ref: str, depth: int = 1, kinds: tuple[str, ...] = ALL_EDGES) -> dict:
    """Everything within `depth` steps of a node, along edges of the given kinds."""
    graph = Graph()
    seen = {ref}
    frontier = [ref]
    for _ in range(max(1, min(depth, 4))):
        if not frontier:
            break
        nxt: list[str] = []
        for link in step(db, frontier, kinds):
            graph.links.add(link)
            for node in (link.source, link.target):
                if node in seen:
                    continue
                if len(seen) >= MAX_NODES:
                    graph.truncated = True
                    continue
                seen.add(node)
                nxt.append(node)
        frontier = nxt
    graph.nodes = describe(db, seen)
    graph.links = {
        link for link in graph.links if link.source in graph.nodes and link.target in graph.nodes
    }
    return graph.as_dict()


def directed(db: Session, ref: str, kind: str, reverse: bool, depth: int) -> dict:
    """Following one kind of edge one way: who calls X (reverse calls), what X depends on
    (calls and imports, transitively), what supersedes X, what contradicts X."""
    graph = Graph()
    seen = {ref}
    frontier = [ref]
    kinds = ("calls", "imports") if kind == "depends" else (kind,)
    for _ in range(max(1, min(depth, 6))):
        nxt = []
        for link in step(db, frontier, kinds):
            if kind == "contradicts":
                nearer, farther = (
                    (link.source, link.target)
                    if link.source in frontier
                    else (link.target, link.source)
                )
            else:
                nearer, farther = (
                    (link.target, link.source) if reverse else (link.source, link.target)
                )
                if nearer not in frontier:
                    continue
            graph.links.add(link)
            if farther not in seen and len(seen) < MAX_NODES:
                seen.add(farther)
                nxt.append(farther)
        frontier = nxt
        if not frontier:
            break
    graph.nodes = describe(db, seen)
    return graph.as_dict()


def path(db: Session, start: str, goal: str, max_depth: int = 6) -> dict:
    """The shortest path between two nodes, along any edge, either way."""
    parent: dict[str, tuple[str, Link] | None] = {start: None}
    queue = deque([(start, 0)])
    found = start == goal
    while queue and not found:
        level = []
        depth = queue[0][1]
        while queue and queue[0][1] == depth:
            level.append(queue.popleft()[0])
        if depth >= max_depth:
            break
        for link in step(db, level):
            for here, there in ((link.source, link.target), (link.target, link.source)):
                if here in level and there not in parent:
                    parent[there] = (here, link)
                    queue.append((there, depth + 1))
                    if there == goal:
                        found = True
        if len(parent) > MAX_NODES * 10:
            break
    graph = Graph()
    if found:
        node = goal
        chain = [goal]
        while parent[node] is not None:
            previous, link = parent[node]  # type: ignore[misc]
            graph.links.add(link)
            chain.append(previous)
            node = previous
        graph.nodes = describe(db, set(chain))
        ordered = list(reversed(chain))
        data = graph.as_dict()
        data["path"] = ordered
        return data
    data = graph.as_dict()
    data["path"] = []
    return data


def overview(db: Session, limit: int = 250) -> dict:
    """A view of the whole graph for drawing: the most connected nodes and the edges
    between them, clustered by source."""
    refs: dict[str, int] = {}
    for a, b in db.execute(select(Edge.from_symbol_id, Edge.to_symbol_id).limit(limit * 4)):
        for ref in (f"symbol:{a}", f"symbol:{b}"):
            refs[ref] = refs.get(ref, 0) + 1
    for a, b in db.execute(select(KgEdge.from_ref, KgEdge.to_ref).limit(limit * 4)):
        for ref in (a, b):
            refs[ref] = refs.get(ref, 0) + 1
    top = {r for r, _ in sorted(refs.items(), key=lambda kv: -kv[1])[:limit]}
    graph = Graph()
    graph.nodes = describe(db, top)
    for link in step(
        db,
        list(top),
        (
            *CODE_EDGES,
            "references",
            "mentioned_in",
            "example_of",
            "contradicts",
            "supersedes",
            "derived_from",
        ),
    ):
        if link.source in graph.nodes and link.target in graph.nodes:
            graph.links.add(link)
    return graph.as_dict()


def node_detail(db: Session, ref: str, max_lines: int = 40) -> dict | None:
    """A node for the side panel: what it is, its snippet and citation (code and
    passages), and its edges with their evidence."""
    described = describe(db, {ref})
    if ref not in described:
        return None
    out = dict(described[ref])
    if ref.startswith("symbol:"):
        row = db.execute(
            select(Symbol.start_line, Symbol.end_line, File.content)
            .join(File, File.id == Symbol.file_id)
            .where(Symbol.id == _split(ref)[1])
        ).first()
        if row:
            out["snippet"], _ = snippet(row.content, row.start_line, row.end_line, max_lines)
    links = step(db, [ref])
    neighbours = describe(db, {x for link in links for x in (link.source, link.target)} - {ref})
    out["edges"] = [
        {
            "kind": link.kind,
            "direction": "out" if link.source == ref else "in",
            "other": neighbours.get(link.target if link.source == ref else link.source),
            "confidence": round(link.confidence, 2),
            "evidence": link.evidence,
        }
        for link in links
        if (link.target if link.source == ref else link.source) in neighbours
    ][:60]
    return out


def as_excerpt(db: Session, ref: str) -> CodeChunk | None:
    """A symbol node as an excerpt the answer can cite."""
    from app.services.spans import read_span

    detail = describe(db, {ref}).get(ref)
    if not detail or "citation" not in detail:
        return None
    citation = detail["citation"].strip("[]")
    file_path, _, lines = citation.rpartition(":")
    start, _, end = lines.partition("-")
    return read_span(db, file_path, int(start), int(end))


# --- Questions about the graph, in words ----------------------------------------------

_NAMED = r"[`'\"]?([\w./:-]+(?:\s[\w./()-]+){0,4}?)[`'\"]?"
_ASKS = [
    (
        "path",
        re.compile(
            rf"(?:shortest\s+)?path\s+(?:between|from)\s+{_NAMED}\s+(?:and|to)\s+{_NAMED}\s*\?$",
            re.IGNORECASE,
        ),
    ),
    ("path", re.compile(rf"how\s+is\s+{_NAMED}\s+connected\s+to\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("callers", re.compile(rf"(?:who|what)\s+calls\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("callers", re.compile(rf"callers\s+of\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("depends", re.compile(rf"what\s+does\s+{_NAMED}\s+depend\s+on\s*\?$", re.IGNORECASE)),
    ("depends", re.compile(rf"dependencies\s+of\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("contradicts", re.compile(rf"what\s+contradicts\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("supersedes", re.compile(rf"what\s+supersedes\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    ("supersedes", re.compile(rf"newer\s+version\s+of\s+{_NAMED}\s*\?$", re.IGNORECASE)),
    (
        "neighbors",
        re.compile(rf"(?:neighbou?rs\s+of|graph\s+of|explore)\s+{_NAMED}\s*\?$", re.IGNORECASE),
    ),
]


def parse_question(question: str) -> tuple[str, list[str]] | None:
    """("path", [a, b]), ("callers", [x]), ("depends", [x]), ("contradicts", [x]),
    ("supersedes", [x]) or ("neighbors", [x]); None if it is no graph question."""
    text = question.strip().rstrip("?").strip() + "?"
    for op, pattern in _ASKS:
        match = pattern.search(text)
        if match:
            names = [g.strip() for g in match.groups() if g]
            if names:
                return op, names[:2] if op == "path" else names[:1]
    return None


_TITLES = {
    "callers": "Who calls `{}`",
    "depends": "What `{}` depends on (up to 3 steps)",
    "contradicts": "What contradicts `{}`",
    "supersedes": "What supersedes `{}`",
    "neighbors": "The graph around `{}`",
}


def answer(db: Session, question: str) -> tuple[str, dict] | None:
    """A graph question answered from the graph: the result as Markdown with citations,
    and the subgraph. None if it is no graph question."""
    asked = parse_question(question)
    if asked is None:
        return None
    op, names = asked
    refs = [resolve(db, n) for n in names]
    missing = [n for n, r in zip(names, refs, strict=True) if r is None]
    if missing:
        listed = ", ".join(f"`{n}`" for n in missing)
        return (
            f"Nothing in the knowledge base is called {listed}, so there is no graph to show.",
            {},
        )
    if op == "path":
        return _path_answer(db, names, refs)
    if op == "neighbors":
        data = neighbors(db, refs[0], 1)
    else:
        kind = "calls" if op == "callers" else op
        reverse = op in ("callers", "supersedes")
        data = directed(db, refs[0], kind, reverse=reverse, depth=3 if op == "depends" else 1)
    nodes = {n["id"]: n for n in data["nodes"]}
    lines = [f"**{_TITLES[op].format(names[0])}:**", ""]
    listed: set[tuple[str, str]] = set()
    for edge in data["edges"]:
        # The node each edge leads to: what is depended on, who calls, the other side.
        if op == "depends":
            other = edge["target"]
        elif op in ("callers", "supersedes"):
            other = edge["source"]
        else:
            other = edge["target"] if edge["source"] == refs[0] else edge["source"]
        node = nodes.get(other)
        if other == refs[0] or node is None or (edge["kind"], other) in listed:
            continue
        listed.add((edge["kind"], other))
        cite = f" {node['citation']}" if node.get("citation") else ""
        evidence = f" (evidence {edge['evidence']})" if edge.get("evidence") else ""
        lines.append(f"- {edge['kind']}: `{node['label']}` ({node['type']}){cite}{evidence}")
    if len(lines) == 2:
        lines.append("Nothing was found.")
    return "\n".join(lines), data


def _path_answer(db: Session, names: list[str], refs: list[str | None]) -> tuple[str, dict]:
    data = path(db, refs[0], refs[1])  # type: ignore[arg-type]
    if not data["path"]:
        return f"No path of up to 6 steps joins `{names[0]}` and `{names[1]}`.", data
    nodes = {n["id"]: n for n in data["nodes"]}
    steps = []
    for i, ref in enumerate(data["path"]):
        node = nodes.get(ref)
        label = node["label"] if node else ref
        cite = f" {node['citation']}" if node and node.get("citation") else ""
        via = ""
        if i:
            pair = {data["path"][i - 1], ref}
            link = next((e for e in data["edges"] if {e["source"], e["target"]} == pair), None)
            via = f" —{link['kind']}→ " if link else " → "
        steps.append(f"{via}`{label}`{cite}")
    return f"**Shortest path ({len(data['path']) - 1} steps):**\n\n" + "".join(steps), data


# --- Edges answers reveal ------------------------------------------------------------


def note_answer(db: Session, data: dict) -> None:
    """A conflicted answer: the cited passages from different sources contradict each
    other. Never raises."""
    from sqlalchemy.dialects.postgresql import insert

    if data.get("epistemic") != "conflicted":
        return
    try:
        cited = {c["file"] for c in data.get("citations") or [] if c.get("verified")}
        chunks = [
            c
            for c in data.get("chunks") or []
            if c.get("file") in cited and c.get("symbol_id", 0) > 0
        ]
        by_source: dict[int | None, dict] = {}
        for chunk in chunks:
            by_source.setdefault(chunk.get("source_id"), chunk)
        found = list(by_source.values())[:4]
        rows = [
            {
                "kind": "contradicts",
                "from_ref": f"symbol:{a['symbol_id']}",
                "to_ref": f"symbol:{b['symbol_id']}",
                "confidence": 0.6,
                "source_id": a.get("source_id"),
                "symbol_id": a["symbol_id"],
                "start_line": a.get("start_line"),
                "end_line": a.get("snippet_end_line"),
            }
            for i, a in enumerate(found)
            for b in found[i + 1 :]
        ]
        if rows:
            db.execute(
                insert(KgEdge)
                .values(rows)
                .on_conflict_do_nothing(constraint="uq_kg_edges_kind_from_to")
            )
            db.commit()
    except Exception:  # noqa: BLE001 - the answer matters more than the graph
        db.rollback()


def note_supersedes(db: Session, newer: int, older: int) -> None:
    """A newer source supersedes an older one on the same topic (a refresh proposal)."""
    from sqlalchemy.dialects.postgresql import insert

    db.execute(
        insert(KgEdge)
        .values(
            kind="supersedes", from_ref=f"source:{newer}", to_ref=f"source:{older}", confidence=0.6
        )
        .on_conflict_do_nothing(constraint="uq_kg_edges_kind_from_to")
    )


def walk(
    db: Session, name: str, depth: int = 1, edge: str | None = None
) -> tuple[str, list[CodeChunk]]:
    """graph.neighbors for the research agent: the nodes around `name` as text, and the
    code and passages among them as excerpts to cite."""
    ref = resolve(db, name)
    if ref is None:
        return f"Nothing in the knowledge base is called {name!r}.", []
    kinds = (edge,) if edge in ALL_EDGES else ALL_EDGES
    data = neighbors(db, ref, depth, kinds)
    nodes = {n["id"]: n for n in data["nodes"]}
    lines = [f"Around {nodes.get(ref, {}).get('label', name)} ({ref}):"]
    for e in data["edges"][:40]:
        a, b = nodes.get(e["source"]), nodes.get(e["target"])
        if a and b:
            where = f" {b['citation']}" if b.get("citation") else ""
            lines.append(f"- {a['label']} —{e['kind']}→ {b['label']}{where}")
    excerpts = [
        x for x in (as_excerpt(db, n) for n in list(nodes)[:12] if n.startswith("symbol:")) if x
    ]
    return "\n".join(lines), excerpts
