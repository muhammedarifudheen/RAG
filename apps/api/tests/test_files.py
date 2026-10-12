from seed import MODELS


def test_file_graph_has_every_file_and_aggregated_edges(client):
    response = client.get("/graph/files")

    assert response.status_code == 200
    body = response.json()
    paths = {n["id"]: n["path"] for n in body["nodes"]}

    assert sorted(paths.values()) == [
        "pkg/big.py",
        "pkg/cycle_a.py",
        "pkg/cycle_b.py",
        "pkg/models.py",
        "pkg/service.py",
    ]
    edges = {
        (paths[e["source"]], paths[e["target"]]): (e["imports"], e["calls"], e["inherits"])
        for e in body["edges"]
    }
    # service.py imports two symbols from models.py and calls two; edges within a file
    # (such as User inheriting Base) are not part of the file graph.
    assert edges == {
        ("pkg/service.py", "pkg/models.py"): (2, 2, 0),
        ("pkg/cycle_a.py", "pkg/cycle_b.py"): (1, 1, 0),
        ("pkg/cycle_b.py", "pkg/cycle_a.py"): (1, 1, 0),
    }


def test_file_graph_marks_cycles(client):
    body = client.get("/graph/files").json()
    paths = {n["id"]: n["path"] for n in body["nodes"]}

    assert {n["path"] for n in body["nodes"] if n["in_cycle"]} == {
        "pkg/cycle_a.py",
        "pkg/cycle_b.py",
    }
    assert [sorted(paths[i] for i in cycle) for cycle in body["cycles"]] == [
        ["pkg/cycle_a.py", "pkg/cycle_b.py"]
    ]
    in_cycle = {(paths[e["source"]], paths[e["target"]]) for e in body["edges"] if e["in_cycle"]}
    assert in_cycle == {
        ("pkg/cycle_a.py", "pkg/cycle_b.py"),
        ("pkg/cycle_b.py", "pkg/cycle_a.py"),
    }


def test_file_graph_nodes_carry_size(client):
    nodes = {n["path"]: n for n in client.get("/graph/files").json()["nodes"]}
    models = nodes["pkg/models.py"]
    assert (models["language"], models["loc"], models["symbols"]) == ("python", 21, 8)
    assert models["in_cycle"] is False


def test_file_returns_source_and_symbols_in_line_order(client):
    response = client.get("/file", params={"path": "pkg/models.py"})

    assert response.status_code == 200
    body = response.json()
    assert (body["path"], body["language"], body["loc"]) == ("pkg/models.py", "python", 21)
    assert body["content"] == MODELS
    # The module symbol is the file itself, so it is not listed.
    assert [(s["name"], s["kind"], s["start_line"], s["end_line"]) for s in body["symbols"]] == [
        ("Base", "class", 4, 9),
        ("Base.describe", "method", 5, 6),
        ("Base.label", "method", 8, 9),
        ("User", "class", 12, 17),
        ("User.__init__", "method", 13, 14),
        ("User.label", "method", 16, 17),
        ("format_name", "function", 20, 21),
    ]
    assert body["symbols"][-1]["signature"] == "def format_name(name: str) -> str"


def test_unknown_file_is_a_404(client):
    assert client.get("/file", params={"path": "pkg/missing.py"}).status_code == 404
    assert client.get("/file").status_code == 422
