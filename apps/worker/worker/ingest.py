"""CLI: python -m worker.ingest <url> | --file <path>"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from worker.config import settings
from worker.pipeline import IngestError, ingest_upload, ingest_url


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m worker.ingest",
        description="Add a source to the knowledge base: a GitHub repository, a web page, "
        "a Wikipedia article, a crawl of one site, or a local file. Adding a source again "
        "replaces the earlier copy of it; other sources are left alone.",
    )
    parser.add_argument(
        "url",
        nargs="?",
        help="https://github.com/owner/repo, a Wikipedia article link, or any web page",
    )
    parser.add_argument("--file", type=Path, help="a PDF, EPUB, text, Markdown or HTML file")
    parser.add_argument(
        "--crawl",
        type=int,
        metavar="PAGES",
        help="follow links on the same site, up to this many pages (at most 100)",
    )
    parser.add_argument(
        "--keep-clone", action="store_true", help="do not delete a repository clone when finished"
    )
    args = parser.parse_args(argv)
    if bool(args.url) == bool(args.file):
        parser.error("give either a URL or --file")

    def progress(message: str) -> None:
        print(message, flush=True)

    started = time.monotonic()
    try:
        if args.file:
            if not args.file.is_file():
                raise IngestError(f"No such file: {args.file}")
            result = ingest_upload(args.file, args.file.name, settings=settings, progress=progress)
        else:
            result = ingest_url(
                args.url,
                settings=settings,
                kind="crawl" if args.crawl else "auto",
                max_pages=args.crawl or 20,
                keep_clone=args.keep_clone,
                progress=progress,
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
