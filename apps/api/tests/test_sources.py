from sqlalchemy import select

from app.models import File, Source, Symbol


def test_sources_are_listed_with_their_sizes(client):
    response = client.get("/sources")

    assert response.status_code == 200
    by_title = {s["title"]: s for s in response.json()}
    assert set(by_title) == {"acme/pkg", "Alan Turing (Wikipedia)"}

    repo = by_title["acme/pkg"]
    assert (repo["kind"], repo["url"]) == ("repo", "https://github.com/acme/pkg")
    assert (repo["files"], repo["symbols"]) == (5, 18)
    assert repo["created_at"]

    article = by_title["Alan Turing (Wikipedia)"]
    assert article["kind"] == "wikipedia"
    assert article["url"] == "https://en.wikipedia.org/wiki/Alan_Turing"
    assert (article["files"], article["symbols"]) == (1, 3)


def test_removing_a_source_removes_only_that_source(client, db):
    # A throwaway source, so the shared fixture data is left as it was.
    source = Source(kind="upload", key="upload:scratch.txt", title="scratch")
    db.add(source)
    db.flush()
    file = File(
        source_id=source.id, path="uploads/scratch.txt", language="text", hash="0" * 64, loc=1,
        content="Scratch text.\n",
    )
    db.add(file)
    db.flush()
    db.add(Symbol(file_id=file.id, name="scratch", kind="section", start_line=1, end_line=1))
    db.commit()
    assert len(client.get("/sources").json()) == 3

    response = client.delete(f"/sources/{source.id}")

    assert response.status_code == 204
    assert {s["title"] for s in client.get("/sources").json()} == {
        "acme/pkg",
        "Alan Turing (Wikipedia)",
    }
    db.expire_all()
    # Its file and passages went with it; the other sources' files did not.
    assert db.scalar(select(File.id).where(File.path == "uploads/scratch.txt")) is None
    assert client.get("/file", params={"path": "uploads/scratch.txt"}).status_code == 404
    assert client.get("/file", params={"path": "pkg/models.py"}).status_code == 200
    assert client.get("/file", params={"path": "wikipedia/en/Alan_Turing"}).status_code == 200


def test_removing_an_unknown_source_is_a_404(client):
    assert client.delete("/sources/999999").status_code == 404
