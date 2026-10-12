import json

import pytest
from worker.pipeline import IngestError

from app.config import settings
from app.routers import ingest

REPO = "https://github.com/pallets/itsdangerous"
ARTICLE = "https://en.wikipedia.org/wiki/Alan_Turing"
PAGE = "https://docs.python.org/3/library/hmac.html"


def events(body: str) -> list[tuple[str, dict]]:
    parsed = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        parsed.append((fields["event"], json.loads(fields["data"])))
    return parsed


@pytest.fixture
def pipeline(monkeypatch):
    """Replaces the worker pipeline; records what it was asked to ingest."""
    calls: list[tuple[str, str, int]] = []

    def fake(url, kind, max_pages, progress):
        calls.append((url, kind, max_pages))
        progress(f"[1/5] Cloning {url}")
        progress("      /tmp/atlas-x at 672971d66a2e")
        progress("[2/5] Parsing source files")
        return {"files": 15, "symbols": 159, "edges": 180}

    monkeypatch.setattr(ingest, "run_ingest", fake)
    return calls


def test_progress_is_streamed_as_server_sent_events(plain_client, pipeline):
    response = plain_client.post("/ingest", json={"url": f"  {REPO} "})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in response.headers["cache-control"]
    assert pipeline == [(REPO, "repo", 20)]
    assert events(response.text) == [
        ("progress", {"step": 1, "total": 5, "message": f"Cloning {REPO}"}),
        ("progress", {"step": None, "total": None, "message": "/tmp/atlas-x at 672971d66a2e"}),
        ("progress", {"step": 2, "total": 5, "message": "Parsing source files"}),
        ("done", {"files": 15, "symbols": 159, "edges": 180}),
    ]


def test_the_kind_of_source_is_worked_out_from_the_link(plain_client, pipeline):
    for url in (REPO, ARTICLE, PAGE):
        assert plain_client.post("/ingest", json={"url": url}).status_code == 200

    assert pipeline == [(REPO, "repo", 20), (ARTICLE, "wikipedia", 20), (PAGE, "web", 20)]


def test_a_crawl_is_asked_for_explicitly_and_carries_its_page_limit(plain_client, pipeline):
    body = {"url": "https://docs.python.org/3/", "kind": "crawl", "max_pages": 7}
    assert plain_client.post("/ingest", json=body).status_code == 200
    assert pipeline == [("https://docs.python.org/3/", "crawl", 7)]


def test_the_older_repo_url_field_still_works(plain_client, pipeline):
    assert plain_client.post("/ingest", json={"repo_url": REPO}).status_code == 200
    assert pipeline == [(REPO, "repo", 20)]


def test_pipeline_failures_end_the_stream_with_an_error_event(plain_client, monkeypatch):
    def failing(url, kind, max_pages, progress):
        progress("[1/4] Fetching")
        raise IngestError("That link points at a private or internal address.")

    monkeypatch.setattr(ingest, "run_ingest", failing)

    response = plain_client.post("/ingest", json={"url": PAGE})

    assert events(response.text)[-1] == (
        "error",
        {"message": "That link points at a private or internal address."},
    )


def test_unexpected_errors_do_not_leak_details(plain_client, monkeypatch):
    def crashing(url, kind, max_pages, progress):
        raise RuntimeError("secret internal path")

    monkeypatch.setattr(ingest, "run_ingest", crashing)

    response = plain_client.post("/ingest", json={"url": REPO})

    assert events(response.text) == [("error", {"message": "Ingestion failed; see the server log."})]


def test_the_lock_is_released_after_success_and_after_failure(plain_client, pipeline, monkeypatch):
    assert plain_client.post("/ingest", json={"url": REPO}).status_code == 200
    assert plain_client.post("/ingest", json={"url": REPO}).status_code == 200

    monkeypatch.setattr(ingest, "run_ingest", lambda url, kind, max_pages, progress: 1 / 0)
    plain_client.post("/ingest", json={"url": REPO})
    assert ingest._running.acquire(blocking=False)
    ingest._running.release()


