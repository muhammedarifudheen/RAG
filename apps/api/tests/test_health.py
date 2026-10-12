from app.services.health import strongly_connected


def names(symbols: list[dict]) -> list[tuple[str, str]]:
    return [(s["file"], s["name"]) for s in symbols]


def test_report_on_the_fixture_graph(client):
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()

    # Files and symbols count the article too; every other measure is about code.
    assert body["summary"] == {
        "files": 6,
        "symbols": 21,
        "edges": 12,
        "dead_symbols": 4,
        "file_cycles": 1,
        "call_cycles": 1,
        "long_functions": 1,
        "high_fan_out_files": 0,
    }
    assert body["thresholds"] == {"max_function_loc": 50, "min_fan_out": 10}


def test_dead_symbols_are_unreferenced_and_not_entry_points(client):
    dead = client.get("/health").json()["dead_symbols"]

    # User.__init__ and main have no callers either, but are entry points.
    # Classes are never reported, only functions and methods.
    assert {s["kind"] for s in dead} == {"function", "method"}
    assert names(dead) == [
        ("pkg/models.py", "Base.describe"),
        ("pkg/models.py", "User.label"),
        ("pkg/service.py", "create_user"),
        ("pkg/service.py", "unused_helper"),
    ]
    assert dead[0]["kind"] == "method"
    assert (dead[0]["start_line"], dead[0]["end_line"]) == (5, 6)


def test_circular_dependencies_between_files_and_between_calls(client):
    cycles = client.get("/health").json()["circular_dependencies"]

    assert cycles["files"] == [["pkg/cycle_a.py", "pkg/cycle_b.py"]]
    assert [names(cycle) for cycle in cycles["calls"]] == [
        [("pkg/cycle_a.py", "ping"), ("pkg/cycle_b.py", "pong")]
    ]


def test_long_functions_exceed_the_threshold(client):
    long_functions = client.get("/health").json()["long_functions"]
    assert [(f["name"], f["file"], f["loc"]) for f in long_functions] == [
        ("long_job", "pkg/big.py", 60)
    ]

    # Exactly at the threshold is not "longer than".
    at_threshold = client.get("/health", params={"max_function_loc": 60}).json()
    assert at_threshold["long_functions"] == []

    # Every function and method in the fixture is at least two lines; longest first.
    everything = client.get("/health", params={"max_function_loc": 1}).json()
    assert everything["summary"]["long_functions"] == 11
    assert everything["long_functions"][0]["name"] == "long_job"


def test_high_fan_out_files_meet_the_threshold(client):
    assert client.get("/health").json()["high_fan_out_files"] == []

    body = client.get("/health", params={"min_fan_out": 1}).json()
    assert body["high_fan_out_files"] == [
        {"file": "pkg/cycle_a.py", "fan_out": 1, "depends_on": ["pkg/cycle_b.py"]},
        {"file": "pkg/cycle_b.py", "fan_out": 1, "depends_on": ["pkg/cycle_a.py"]},
        {"file": "pkg/service.py", "fan_out": 1, "depends_on": ["pkg/models.py"]},
    ]
    assert body["summary"]["high_fan_out_files"] == 3


def test_limit_caps_lists_but_not_totals(client):
    body = client.get("/health", params={"limit": 2}).json()
    assert len(body["dead_symbols"]) == 2
    assert body["summary"]["dead_symbols"] == 4


def test_parameters_are_validated(client):
    assert client.get("/health", params={"max_function_loc": 0}).status_code == 422
    assert client.get("/health", params={"min_fan_out": 0}).status_code == 422
    assert client.get("/health", params={"limit": 0}).status_code == 422


def test_healthz_is_a_liveness_probe_that_needs_no_database(plain_client):
    response = plain_client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def components(edges: list[tuple[int, int]]) -> set[frozenset[int]]:
    return {frozenset(component) for component in strongly_connected(edges)}


def test_strongly_connected_finds_cycles_of_any_length():
    assert components([(1, 2), (2, 3), (3, 1), (3, 4)]) == {frozenset({1, 2, 3})}
    assert components([(1, 2), (2, 1), (3, 4), (4, 3), (2, 3)]) == {
        frozenset({1, 2}),
        frozenset({3, 4}),
    }


def test_strongly_connected_ignores_chains_and_self_loops():
    assert components([(1, 2), (2, 3)]) == set()
    assert components([(1, 1)]) == set()
    assert components([]) == set()


def test_strongly_connected_handles_graphs_deeper_than_the_recursion_limit():
    size = 5000
    ring = [(i, (i + 1) % size) for i in range(size)]
    assert components(ring) == {frozenset(range(size))}
