"""The 100x answer: freshness (FRESH / RECENT / STALE), newer sources first, diversity
(MMR), and the TL;DR → detail → action format."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.assistant.prompt import context_blocks
from app.assistant.service import Assistant, Options, with_footer
from app.schemas import CodeChunk
from app.services.freshness import answer_freshness, category, label, prefer_newer
from app.services.search import diversify

NOW = datetime(2026, 11, 3, tzinfo=UTC)


def chunk(symbol_id, *, file="a/signer.py", score=0.8, snippet="def unsign(self): ...", days=1,
          updated=None, relevance=None, freshness=None):  # fmt: skip
    return CodeChunk(
        symbol_id=symbol_id, name="Signer.unsign", kind="method", file=file, language="python",
        start_line=10, end_line=20, signature=None, score=score, snippet=snippet,
        snippet_end_line=20, truncated=False, citation=f"[{file}:10-20]", relevance=relevance,
        ingested_at=NOW - timedelta(days=days), source_updated_at=updated, freshness=freshness,
    )  # fmt: skip


def test_freshness_depends_on_the_kind_of_source():
    assert category("repo", "https://github.com/a/b", "a/b/x.py") == "code"
    assert category("upload", None, "uploads/signer.go") == "code"
    assert category("web", "https://www.reuters.com/tech/x", "web/x") == "news"
    assert (
        category("wikipedia", "https://en.wikipedia.org/wiki/HMAC", "wikipedia/en/HMAC") == "docs"
    )
    # Code: fresh within 10 days, recent within 30, stale beyond.
    assert label(NOW - timedelta(days=5), "code", NOW) == "fresh"
    assert label(NOW - timedelta(days=20), "code", NOW) == "recent"
    assert label(NOW - timedelta(days=31), "code", NOW) == "stale"
    # Docs: 90 days; news: 7.
    assert label(NOW - timedelta(days=60), "docs", NOW) == "recent"
    assert label(NOW - timedelta(days=8), "news", NOW) == "stale"
    assert label(None, "docs", NOW) is None


def test_an_answer_is_as_fresh_as_the_freshest_source_it_used():
    old = {"file": "a.py", "freshness": "stale", "ingested_at": NOW - timedelta(days=100)}
    new = {"file": "b.py", "freshness": "fresh", "ingested_at": NOW - timedelta(days=1)}
    assert answer_freshness([old, new], {"a.py", "b.py"})["label"] == "fresh"
    # Only the sources it cited count.
    assert answer_freshness([old, new], {"a.py"})["label"] == "stale"
    assert answer_freshness([{"file": "c.py"}], {"c.py"}) is None


def test_a_stale_answer_opens_with_a_warning_and_the_footer_carries_freshness():
    stale = NOW - timedelta(days=200)
    data = {
        "answer": "TL;DR: it signs.",
        "epistemic": "known",
        "citations": [{"file": "a.py", "verified": True}],
        "chunks": [{"file": "a.py", "freshness": "stale", "ingested_at": stale}],
    }
    done = with_footer(data, Options())
    assert (
        done["answer"]
        == f"⚠ This may be outdated — last ingested {stale:%Y-%m-%d}.\n\nTL;DR: it signs."
    )
    assert done["footer"] == "[confidence: KNOWN] [freshness: STALE] [sources: 1]"
    assert done["freshness"]["label"] == "stale"
    # Not warned twice.
    assert with_footer(done, Options())["answer"].count("⚠") == 1


def test_of_two_equally_good_excerpts_the_newer_source_goes_first():
    older = chunk(1, score=0.80, updated=NOW - timedelta(days=300))
    newer = chunk(2, score=0.795, updated=NOW - timedelta(days=3))
    clearly_better = chunk(3, score=0.95, updated=NOW - timedelta(days=900))
    assert [c.symbol_id for c in prefer_newer([older, newer])] == [2, 1]
    # A clearly better excerpt keeps its place, however old.
    assert [c.symbol_id for c in prefer_newer([clearly_better, newer])] == [3, 2]
    # So does one the judge rated higher.
    judged = chunk(4, score=0.80, relevance=9, updated=NOW - timedelta(days=300))
    assert [c.symbol_id for c in prefer_newer([judged, chunk(5, score=0.80, relevance=6)])] == [
        4,
        5,
    ]


def test_near_duplicates_give_way_to_other_excerpts():
    text = "def sign(value, key): return hmac.new(key, value, sha256).digest()"
    first = chunk(1, snippet=text)
    copy = chunk(2, file="b/signer.py", snippet=text)
    other = chunk(3, file="c/verify.py", snippet="def verify(sig): compare_digest(sig, expected)")
    assert [c.symbol_id for c in diversify([first, copy, other], 2)] == [1, 3]
    # Distinct excerpts keep their order.
    assert [c.symbol_id for c in diversify([first, other], 2)] == [1, 3]


def test_each_excerpt_says_when_its_source_changed_and_was_ingested():
    block = context_blocks([chunk(1, days=2, updated=datetime(2026, 9, 1, tzinfo=UTC))])
    assert block.startswith(
        "[a/signer.py:10-20] (source updated 2026-09-01, ingested 2026-11-01)\n10| "
    )


class Agent:
    def __init__(self):
        self.name, self.label, self.models = "gemini", "Gemini", ["g1"]
        self.calls = []

    def searches(self, model):
        return False

    def stream(self, model, system, turns, outcome, *, web, temperature=None, max_tokens=None):
        self.calls.append(SimpleNamespace(system=system))
        outcome.model = model
        yield "TL;DR: it splits [a/signer.py:10-20].\n\nAction: call unsign."


def test_answers_from_the_sources_follow_the_tldr_detail_action_format():
    agent = Agent()
    list(Assistant([agent]).respond("q", [chunk(1)], (), "auto", Options(about_sources=True)))
    system = agent.calls[0].system
    assert "TL;DR: <one or two lines" in system and "Action: <one concrete next step" in system
    assert 'after a line "Previous version:"' in system
    # The user's own instructions still come last.
    agent = Agent()
    list(Assistant([agent]).respond("q", [chunk(1)], (), "auto",
                                    Options(about_sources=True, instructions="Be brief.")))  # fmt: skip
    assert agent.calls[0].system.rstrip().endswith("Be brief.")
