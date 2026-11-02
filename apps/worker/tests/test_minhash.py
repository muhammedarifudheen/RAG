"""Near-duplicate passages, found by MinHash."""

from worker.minhash import pairs, signature, similarity

PASSAGE = (
    "HMAC is a specific type of message authentication code involving a cryptographic hash "
    "function and a secret cryptographic key. It may be used to simultaneously verify both "
    "the data integrity and the authenticity of a message, as with any MAC."
)


def test_a_copy_is_a_near_duplicate_and_another_text_is_not():
    original = signature(PASSAGE)
    copy = signature(PASSAGE.replace("specific type", "specific kind"))
    other = signature(
        "TimestampSigner adds a timestamp to the signature, so the age of a signed value can "
        "be checked when it is unsigned, and values older than max_age are refused outright."
    )
    assert similarity(original, signature(PASSAGE)) == 1.0
    assert similarity(original, copy) >= 0.7
    assert similarity(original, other) < 0.3
    assert pairs([(1, copy), (2, other)], [(10, original)]) == [(1, 10, similarity(copy, original))]


def test_short_passages_are_not_compared():
    assert signature("def sign(value): return hmac(value)") is None
