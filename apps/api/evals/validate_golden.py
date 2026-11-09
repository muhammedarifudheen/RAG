"""Checks a golden set before it is used:

1. every relevant path exists in the knowledge base (and every line range is inside its file);
2. every expected_state is one Atlas knows;
3. the categories match the spec (20 failure modes, 10 multi-hop, 5 code traces, 5 adversarial);
4. no two questions are near-duplicates (cosine similarity over 0.95);
5. vector-only search leaves headroom: mean nDCG@10 (over files) under 0.85.

    python -m evals.validate_golden --api https://atlas-api-uxze.onrender.com \\
        --golden evals/golden/golden_set.jsonl --out evals/golden/validation_report.md

Exit status 1 if any check fails. Only check 4 needs more than the standard library: it embeds
the questions with the same model the server uses (the worker's ONNX copy of all-MiniLM-L6-v2),
and fails, rather than skips, if that is not available.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import sys
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from evals.metrics import Hit, Target, score_retrieval

HERE = Path(__file__).resolve().parent
STATES = {"KNOWN", "INFERRED", "PARTIAL", "ABSENT", "CONFLICTED", "REFUSED"}
# category -> required count, grouped as the spec does (20/10/5/5)
SPEC = {"failure": 20, "multi-hop": 10, "code-trace": 5, "adversarial": 5}
GROUP = {
    "fail-partial": "failure",
    "fail-absent": "failure",
    "multi-hop": "multi-hop",
    "code-trace": "code-trace",
    "adversarial": "adversarial",
}
DUPLICATE_COSINE = 0.95
HEADROOM_BELOW = 0.85


@dataclass
class Check:
    name: str
    passed: bool = True
    details: list[str] = field(default_factory=list)

    def fail(self, message: str) -> None:
        self.passed = False
        self.details.append(f"FAIL {message}")

    def note(self, message: str) -> None:
        self.details.append(message)


def get(api: str, route: str, **params) -> dict:
    url = f"{api.rstrip('/')}{route}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=120) as response:
        return json.loads(response.read())


def load(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def stored_paths(api: str) -> set[str]:
    """Every file path in the knowledge base that can be found: the code files from the graph,
    plus the pages of document sources, which show up in search results."""
    paths = {n["path"] for n in get(api, "/graph/files")["nodes"]}
    for probe in ("HMAC", "hmac module digestmod", "itsdangerous signer", "Wikipedia HMAC article"):
        paths |= {r["file"] for r in get(api, "/search", q=probe, limit=50)["results"]}
    return paths


def resolve(path: str, known: set[str]) -> list[str]:
    path = path.replace("\\", "/")
    return sorted(p for p in known if p == path or p.endswith("/" + path))


def check_paths(items: list[dict], api: str) -> Check:
    check = Check("1. Every relevant_path exists in the knowledge base")
    known = stored_paths(api)
    check.note(f"{len(known)} files found in the knowledge base")
    lengths: dict[str, int] = {}
    checked = 0
    for item in items:
        for raw in item["relevant_paths"]:
            file = raw if isinstance(raw, str) else raw["file"]
            found = resolve(file, known)
            checked += 1
            if len(found) != 1:
                reason = "no such file" if not found else f"ambiguous: {', '.join(found)}"
                check.fail(f"{item['id']}: {file} ({reason})")
                continue
            if isinstance(raw, dict) and raw.get("lines"):
                if found[0] not in lengths:
                    lengths[found[0]] = len(
                        get(api, "/file", path=found[0])["content"].splitlines()
                    )
                start, end = raw["lines"]
                if not (1 <= start <= end <= lengths[found[0]]):
                    check.fail(
                        f"{item['id']}: {file} lines {start}-{end} outside 1-{lengths[found[0]]}"
                    )
    check.note(f"{checked} path references checked")
    return check


def check_states(items: list[dict]) -> Check:
    check = Check("2. Every expected_state is valid")
    for item in items:
        if item.get("expected_state") not in STATES:
            check.fail(f"{item['id']}: {item.get('expected_state')!r}")
    counts = Counter(i["expected_state"] for i in items)
    check.note("states: " + ", ".join(f"{s} {counts.get(s, 0)}" for s in sorted(STATES)))
    return check


def check_distribution(items: list[dict]) -> Check:
    check = Check("3. Difficulty distribution matches the spec (20 / 10 / 5 / 5)")
    counts = Counter(
        GROUP.get(i.get("category", ""), f"unknown:{i.get('category')}") for i in items
    )
    for group, want in SPEC.items():
        have = counts.get(group, 0)
        (check.note if have == want else check.fail)(f"{group}: {have} (spec {want})")
    for group in counts:
        if group not in SPEC:
            check.fail(f"unexpected category {group}")
    ids = [i["id"] for i in items]
    if len(set(ids)) != len(ids):
        check.fail("duplicate ids")
    check.note(f"{len(items)} entries in all")
    return check


def embed(texts: list[str]) -> list[list[float]]:
    from worker.embed import LocalEmbedder

    return LocalEmbedder("sentence-transformers/all-MiniLM-L6-v2").encode(texts)


def check_duplicates(items: list[dict]) -> Check:
    check = Check(f"4. No near-duplicate questions (cosine over {DUPLICATE_COSINE})")
    try:
        vectors = embed([i["question"] for i in items])
    except (
        ImportError,
        OSError,
        RuntimeError,
        ValueError,
    ) as error:  # cannot embed: no package or model
        check.fail(f"could not embed the questions ({type(error).__name__}: {error})")
        return check
    pairs = []
    for (a, va), (b, vb) in itertools.combinations(zip(items, vectors, strict=True), 2):
        dot = sum(x * y for x, y in zip(va, vb, strict=True))
        norm = math.sqrt(sum(x * x for x in va)) * math.sqrt(sum(y * y for y in vb))
        pairs.append((dot / norm if norm else 0.0, a["id"], b["id"]))
    pairs.sort(reverse=True)
    for cosine, a, b in pairs:
        if cosine > DUPLICATE_COSINE:
            check.fail(f"{a} and {b}: cosine {cosine:.3f}")
    check.note(
        f"{len(pairs)} pairs compared; the closest: "
        + ", ".join(f"{a}/{b} {c:.3f}" for c, a, b in pairs[:3])
    )
    return check


def check_headroom(items: list[dict], api: str) -> tuple[Check, list[tuple[str, float]]]:
    check = Check(f"5. Vector-only baseline leaves headroom (mean nDCG@10 under {HEADROOM_BELOW})")
    scores: list[tuple[str, float]] = []
    for item in items:
        if not item["relevant_paths"]:
            continue  # nothing to retrieve: absent and refused entries have no nDCG
        results = get(api, "/search", q=item["question"], limit=10)["results"]
        hits = [Hit(r["file"], r["start_line"], r["end_line"]) for r in results]
        targets = [Target.parse(t) for t in item["relevant_paths"]]
        scores.append((item["id"], score_retrieval(hits, targets, ks=(10,)).ndcg_at[10]))
    mean = sum(s for _, s in scores) / len(scores) if scores else 0.0
    check.note(f"{len(scores)} questions with a retrieval target; mean nDCG@10 = {mean:.3f}")
    if mean >= HEADROOM_BELOW:
        check.fail(f"mean nDCG@10 {mean:.3f} is at or above {HEADROOM_BELOW}: too easy")
    return check, scores


def report(checks: list[Check], scores: list[tuple[str, float]], golden: Path, api: str) -> str:
    lines = [
        "# Golden set validation",
        "",
        f"`{golden.name}` against `{api}`. "
        + (
            "**All checks passed.**" if all(c.passed for c in checks) else "**Some checks failed.**"
        ),
        "",
        "| Check | Result |",
        "| --- | --- |",
    ]
    lines += [f"| {c.name} | {'PASS' if c.passed else 'FAIL'} |" for c in checks]
    for check in checks:
        lines += ["", f"## {check.name}: {'PASS' if check.passed else 'FAIL'}", ""]
        lines += [f"- {d}" for d in check.details]
    if scores:
        lines += [
            "",
            "## nDCG@10 by question (vector-only)",
            "",
            "| Id | nDCG@10 |",
            "| --- | --- |",
        ]
        lines += [f"| {i} | {s:.3f} |" for i, s in sorted(scores, key=lambda x: x[1])]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--out", type=Path, default=HERE / "golden" / "validation_report.md")
    args = p.parse_args(argv)

    items = load(args.golden)
    headroom, scores = check_headroom(items, args.api)
    checks = [
        check_paths(items, args.api),
        check_states(items),
        check_distribution(items),
        check_duplicates(items),
        headroom,
    ]
    text = report(checks, scores, args.golden, args.api)
    args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0 if all(c.passed for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
