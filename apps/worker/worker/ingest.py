"""CLI: python -m worker.ingest <repo_url>"""

from __future__ import annotations

import argparse
import sys
import time

from worker.config import settings
from worker.pipeline import IngestError, ingest_repo


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m worker.ingest",
        description="Clone a GitHub repository, extract its code graph and store it in Postgres. "
        "Replaces whatever repository was ingested before.",
    )
    parser.add_argument("repo_url", help="https://github.com/owner/repo")
    parser.add_argument(
        "--keep-clone", action="store_true", help="do not delete the clone when finished"
    )
    args = parser.parse_args(argv)

    started = time.monotonic()
    try:
        result = ingest_repo(
            args.repo_url,
            settings=settings,
            keep_clone=args.keep_clone,
            progress=lambda message: print(message, flush=True),
        )
    except IngestError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    elapsed = time.monotonic() - started
    print(
        f"Done in {elapsed:.1f}s: {result.files} files, "
        f"{result.symbols} symbols, {result.edges} edges."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
