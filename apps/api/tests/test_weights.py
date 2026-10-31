"""Source weights: primary 3, secondary 2, derived 1, and what an answer says about them."""

from types import SimpleNamespace

from app.assistant.prompt import weights_block
from app.assistant.service import Assistant, Options
from app.schemas import CodeChunk
from app.services.weights import automatic_weight, source_weight


def chunk(file="a/signer.py", weight=3):
    return CodeChunk(
        symbol_id=hash(file) % 1000,
        name="unsign",
        kind="method",
        file=file,
        language="python",
        start_line=10,
        end_line=20,
        signature=None,
        score=0.8,
        snippet="def unsign(self):\n    pass",
        snippet_end_line=20,
        truncated=False,
        citation=f"[{file}:10-20]",
        weight=weight,
    )


def test_weights_come_from_what_the_source_is_unless_the_admin_set_one():
    assert automatic_weight("repo", "https://github.com/pallets/itsdangerous") == 3
    assert automatic_weight("web", "https://docs.python.org/3/library/hmac.html") == 3
    assert automatic_weight("web", "https://itsdangerous.palletsprojects.com/en/stable/") == 3
    assert automatic_weight("web", "https://someblog.example/hmac-explained") == 2
    assert automatic_weight("wikipedia", "https://en.wikipedia.org/wiki/HMAC") == 2
    assert automatic_weight("upload", None, "design.pdf") == 2
    assert automatic_weight("upload", None, "meeting notes.md") == 1
    assert source_weight("wikipedia", None, "HMAC", 3) == 3  # the admin's choice wins


def test_the_model_is_told_each_excerpts_weight():
    block = weights_block([chunk(), chunk("wiki/HMAC", 2)])
    assert "- a/signer.py: PRIMARY (weight 3)" in block
    assert "- wiki/HMAC: SECONDARY (weight 2)" in block


class Agent:
    def __init__(self, reply):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.reply, self.calls = reply, []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system, content=turns[-1].content))
        outcome.model = model
        yield self.reply


def test_an_answer_resting_on_secondary_sources_says_so():
    agent = Agent("HMAC was published in 1996 [wiki/HMAC:10-20].")
    done = list(
        Assistant([agent]).respond(
            "When was HMAC published?", [chunk("wiki/HMAC", 2)], (), "auto", Options()
        )
    )[-1][1]
    assert done["source_basis"] == "secondary"
    assert done["answer"].startswith("This is based on secondary sources only.\n\nHMAC was")
    assert "For every claim in your answer, weight the source by:" in agent.calls[0].system
    assert "<source_weights>" in agent.calls[0].content


def test_an_answer_with_a_primary_source_is_left_as_it_is():
    agent = Agent("It splits the value [a/signer.py:10-20].")
    done = list(
        Assistant([agent]).respond("How?", [chunk(), chunk("wiki/HMAC", 2)], (), "auto", Options())
    )[-1][1]
    assert done["source_basis"] == "primary"
    assert done["answer"] == "It splits the value [a/signer.py:10-20]."


def test_excerpts_carry_their_sources_weight_and_the_admin_can_change_it(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "admin_token", "secret")
    found = client.get("/search", params={"q": "format name"}).json()["results"]
    assert found[0]["weight"] == 3  # pkg/models.py, from a repository

    sources = {s["title"]: s for s in client.get("/sources").json()}
    turing = sources["Alan Turing (Wikipedia)"]
    assert (turing["weight"], turing["weight_override"]) == (2, None)
    assert client.patch(f"/sources/{turing['id']}", json={"weight": 3}).status_code == 401
    changed = client.patch(
        f"/sources/{turing['id']}", json={"weight": 3}, headers={"Authorization": "Bearer secret"}
    ).json()
    assert (changed["weight"], changed["weight_override"]) == (3, 3)
    reset = client.patch(
        f"/sources/{turing['id']}",
        json={"weight": None},
        headers={"Authorization": "Bearer secret"},
    ).json()
    assert reset["weight"] == 2