def test_only_one_ingest_runs_at_a_time(plain_client, pipeline):
    assert ingest._running.acquire(blocking=False)
    try:
        response = plain_client.post("/ingest", json={"url": REPO})
    finally:
        ingest._running.release()

    assert response.status_code == 409
    assert pipeline == []


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"url": ""},
        {"url": "not a url"},
        {"url": "file:///etc/passwd"},
        {"url": "ftp://example.com/file"},
        {"url": "git@github.com:pallets/flask.git", "kind": "repo"},
        {"url": "https://gitlab.com/a/b", "kind": "repo"},
        {"url": "https://example.com/wiki/X", "kind": "wikipedia"},
        {"url": "https://en.wikipedia.org/", "kind": "wikipedia"},
        {"url": PAGE, "kind": "crawl", "max_pages": 0},
        {"url": PAGE, "kind": "crawl", "max_pages": 101},
        {"url": PAGE, "kind": "everything"},
    ],
)
def test_unusable_requests_are_rejected_before_anything_runs(plain_client, pipeline, body):
    response = plain_client.post("/ingest", json=body)

    assert response.status_code == 422
    assert pipeline == []


def test_ingest_is_rate_limited(plain_client, pipeline, monkeypatch):
    monkeypatch.setattr(settings, "ingest_rate_limit_per_minute", 1)

    statuses = [plain_client.post("/ingest", json={"url": REPO}).status_code for _ in range(2)]

    assert statuses == [200, 429]


# --- uploads ---------------------------------------------------------------------


@pytest.fixture
def uploads(monkeypatch):
    """Replaces the worker pipeline for files; records each file's name and bytes."""
    received: list[tuple[str, bytes, str]] = []

    def fake(path, filename, progress):
        received.append((filename, path.read_bytes(), path.suffix))
        progress(f"[1/4] Fetching {filename}")
        return {"files": 1, "symbols": 4, "edges": 0}

    monkeypatch.setattr(ingest, "run_upload", fake)
    return received


def test_an_uploaded_file_is_ingested_and_progress_streamed(plain_client, uploads):
    response = plain_client.post(
        "/ingest/upload", files={"file": ("My Notes.md", b"# Notes\n\nSome text.\n", "text/markdown")}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert uploads == [("My Notes.md", b"# Notes\n\nSome text.\n", ".md")]
    assert events(response.text) == [
        ("progress", {"step": 1, "total": 4, "message": "Fetching My Notes.md"}),
        ("done", {"files": 1, "symbols": 4, "edges": 0}),
    ]


def test_the_temporary_copy_is_removed_afterwards(plain_client, monkeypatch):
    seen = []

    def fake(path, filename, progress):
        seen.append(path)
        return {"files": 1, "symbols": 1, "edges": 0}

    monkeypatch.setattr(ingest, "run_upload", fake)
    plain_client.post("/ingest/upload", files={"file": ("a.txt", b"text", "text/plain")})

    assert seen and not seen[0].exists() and not seen[0].parent.exists()


def test_upload_file_names_cannot_carry_a_path(plain_client, uploads):
    plain_client.post(
        "/ingest/upload", files={"file": ("../../etc/passwd.txt", b"text", "text/plain")}
    )
    assert [name for name, _, _ in uploads] == ["passwd.txt"]


def test_unsupported_and_oversized_uploads_are_rejected(plain_client, uploads, monkeypatch):
    wrong_type = plain_client.post(
        "/ingest/upload", files={"file": ("setup.exe", b"MZ", "application/octet-stream")}
    )
    assert wrong_type.status_code == 422
    assert ".exe is not supported" in wrong_type.json()["detail"]

    monkeypatch.setattr(ingest, "MAX_UPLOAD_BYTES", 10)
    too_big = plain_client.post(
        "/ingest/upload", files={"file": ("big.txt", b"x" * 11, "text/plain")}
    )
    assert too_big.status_code == 413
    assert uploads == []

    # A rejected upload must not leave the "one at a time" lock held.
    assert ingest._running.acquire(blocking=False)
    ingest._running.release()


def test_uploads_share_the_one_at_a_time_lock(plain_client, uploads):
    assert ingest._running.acquire(blocking=False)
    try:
        response = plain_client.post(
            "/ingest/upload", files={"file": ("a.txt", b"text", "text/plain")}
        )
    finally:
        ingest._running.release()
    assert response.status_code == 409
    assert uploads == []
