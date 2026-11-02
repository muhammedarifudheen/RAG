"""Heuristic knowledge-graph facts from a passage."""

from worker.knowledge import Fact, facts

TEXT = """**HMAC** was published in 1996 by Mihir Bellare, Ran Canetti and Hugo Krawczyk.
The Internet Engineering Task Force adopted it. Signing uses `Signer.sign` and checks
with `verify_signature`.

```python
signer = TimestampSigner(key)
value = signer.unsign(token, max_age=60)
```

Alan Turing (born 1912) was a mathematician."""


def test_a_passage_yields_concepts_entities_people_and_code():
    found = {(f.node, f.name): f for f in facts(TEXT, "Cryptography › History")}
    assert found[("concept", "History")] == Fact("mentioned_in", "concept", "History", 0.9)
    assert ("concept", "HMAC") in found
    assert found[("person", "Mihir Bellare")].confidence == 0.6
    assert found[("person", "Alan Turing")].kind == "mentioned_in"
    assert ("entity", "Internet Engineering Task Force") in found
    assert found[("code", "Signer.sign")].kind == "references"
    assert found[("code", "verify_signature")].kind == "references"
    assert found[("code", "TimestampSigner")].kind == "example_of"


def test_generic_headings_are_not_concepts():
    assert not [f for f in facts("Some text.", "Overview") if f.node == "concept"]
