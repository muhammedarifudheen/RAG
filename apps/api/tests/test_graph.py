from app.services.graph import call_graph


def nodes(body: dict) -> set[tuple[str, int]]:
    return {(n["name"], n["depth"]) for n in body["nodes"]}


def edges(body: dict) -> set[tuple[str, str]]:
    names = {n["id"]: n["name"] for n in body["nodes"]}
    return {(names[e["source"]], names[e["target"]]) for e in body["edges"]}


def get(client, **params) -> dict:
    response = client.get("/graph", params=params)
    assert response.status_code == 200
    return response.json()


def test_one_hop_reaches_direct_callees(client):
    body = get(client, file="pkg/service.py")

    assert (body["file"], body["hops"], body["direction"]) == ("pkg/service.py", 1, "both")
    assert nodes(body) == {
        ("pkg/service.py", 0),
        ("create_user", 0),
        ("unused_helper", 0),
        ("User", 1),
        ("format_name", 1),
    }
    assert edges(body) == {("create_user", "User"), ("create_user", "format_name")}
    assert body["truncated"] is False


def test_nodes_carry_file_and_line_range(client):
    body = get(client, file="pkg/service.py")
    user = next(n for n in body["nodes"] if n["name"] == "User")
    assert user == {
        "id": user["id"],
        "name": "User",
        "kind": "class",
        "file": "pkg/models.py",
        "start_line": 12,
        "end_line": 17,
        "depth": 1,
    }


def test_second_hop_reaches_other_callers_of_the_callees(client):
    body = get(client, file="pkg/service.py", hops=2)

    assert nodes(body) == {
        ("pkg/service.py", 0),
        ("create_user", 0),
        ("unused_helper", 0),
        ("User", 1),
        ("format_name", 1),
        ("User.label", 2),  # also calls format_name
    }
    assert edges(body) == {
        ("create_user", "User"),
        ("create_user", "format_name"),
        ("User.label", "format_name"),
    }


def test_direction_limits_traversal(client):
    # Nothing in models.py calls out of the file, so following callees adds no nodes.
    callees = get(client, file="pkg/models.py", hops=3, direction="callees")
    assert all(depth == 0 for _, depth in nodes(callees))
    assert edges(callees) == {("Base.describe", "Base.label"), ("User.label", "format_name")}

    callers = get(client, file="pkg/models.py", hops=3, direction="callers")
    assert ("create_user", 1) in nodes(callers)
    assert ("create_user", "User") in edges(callers)

    # User.label is only reached from service.py by going "up" from format_name.
    down_only = get(client, file="pkg/service.py", hops=2, direction="callees")
    assert "User.label" not in {name for name, _ in nodes(down_only)}


def test_cycles_do_not_loop(client):
    body = get(client, file="pkg/cycle_a.py", hops=5)

    assert nodes(body) == {("pkg/cycle_a.py", 0), ("ping", 0), ("pong", 1)}
    assert edges(body) == {("ping", "pong"), ("pong", "ping")}


def test_only_call_edges_are_included(client):
    # service.py imports from models.py and User inherits from Base; neither is a call.
    body = get(client, file="pkg/service.py", hops=5)
    assert "Base" not in {name for name, _ in nodes(body)}


def test_unknown_file_is_a_404(client):
    response = client.get("/graph", params={"file": "pkg/missing.py"})
    assert response.status_code == 404
    assert "pkg/missing.py" in response.json()["detail"]


def test_hops_are_bounded(client):
    assert client.get("/graph", params={"file": "pkg/service.py", "hops": 0}).status_code == 422
    assert client.get("/graph", params={"file": "pkg/service.py", "hops": 6}).status_code == 422
    assert client.get("/graph").status_code == 422
    bad_direction = {"file": "pkg/service.py", "direction": "sideways"}
    assert client.get("/graph", params=bad_direction).status_code == 422


def test_node_limit_truncates(db):
    graph = call_graph(db, "pkg/service.py", hops=1, direction="both", max_nodes=4)

    assert graph is not None
    assert graph.truncated is True
    assert len(graph.nodes) == 4
    ids = {node.id for node in graph.nodes}
    assert all(edge.source in ids and edge.target in ids for edge in graph.edges)
