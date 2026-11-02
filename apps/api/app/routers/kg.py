"""The knowledge graph: neighbours, directed queries, shortest paths, a node's detail, an
overview for drawing, and questions in words."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.ratelimit import rate_limit
from app.services import kg

router = APIRouter(
    tags=["graph"],
    dependencies=[Depends(rate_limit("default", lambda: settings.rate_limit_per_minute))],
    responses={404: {"description": "Nothing in the knowledge base is called that."}},
)

EdgeKind = Literal[
    "calls",
    "imports",
    "inherits",
    "defines",
    "references",
    "mentioned_in",
    "example_of",
    "contradicts",
    "supersedes",
    "derived_from",
]


def _ref(db: Session, name: str) -> str:
    ref = kg.resolve(db, name)
    if ref is None:
        raise HTTPException(404, f"Nothing in the knowledge base is called {name!r}.")
    return ref


@router.get("/kg", summary="The knowledge graph around a node")
def neighbors(
    db: Annotated[Session, Depends(get_db)],
    node: Annotated[
        str,
        Query(
            min_length=1,
            description="A name (symbol, file, source, concept…) or a reference "
            "such as symbol:12 or concept:3.",
        ),
    ],
    depth: Annotated[int, Query(ge=1, le=4)] = 1,
    edge: Annotated[list[EdgeKind] | None, Query(description="Only these kinds of edge.")] = None,
) -> dict:
    """Every node within `depth` steps, and the edges between them: code (calls, imports,
    inherits), what defines what (source → file → symbol), and knowledge (references,
    mentioned_in, example_of, contradicts, supersedes, derived_from). Each edge carries
    its confidence and evidence. This is graph.neighbors(id, depth, edge_type)."""
    kinds = tuple(edge) if edge else kg.ALL_EDGES
    return {"node": _ref(db, node), **kg.neighbors(db, _ref(db, node), depth, kinds)}


@router.get("/kg/related", summary="Callers, dependencies, contradictions or successors")
def related(
    db: Annotated[Session, Depends(get_db)],
    node: Annotated[str, Query(min_length=1)],
    relation: Annotated[
        Literal["callers", "depends", "contradicts", "supersedes"],
        Query(
            description="Who calls it; what it depends on (transitively); what contradicts "
            "it; what supersedes it."
        ),
    ],
    depth: Annotated[int, Query(ge=1, le=6)] = 1,
) -> dict:
    ref = _ref(db, node)
    kind = "calls" if relation == "callers" else relation
    reverse = relation in ("callers", "supersedes")
    return {"node": ref, **kg.directed(db, ref, kind, reverse=reverse, depth=depth)}


@router.get("/kg/path", summary="The shortest path between two nodes")
def shortest_path(
    db: Annotated[Session, Depends(get_db)],
    start: Annotated[str, Query(alias="from", min_length=1)],
    end: Annotated[str, Query(alias="to", min_length=1)],
) -> dict:
    """The fewest steps, along any edge either way (at most six), from one node to the
    other; `path` lists the nodes in order, empty if none joins them."""
    return kg.path(db, _ref(db, start), _ref(db, end))


@router.get("/kg/node", summary="A node, for the graph's side panel")
def node_detail(
    db: Annotated[Session, Depends(get_db)], node: Annotated[str, Query(min_length=1)]
) -> dict:
    """What it is, its snippet and citation (code and passages), and its edges with their
    evidence."""
    detail = kg.node_detail(db, _ref(db, node))
    if detail is None:
        raise HTTPException(404, "No such node.")
    return detail


@router.get("/kg/overview", summary="The knowledge graph, for drawing")
def overview(
    db: Annotated[Session, Depends(get_db)], limit: Annotated[int, Query(ge=10, le=500)] = 250
) -> dict:
    """The most connected nodes and the edges between them; each node carries its type
    and its source, to colour and cluster by."""
    return kg.overview(db, limit)


@router.get("/kg/ask", summary="A question about the graph, in words")
def ask_graph(
    db: Annotated[Session, Depends(get_db)], q: Annotated[str, Query(min_length=3, max_length=500)]
) -> dict:
    """ "Shortest path between A and B", "who calls X", "what does X depend on", "what
    contradicts X", "what supersedes X", "neighbours of X": the answer in Markdown, with
    citations, and the subgraph."""
    answered = kg.answer(db, q)
    if answered is None:
        raise HTTPException(422, "That is not a question about the graph.")
    text, graph = answered
    return {"answer": text, **graph}
