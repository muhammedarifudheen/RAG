from seed import SYMBOL_COUNT

from app.config import settings


def test_most_similar_symbol_comes_first_with_path_lines_and_snippet(client):
    response = client.get("/search", params={"q": "format name"})

    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "format name"
    top = body["results"][0]
    assert top["name"] == "format_name"
    assert top["kind"] == "function"
    assert top["signature"] == "def format_name(name: str) -> str"
    assert top["file"] == "pkg/models.py"
    assert top["language"] == "python"
    assert (top["start_line"], top["end_line"]) == (20, 21)
    assert top["snippet"] == "def format_name(name: str) -> str:\n    return name.strip().title()"
    assert top["snippet_end_line"] == 21
    assert top["truncated"] is False
    assert top["citation"] == "[pkg/models.py:20-21]"
    assert top["score"] > 0.5


def test_results_are_ordered_by_descending_similarity(client):
    results = client.get("/search", params={"q": "user label"}).json()["results"]
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)
    assert results[0]["name"] == "User.label"


def test_returns_at_most_20_by_default_and_honours_limit(client):
    # The fixture graph has 18 symbols, so the default limit of 20 returns them all.
    assert SYMBOL_COUNT == 18
    assert len(client.get("/search", params={"q": "user"}).json()["results"]) == 18
    assert len(client.get("/search", params={"q": "user", "limit": 3}).json()["results"]) == 3


def test_long_symbols_are_truncated_to_the_snippet_limit(client, monkeypatch):
    monkeypatch.setattr(settings, "snippet_max_lines", 5)

    results = client.get("/search", params={"q": "long job"}).json()["results"]
    long_job = next(r for r in results if r["name"] == "long_job")

    assert (long_job["start_line"], long_job["end_line"]) == (1, 60)
    assert long_job["snippet"].split("\n") == [
        "def long_job() -> int:",
        "    total = 0",
        "    total += 0",
        "    total += 1",
        "    total += 2",
    ]
    assert long_job["snippet_end_line"] == 5
    assert long_job["truncated"] is True
    assert long_job["citation"] == "[pkg/big.py:1-5]"


def test_invalid_queries_are_rejected(client):
    assert client.get("/search").status_code == 422
    assert client.get("/search", params={"q": ""}).status_code == 422
    assert client.get("/search", params={"q": "   "}).status_code == 422
    assert client.get("/search", params={"q": "x", "limit": 0}).status_code == 422
    assert client.get("/search", params={"q": "x", "limit": 51}).status_code == 422
