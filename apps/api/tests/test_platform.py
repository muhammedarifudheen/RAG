"""Rate limiting, request logging, error handling and OpenAPI docs."""

import logging

import pytest
from sqlalchemy.exc import OperationalError

from app.config import settings
from app.db import get_db
from app.main import app
from app.ratelimit import RateLimiter


def test_requests_over_the_limit_get_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 3)

    statuses = [client.get("/search", params={"q": "user"}).status_code for _ in range(4)]
    assert statuses == [200, 200, 200, 429]

    limited = client.get("/search", params={"q": "user"})
    assert limited.status_code == 429
    assert limited.json() == {"detail": "Rate limit of 3 requests per minute exceeded."}
    assert 1 <= int(limited.headers["Retry-After"]) <= 60


def test_the_limit_is_shared_across_endpoints_but_not_with_healthz(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 2)

    assert client.get("/search", params={"q": "user"}).status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/graph", params={"file": "pkg/service.py"}).status_code == 429
    assert client.get("/healthz").status_code == 200


def test_a_limit_of_zero_disables_rate_limiting(client, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_per_minute", 0)
    statuses = {client.get("/health").status_code for _ in range(5)}
    assert statuses == {200}


def test_limiter_window_slides():
    now = 1000.0
    limiter = RateLimiter(clock=lambda: now)

    assert limiter.check("a", limit=2) is None
    now += 10
    assert limiter.check("a", limit=2) is None
    assert limiter.check("a", limit=2) == pytest.approx(50)  # until the first hit expires
    assert limiter.check("b", limit=2) is None  # other clients are unaffected

    now += 50
    assert limiter.check("a", limit=2) is None  # first hit left the window
    assert limiter.check("a", limit=2) == pytest.approx(10)


def test_each_request_is_logged_without_its_query_string(client, caplog):
    with caplog.at_level(logging.INFO, logger="atlas.api.request"):
        response = client.get("/search", params={"q": "confidential question"})

    [record] = [r for r in caplog.records if r.name == "atlas.api.request"]
    message = record.getMessage()
    assert message.startswith("GET /search -> 200 in ")
    assert "client=testclient" in message
    assert f"request_id={response.headers['X-Request-ID']}" in message
    assert "confidential" not in message


def test_error_statuses_are_logged_too(client, caplog):
    with caplog.at_level(logging.INFO, logger="atlas.api.request"):
        client.get("/graph", params={"file": "pkg/missing.py"})

    assert any("GET /graph -> 404" in r.getMessage() for r in caplog.records)


def test_request_id_is_echoed_only_when_safe(plain_client):
    echoed = plain_client.get("/healthz", headers={"X-Request-ID": "abc-123"})
    assert echoed.headers["X-Request-ID"] == "abc-123"

    replaced = plain_client.get("/healthz", headers={"X-Request-ID": "bad id; drop"})
    assert replaced.headers["X-Request-ID"] != "bad id; drop"
    assert len(replaced.headers["X-Request-ID"]) == 32

    generated = plain_client.get("/healthz")
    assert len(generated.headers["X-Request-ID"]) == 32


def test_database_outage_is_a_503(plain_client):
    def broken_db():
        raise OperationalError("SELECT 1", {}, Exception("connection refused"))

    app.dependency_overrides[get_db] = broken_db

    response = plain_client.get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "The database is unavailable."}


def test_openapi_documents_every_endpoint(plain_client):
    assert plain_client.get("/docs").status_code == 200
    assert plain_client.get("/redoc").status_code == 200

    spec = plain_client.get("/openapi.json").json()
    assert spec["info"]["title"] == "Atlas API"
    assert set(spec["paths"]) == {
        "/ingest",
        "/ingest/upload",
        "/sources",
        "/sources/{source_id}",
        "/search",
        "/ask",
        "/graph",
        "/graph/files",
        "/file",
        "/health",
        "/healthz",
    }
    assert "text/event-stream" in spec["paths"]["/ingest"]["post"]["responses"]["200"]["content"]

    search = spec["paths"]["/search"]["get"]
    parameters = {p["name"]: p for p in search["parameters"]}
    assert parameters["q"]["required"] is True
    assert parameters["limit"]["schema"]["default"] == 20
    assert "429" in search["responses"]
    assert search["summary"] and search["description"]

    assert "post" in spec["paths"]["/ask"]
    assert {"409", "429", "502", "503"} <= set(spec["paths"]["/ask"]["post"]["responses"])
    assert "404" in spec["paths"]["/graph"]["get"]["responses"]
    for name in ("SearchResponse", "AskResponse", "GraphResponse", "HealthReport"):
        assert name in spec["components"]["schemas"]
