"""Are the golden set's ABSENT questions really absent from the corpus?

The corpus is read through the public API (`/graph/files`, `/file`), then each question is tried
five ways against all of it, not just the vector index:

- cosine: every 12-line window of every file is embedded (`/v1/embeddings`, the model the server
  uses) and compared with each variant; the best window per variant, flagged over 0.80;
- BM25: a keyword ranking over the same windows;
- grep: the question's distinguishing terms searched in the raw text, case-insensitively;
- the server's own hybrid `/search`, top 3 files.

It reports numbers and the lines to read; a person makes the call (the script does not classify).

    python -m evals.verify_absent --api https://atlas-api-uxze.onrender.com
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HERE = Path(__file__).resolve().parent
WINDOW, STEP = 12, 6

# question id -> (grep terms, four more phrasings of the same need; the golden question is the fifth)
CASES: dict[str, tuple[list[str], list[str]]] = {
    "F-A01": (
        ["revok", "revocation", "blacklist", "blocklist", "invalidat", "denylist"],
        [
            "invalidate a signed token before expiry",
            "token revocation blacklist itsdangerous",
            "cancel a previously issued signature",
            "make a signed value stop working early",
        ],
    ),
    "F-A02": (
        ["flask", "session cookie", "sessioninterface"],
        [
            "itsdangerous flask session cookie signing",
            "flask secure cookie session serializer",
            "use signer with flask app secret key",
            "flask session",
        ],
    ),
    "F-A03": (
        ["encrypt", "fernet", "cryptography", "aes", "cipher", "confidential"],
        [
            "encrypt the payload of a token library",
            "fernet encryption signed payload confidentiality",
            "keep token contents secret not just signed",
            "authenticated encryption of data in a token",
        ],
    ),
    "F-A04": (
        ["java", "javax", "jvm"],
        [
            "HMAC in Java javax.crypto Mac",
            "Java example computing keyed hash",
            "javax.crypto.Mac getInstance HmacSHA256",
            "java hmac",
        ],
    ),
    "F-A05": (
        [
            "88aab3ede8d3adf94d26ab90d3bafd4a2083070c3bcce9c014ee04a443847c0b",
            "'hello'",
            '"hello"',
            "b'secret'",
        ],
        [
            "HMAC-SHA256 of hello with key secret",
            "hex digest for message hello and key secret",
            "compute hmac sha256 hello secret value",
            "hmac sha256 test vector hello secret",
        ],
    ),
    "F-A06": (
        ["companies", "customers", "used by", "in production", "adopters", "users include"],
        [
            "companies using itsdangerous in production",
            "who uses itsdangerous",
            "itsdangerous adopters customers users",
            "organisations that deploy itsdangerous",
        ],
    ),
    "F-A07": (
        ["conda", "pip install", "install", "windows"],
        [
            "install itsdangerous conda",
            "conda install itsdangerous windows",
            "itsdangerous installation instructions windows",
            "pip or conda to install itsdangerous",
        ],
    ),
    "F-A08": (
        ["blake2", "blake", "performance", "benchmark", "faster", "slower", "throughput"],
        [
            "HMAC SHA256 versus BLAKE2 speed",
            "blake2 keyed hashing performance comparison",
            "benchmark hmac against blake2b keyed mode",
            "which is faster hmac or blake2",
        ],
    ),
    "F-A09": (
        ["licen", "bsd", "mit license", "copyright (c)", "apache"],
        [
            "itsdangerous license",
            "software licence terms of itsdangerous",
            "is itsdangerous BSD or MIT licensed",
            "open source license of the library",
        ],
    ),
    "F-A10": (
        ["asyncio", "async def", "await ", "coroutine", "trio", "anyio"],
        [
            "itsdangerous asyncio async await",
            "use signer in an async application",
            "async serializer coroutine itsdangerous",
            "is itsdangerous thread safe or async safe",
        ],
    ),
    "V-03": (
        ["world cup", "fifa", "football", "soccer", "argentina", "messi"],
        [
            "FIFA World Cup 2022 winner",
            "who won the 2022 world cup",
            "football world cup 2022 champion",
            "world cup final 2022 Qatar",
        ],
    ),
    "V-05": (
        ["aes", "encrypt", "cipher"],
        [
            "Signer.sign encrypts payload AES",
            "does sign use AES encryption",
            "itsdangerous sign function encryption algorithm",
            "Signer.sign cipher",
        ],
    ),
}


def get(api: str, path: str) -> dict:
    with urllib.request.urlopen(f"{api.rstrip('/')}{path}", timeout=180) as r:
        return json.loads(r.read())


def embed(api: str, texts: list[str]) -> list[list[float]]:
    out: list[list[float]] = []
    for i in range(0, len(texts), 16):
        body = json.dumps({"input": texts[i : i + 16], "model": "atlas-embed"}).encode()
        request = urllib.request.Request(
            f"{api.rstrip('/')}/v1/embeddings", body, {"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(request, timeout=180) as r:
            data = json.loads(r.read())["data"]
        out += [d["embedding"] for d in sorted(data, key=lambda d: d["index"])]
    return out


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


def bm25(query: str, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> list[float]:
    n = len(docs)
    avg = sum(len(d) for d in docs) / n
    df: Counter[str] = Counter(t for d in docs for t in set(d))
    scores = []
    for d in docs:
        tf = Counter(d)
        s = 0.0
        for t in set(tokens(query)):
            if t in tf:
                idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
                s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avg))
        scores.append(s)
    return scores


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--golden", type=Path, default=HERE / "golden" / "golden_set.jsonl")
    p.add_argument("--out", type=Path, default=HERE / "reports" / "verify_absent.json")
    args = p.parse_args(argv)

    questions = {
        json.loads(line)["id"]: json.loads(line)["question"]
        for line in args.golden.read_text("utf-8").splitlines()
        if line.strip()
    }
    paths = [n["path"] for n in get(args.api, "/graph/files")["nodes"]]
    paths += ["wikipedia/en/HMAC"]
    # The docs page's path is not listed with the code; find it through a search.
    for hit in get(args.api, "/search?q=hmac.new+digestmod&limit=20")["results"]:
        if hit["file"] not in paths:
            paths.append(hit["file"])
    corpus = {}
    for path in paths:
        try:
            corpus[path] = get(args.api, "/file?" + urllib.parse.urlencode({"path": path}))[
                "content"
            ]
        except (
            OSError,
            ValueError,
            KeyError,
        ) as error:  # a listed file that cannot be read is reported, not hidden
            print("could not read", path, error)
    print(f"{len(corpus)} files, {sum(len(t.splitlines()) for t in corpus.values())} lines")

    windows = []
    for path, text in corpus.items():
        lines = text.splitlines()
        for start in range(0, max(len(lines), 1), STEP):
            chunk = lines[start : start + WINDOW]
            if chunk:
                windows.append({"file": path, "start": start + 1, "text": "\n".join(chunk)})
    print(f"{len(windows)} windows; embedding", flush=True)
    vectors = embed(args.api, [w["text"][:2000] for w in windows])
    docs = [tokens(w["text"]) for w in windows]

    report = {}
    for qid, (terms, variants) in CASES.items():
        phrasings = [questions[qid], *variants]
        embedded = embed(args.api, phrasings)
        per_variant = []
        for text, vector in zip(phrasings, embedded, strict=True):
            sims = [cosine(vector, v) for v in vectors]
            best = max(range(len(sims)), key=sims.__getitem__)
            keyword = bm25(text, docs)
            top = sorted(range(len(keyword)), key=lambda i: -keyword[i])[:3]
            hits = get(args.api, "/search?" + urllib.parse.urlencode({"q": text, "limit": 3}))
            per_variant.append(
                {
                    "variant": text,
                    "best_cosine": round(sims[best], 3),
                    "best_window": f"{windows[best]['file']}:{windows[best]['start']}",
                    "over_0.80": sims[best] > 0.80,
                    "bm25_top3": [
                        f"{windows[i]['file'].split('/')[-1]}:{windows[i]['start']} ({keyword[i]:.1f})"
                        for i in top
                    ],
                    "search_top3": [
                        f"{r['file'].split('/')[-1]}:{r['start_line']} ({r['score']:.2f})"
                        for r in hits["results"]
                    ],
                }
            )
        grep = []
        for term in terms:
            for path, text in corpus.items():
                for number, line in enumerate(text.splitlines(), 1):
                    if term.lower() in line.lower():
                        grep.append(
                            f"{term!r} {path.split('/')[-1]}:{number}: {line.strip()[:110]}"
                        )
        report[qid] = {
            "question": questions[qid],
            "max_cosine": max(v["best_cosine"] for v in per_variant),
            "any_over_0.80": any(v["over_0.80"] for v in per_variant),
            "grep_matches": len(grep),
            "grep": grep[:25],
            "variants": per_variant,
        }
        print(
            qid,
            "max cosine",
            report[qid]["max_cosine"],
            "grep matches",
            len(grep),
            flush=True,
        )
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
