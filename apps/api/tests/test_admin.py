import pytest

from app.config import settings
from app.routers import ingest

TOKEN = "correct horse battery staple"
REPO = "https://github.com/pallets/itsdangerous"


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(
        ingest, "run_ingest", lambda url, kind, max_pages, progress: {"files": 1, "symbols": 1, "edges": 0}
    )
    monkeypatch.setattr(
        ingest, "run_upload", lambda path, name, progress: {"files": 1, "symbols": 1, "edges": 0}
    )


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_without_a_token_configured_everything_is_open(plain_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", None)
    assert plain_client.post("/admin/check").status_code == 204
    assert plain_client.get("/config").json()["admin_required"] is False


def test_config_reports_whether_admin_and_chat_are_set_up(plain_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_token", TOKEN)
    monkeypatch.setattr(settings, "llm_provider", "gemini")
    monkeypatch.setattr(settings, "gemini_api_key", "key")
    assert plain_client.get("/config").json() == {"admin_required": True, "chat_configured": True}

    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert plain_client.get("/config").json()["chat_configured"] is False


@pytest.mark.parametrize("headers", [{}, auth("wrong"), {"Authorization": TOKEN}, auth(TOKEN + " ")])
def test_managing_sources_is_refused_without_the_right_token(plain_client, locked, headers):
    responses = [
        plain_client.post("/admin/check", headers=headers),
        plain_client.post("/ingest", json={"url": REPO}, headers=headers),
        plain_client.post(
            "/ingest/upload", files={"file": ("a.txt", b"text", "text/plain")}, headers=headers
        ),
        plain_client.delete("/sources/1", headers=headers),
    ]
    for response in responses:
        assert response.status_code == 401
        assert response.json() == {"detail": "Adding or removing sources needs the admin password."}
        assert response.headers["www-authenticate"] == "Bearer"


def test_the_right_token_lets_an_admin_manage_sources(plain_client, locked):
    assert plain_client.post("/admin/check", headers=auth(TOKEN)).status_code == 204
    assert plain_client.post("/ingest", json={"url": REPO}, headers=auth(TOKEN)).status_code == 200
    upload = plain_client.post(
        "/ingest/upload", files={"file": ("a.txt", b"text", "text/plain")}, headers=auth(TOKEN)
    )
    assert upload.status_code == 200


def test_reading_stays_open_when_locked(client, locked):
    assert client.get("/sources").status_code == 200
    assert client.get("/search", params={"q": "user"}).status_code == 200
    assert client.get("/health").status_code == 200
    assert client.get("/graph/files").status_code == 200
    assert client.post("/ask", json={"question": "format name"}).status_code == 200


def test_an_unknown_source_is_still_a_404_for_the_admin(client, locked):
    assert client.delete("/sources/999999", headers=auth(TOKEN)).status_code == 404
