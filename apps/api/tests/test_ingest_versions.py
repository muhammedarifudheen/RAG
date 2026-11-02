"""Ingest upgrade: versions kept and restorable, near-duplicates across sources linked and
shown once, as_of retrieval, and the live per-source health with its actions."""

from datetime import UTC, datetime, timedelta

import pytest
from seed import FakeEmbedder, seed
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from worker.documents import Document, build_extraction
from worker.store import SourceInfo, store_source

from app.models import Source, SourceVersion, Symbol
from app.services.search import hybrid_search
from app.services.source_health import report

PASSAGE = (
    "HMAC is a specific type of message authentication code involving a cryptographic hash "
    "function and a secret cryptographic key. It may be used to simultaneously verify both "
    "the data integrity and the authenticity of a message, as with any MAC."
)


def extraction(path, title, body):
    found = build_extraction(Document(path, title, f"# {title}\n\n## Overview\n\n{body}"))
    embedder = FakeEmbedder()
    for symbol in found.symbols:
        symbol.embedding = embedder.embed(symbol.text)
    return found


def store(session: Session, key, kind, title, url, path, body):
    with session.begin():
        return store_source(
            session,
            SourceInfo(kind=kind, key=key, title=title, url=url),
            [extraction(path, title, body)],
            [],
        )


@pytest.fixture
def empty(engine):
    """An empty knowledge base for the test, and the shared seed restored afterwards."""
    with Session(engine) as session:
        session.execute(text(TRUNCATE))
        session.commit()
    yield
    with Session(engine) as session, session.begin():
        session.execute(text(TRUNCATE))
        seed(session)


TRUNCATE = "TRUNCATE TABLE edges, symbols, files, sources, source_versions RESTART IDENTITY CASCADE"


def test_each_ingest_is_a_version_the_last_three_are_kept_and_one_can_be_restored(
    engine, client, empty
):
    with Session(engine) as session:
        for n in range(1, 5):
            store(session, "web:notes", "web", "Notes", "https://docs.example.com/n", "web/notes",
                  f"Release {n}: tokens last {n * 10} days by default, unless max_age says otherwise.")  # fmt: skip
        source = session.scalars(select(Source).where(Source.key == "web:notes")).one()
        assert source.version == 4
        kept = session.scalars(
            select(SourceVersion.version).where(SourceVersion.source_key == "web:notes")
        ).all()
        assert sorted(kept) == [2, 3, 4]
        source_id = source.id

    versions = client.get(f"/sources/{source_id}/versions").json()
    assert [(v["version"], v["current"]) for v in versions] == [(4, True), (3, False), (2, False)]
    restored = client.post(f"/sources/{source_id}/rollback", json={"version": 2})
    assert restored.status_code == 200 and restored.json()["version"] == 5
    with Session(engine) as session:
        content = session.execute(
            text("SELECT content FROM files WHERE path = 'web/notes'")
        ).scalar()
        assert "Release 2" in content
    assert (
        client.post(f"/sources/{restored.json()['id']}/rollback", json={"version": 1}).status_code
        == 404
    )


def test_a_near_duplicate_is_shown_once_with_where_else_it_was_seen(engine, empty):
    with Session(engine) as session:
        store(
            session,
            "web:blog",
            "web",
            "A blog",
            "https://blog.example.com/hmac",
            "web/blog",
            PASSAGE,
        )
        linked = store(session, "wikipedia:en:hmac", "wikipedia", "HMAC (Wikipedia)",
                       "https://en.wikipedia.org/wiki/HMAC", "wikipedia/en/HMAC", PASSAGE)  # fmt: skip
        assert linked == 1
        found, _ = hybrid_search(
            session, FakeEmbedder(), "message authentication code hash key", 5, 80
        )
        sections = [c for c in found if c.kind == "section"]
        assert len(sections) == 1
        # Same weight (both secondary): the copy seen first stays canonical.
        assert sections[0].file == "web/blog"
        assert sections[0].also_seen_in == ["HMAC (Wikipedia)"]
        duplicates = session.scalars(select(Symbol).where(Symbol.duplicate_of.is_not(None))).all()
        assert len(duplicates) == 1


def test_as_of_leaves_out_sources_ingested_later(engine, empty):
    with Session(engine) as session:
        store(session, "web:old", "web", "Old", "https://a.example.com", "web/old", PASSAGE)
        session.execute(text("UPDATE sources SET created_at = now() - interval '10 days'"))
        session.commit()
        store(session, "web:new", "web", "New", "https://b.example.com", "web/new",
              "TimestampSigner adds a timestamp to every signature so that its age can be checked "
              "when it is unsigned, refusing values older than max_age seconds.")  # fmt: skip
        then = datetime.now(UTC) - timedelta(days=5)
        found, _ = hybrid_search(
            session, FakeEmbedder(), "timestamp signature age", 5, 80, as_of=then
        )
        assert {c.file for c in found} == {"web/old"}


def test_source_health_scores_each_source_and_suggests_actions(engine, client, empty):
    with Session(engine) as session:
        store(
            session,
            "web:blog",
            "web",
            "A blog",
            "https://blog.example.com/hmac",
            "web/blog",
            PASSAGE,
        )
        store(session, "wikipedia:en:hmac", "wikipedia", "HMAC (Wikipedia)",
              "https://en.wikipedia.org/wiki/HMAC", "wikipedia/en/HMAC", PASSAGE)  # fmt: skip
        session.execute(
            text(
                "UPDATE sources SET created_at = now() - interval '200 days' WHERE key = 'web:blog'"
            )
        )
        session.commit()
        data = report(session)
    # The score is kept at most every six hours, so the history may end with an earlier one.
    assert (
        0 < data["score"] <= 100
        and data["history"]
        and all(0 <= h["score"] <= 100 for h in data["history"])
    )
    blog = next(s for s in data["sources"] if s["title"] == "A blog")
    assert blog["freshness"]["label"] == "stale" and blog["freshness"]["trend"] == "degrading"
    kinds = {a["kind"] for a in blog["actions"]}
    assert {"reingest", "primary"} <= kinds
    wiki = next(s for s in data["sources"] if s["title"] == "HMAC (Wikipedia)")
    assert wiki["redundancy"] == 1.0 and wiki["trust"]["evidence"] == "an encyclopedia: secondary"
    assert any(a["kind"] in ("demote", "merge") for a in wiki["actions"])
    assert client.get("/health/sources").json()["sources"]
