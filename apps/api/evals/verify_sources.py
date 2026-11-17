"""Checks each source in the knowledge base is there and retrievable.

    python -m evals.verify_sources --api https://atlas-api.example.com

For every line of `golden/sources.jsonl` ({"url": ..., "phrase": ...}) it checks that:
  1. the source is listed by `/sources` with more than 0 searchable symbols; and
  2. a raw vector search (`/search`) for a phrase known to be on that page returns a passage of
     that source among the top results (or one it duplicates, `also_seen_in`).

A source that fails (1) did not ingest; one that fails only (2) ingested but is not found by
its own words, which points at chunking or extraction rather than at the source. Exit status 1
if any source fails. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def get(url: str, timeout: float) -> object:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def normal(url: str | None) -> str:
    """A link without its scheme, `www.`, fragment and trailing slash, for comparing."""
    if not url:
        return ""
    parts = urllib.parse.urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.")
    return f"{host}{parts.path}".rstrip("/")


def load(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            rows.append(json.loads(line))
    return rows


def check(base: str, rows: list[dict], top: int, timeout: float) -> list[dict]:
    listed = {normal(s.get("url")): s for s in get(f"{base}/sources", timeout)}  # type: ignore[union-attr]
    results = []
    for row in rows:
        source = listed.get(normal(row["url"]))
        result = {
            "url": row["url"],
            "phrase": row["phrase"],
            "symbols": source["symbols"] if source else None,
            "listed": source is not None and source["symbols"] > 0,
            "rank": None,
            "score": None,
            "error": None,
        }
        if source is not None:
            query = urllib.parse.urlencode({"q": row["phrase"], "limit": top})
            try:
                found = get(f"{base}/search?{query}", timeout)["results"]  # type: ignore[index]
            except (urllib.error.URLError, TimeoutError, KeyError, ValueError) as error:
                result["error"] = f"{type(error).__name__}: {error}"
                found = []
            for rank, chunk in enumerate(found, 1):
                own = normal(chunk.get("source_url")) == normal(row["url"])
                duplicate = source["title"] in (chunk.get("also_seen_in") or [])
                if own or duplicate:
                    result["rank"], result["score"] = rank, chunk["score"]
                    break
        results.append(result)
    return results


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--api", default="http://localhost:8000")
    p.add_argument("--sources", type=Path, default=HERE / "golden" / "sources.jsonl")
    p.add_argument("--top", type=int, default=10, help="how far down the results to look")
    p.add_argument("--timeout", type=float, default=120)
    args = p.parse_args(argv)

    results = check(args.api.rstrip("/"), load(args.sources), args.top, args.timeout)
    width = max(len(r["url"]) for r in results)
    failed = 0
    for r in results:
        if not r["listed"]:
            status = "NOT INGESTED" if r["symbols"] is None else "EMPTY (0 symbols)"
        elif r["rank"] is None:
            status = f"INGESTED ({r['symbols']} symbols) but not in the top {args.top} for its phrase"
        else:
            status = f"ok: {r['symbols']} symbols; {r['phrase']!r} at rank {r['rank']} (score {r['score']:.2f})"
        failed += status[:2] != "ok"
        print(f"{r['url']:<{width}}  {status}")
    print(f"\n{len(results) - failed} of {len(results)} sources verified")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
