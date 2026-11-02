"""MinHash signatures, to find near-duplicate passages across sources quickly.

A passage's word 3-grams are hashed under 64 permutations; the share of positions where
two signatures agree estimates their Jaccard similarity. Locality-sensitive hashing (16
bands of 4) finds the candidate pairs without comparing every passage with every other."""

from __future__ import annotations

import hashlib
import re
import struct
from collections import defaultdict
from collections.abc import Iterable

PERMUTATIONS = 64
BANDS, ROWS = 16, 4
# Near-duplicates: an estimated Jaccard similarity of at least this (the estimate from 64
# permutations is within about 0.1 of the true value).
THRESHOLD = 0.7
# Passages with fewer distinct 3-grams than this are too short to call duplicates.
MIN_SHINGLES = 20

_PRIME = (1 << 61) - 1
_MAX = (1 << 32) - 1
# Fixed, so signatures computed at different times compare.
_A = [((i + 1) * 0x9E3779B97F4A7C15) % _PRIME | 1 for i in range(PERMUTATIONS)]
_B = [((i + 7) * 0xC2B2AE3D27D4EB4F) % _PRIME for i in range(PERMUTATIONS)]
_WORD = re.compile(r"[a-z0-9_]+")


def shingles(text: str) -> set[int]:
    words = _WORD.findall(text.lower())
    grams = {" ".join(words[i : i + 3]) for i in range(max(0, len(words) - 2))}
    return {
        int.from_bytes(hashlib.blake2b(g.encode(), digest_size=8).digest(), "big") for g in grams
    }


def signature(text: str) -> bytes | None:
    """64 x 32-bit minimums, packed; None for a passage too short to compare."""
    hashed = shingles(text)
    if len(hashed) < MIN_SHINGLES:
        return None
    values = [
        min(((a * h + b) % _PRIME) & _MAX for h in hashed) for a, b in zip(_A, _B, strict=True)
    ]
    return struct.pack(f">{PERMUTATIONS}I", *values)


def similarity(a: bytes, b: bytes) -> float:
    left = struct.unpack(f">{PERMUTATIONS}I", a)
    right = struct.unpack(f">{PERMUTATIONS}I", b)
    return sum(x == y for x, y in zip(left, right, strict=True)) / PERMUTATIONS


def pairs(
    new: Iterable[tuple[int, bytes]], old: Iterable[tuple[int, bytes]]
) -> list[tuple[int, int, float]]:
    """(new id, old id, similarity) for every near-duplicate pair between the two sets."""
    buckets: dict[tuple[int, bytes], list[tuple[int, bytes]]] = defaultdict(list)
    for key, sig in old:
        for band in range(BANDS):
            buckets[(band, sig[band * ROWS * 4 : (band + 1) * ROWS * 4])].append((key, sig))
    found: dict[tuple[int, int], float] = {}
    for key, sig in new:
        for band in range(BANDS):
            for other, other_sig in buckets.get(
                (band, sig[band * ROWS * 4 : (band + 1) * ROWS * 4]), ()
            ):
                if (key, other) in found:
                    continue
                score = similarity(sig, other_sig)
                if score >= THRESHOLD:
                    found[(key, other)] = score
    return [(a, b, s) for (a, b), s in found.items()]
