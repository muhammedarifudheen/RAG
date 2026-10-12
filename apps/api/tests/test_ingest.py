import json

import pytest
from worker.pipeline import IngestError

from app.config import settings
from app.routers import ingest

REPO = "https://github.com/pallets/itsdangerous"


def events(body: str) -> list[tuple[str, dict]]:
    parsed = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


@pytest.fixture
def pipeline(monkeypatch):
    """Replaces the worker pipeline; records the URLs it was asked to ingest."""
    calls: list[str] = []

    def fake(repo_url, progress):
        calls.append(repo_url)
        progress(f"[1/5] Cloning {repo_url}")
        progress("      /tmp/atlas-x at 672971d66a2e")
        progress("[2/5] Parsing source files")
        return {"files": 15, "symbols": 159, "edges": 180}

    monkeypatch.setattr(ingest, "run_ingest", fake)
    return calls


def test_progress_is_streamed_as_server_sent_events(plain_client, pipeline):
    response = plain_client.post("/ingest", json={"repo_url": f"  {REPO} "})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in response.headers["cache-control"]
    assert pipeline == [REPO]
    assert events(response.text) == [
        ("progress", {"step": 1, "total": 5, "message": f"Cloning {REPO}"}),
        ("progress", {"step": None, "total": None, "message": "/tmp/atlas-x at 672971d66a2e"}),
        ("progress", {"step": 2, "total": 5, "message": "Parsing source files"}),
        ("done", {"files": 15, "symbols": 159, "edges": 180}),
    ]


def test_pipeline_failures_end_the_stream_with_an_error_event(plain_client, monkeypatch):
    def failing(repo_url, progress):
        progress("[1/5] Cloning")
        raise IngestError("Database is not ready: connection timeout expired")

    monkeypatch.setattr(ingest, "run_ingest", failing)

    response = plain_client.post("/ingest", json={"repo_url": REPO})

    assert events(response.text)[-1] == (
        "error",
        {"message": "Database is not ready: connection timeout expired"},
    )


def test_unexpected_errors_do_not_leak_details(plain_client, monkeypatch):
    def crashing(repo_url, progress):
        raise RuntimeError("secret internal path")

    monkeypatch.setattr(ingest, "run_ingest", crashing)

    response = plain_client.post("/ingest", json={"repo_url": REPO})

    assert events(response.text) == [("error", {"message": "Ingestion failed; see the server log."})]


def test_the_lock_is_released_after_success_and_after_failure(plain_client, pipeline, monkeypatch):
    assert plain_client.post("/ingest", json={"repo_url": REPO}).status_code == 200
    assert plain_client.post("/ingest", json={"repo_url": REPO}).status_code == 200

    monkeypatch.setattr(ingest, "run_ingest", lambda url, progress: 1 / 0)
    plain_client.post("/ingest", json={"repo_url": REPO})
    assert ingest._running.acquire(blocking=False)
    ingest._running.release()


def test_only_one_ingest_runs_at_a_time(plain_client, pipeline):
    assert ingest._running.acquire(blocking=False)
    try:
        response = plain_client.post("/ingest", json={"repo_url": REPO})
    finally:
        ingest._running.release()

    assert response.status_code == 409
    assert pipeline == []


@pytest.mark.parametrize(
    "url", ["", "not a url", "git@github.com:pallets/flask.git", "https://gitlab.com/a/b"]
)
def test_invalid_urls_are_rejected_before_anything_runs(plain_client, pipeline, url):
    response = plain_client.post("/ingest", json={"repo_url": url})

    assert response.status_code == 422
    assert pipeline == []


def test_ingest_is_rate_limited(plain_client, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "ingest_rate_limit_per_minute", 1)

    statuses = [plain_client.post("/ingest", json={"repo_url": REPO}).status_code for _ in range(2)]

    assert statuses == [200, 429]
