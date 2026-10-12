"""Loaders for the non-code sources: web pages, Wikipedia, site crawls and uploaded files.

Each returns a title and a list of documents; the pipeline does the rest.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
import zipfile
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote, urldefrag, urljoin, urlsplit
from xml.etree import ElementTree

from worker.documents import Document, document_path
from worker.fetch import USER_AGENT, FetchError, fetch, robots_for

Progress = Callable[[str], None]

MAX_CRAWL_PAGES = 100
MAX_CRAWL_DEPTH = 3
CRAWL_DELAY_SECONDS = 0.5
MAX_UPLOAD_BYTES = 30_000_000
UPLOAD_TYPES = (".pdf", ".epub", ".txt", ".md", ".markdown", ".html", ".htm")

_WIKIPEDIA_HOST = re.compile(r"^([a-z]{2,3}(?:-[a-z0-9-]+)?)\.(?:m\.)?wikipedia\.org$")
_WIKI_HEADING = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.MULTILINE)
_NOT_PAGES = re.compile(
    r"\.(?:png|jpe?g|gif|svg|webp|ico|css|js|json|xml|zip|gz|tar|pdf|mp[34]|avi|mov|woff2?|ttf|exe|dmg)$",
    re.IGNORECASE,
)


class SourceError(Exception):
    """The source could not be loaded; the message is safe to show to the user."""


@dataclass
class Loaded:
    title: str
    url: str | None
    documents: list[Document]


def detect_kind(url: str) -> str:
    """Which loader a pasted link belongs to: repo, wikipedia or web."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    if host == "github.com":
        return "repo"
    if _WIKIPEDIA_HOST.match(host):
        return "wikipedia"
    return "web"


# --- HTML ---------------------------------------------------------------------


def html_to_document(html: bytes | str, path: str, url: str | None, fallback_title: str) -> Document | None:
    """Extracts the readable article text of a page as Markdown, without navigation or ads."""
    import trafilatura  # imported here: it is slow to load and only needed for HTML

    text = trafilatura.extract(
        html,
        output_format="markdown",
        include_comments=False,
        include_tables=True,
        include_links=False,
        include_images=False,
    )
    if not text or not text.strip():
        text = trafilatura.html2txt(html)
    if not text or not text.strip():
        return None
    metadata = trafilatura.extract_metadata(html)
    title = (metadata.title if metadata and metadata.title else fallback_title).strip()
    return Document(path=path, title=title or fallback_title, text=text, url=url)


def _web_path(url: str) -> str:
    parts = urlsplit(url)
    path = parts.path.strip("/") or "index"
    if parts.query:
        path += "_" + parts.query
    return document_path("web", parts.hostname or "site", path)


def load_web(url: str) -> Loaded:
    try:
        page = fetch(url)
    except FetchError as error:
        raise SourceError(str(error)) from error
    if page.content_type not in ("text/html", "application/xhtml+xml", "text/plain"):
        raise SourceError(f"That link is {page.content_type}, not a web page. Upload the file instead.")
    host = urlsplit(page.url).hostname or page.url
    if page.content_type == "text/plain":
        document = Document(_web_path(page.url), host, page.body.decode("utf-8", errors="replace"), page.url)
    else:
        document = html_to_document(page.body, _web_path(page.url), page.url, host)
    if document is None:
        raise SourceError("No readable text was found on that page.")
    return Loaded(document.title, page.url, [document])


# --- Wikipedia ----------------------------------------------------------------


def parse_wikipedia_url(url: str) -> tuple[str, str]:
    """Returns (language, article title) for a Wikipedia article link."""
    parts = urlsplit(url.strip())
    match = _WIKIPEDIA_HOST.match((parts.hostname or "").lower())
    if not match or not parts.path.startswith("/wiki/") or len(parts.path) <= len("/wiki/"):
        raise SourceError("Expected a Wikipedia article link such as https://en.wikipedia.org/wiki/Alan_Turing.")
    return match[1], unquote(parts.path[len("/wiki/") :]).replace("_", " ")


def wikipedia_to_markdown(extract: str) -> str:
    """Wikipedia's plain-text extract marks headings as `== Title ==`."""
    return _WIKI_HEADING.sub(lambda m: f"{'#' * len(m[1])} {m[2]}", extract)


def load_wikipedia(url: str) -> Loaded:
    language, title = parse_wikipedia_url(url)
    # The official API returns clean article text, which scraping the page would not.
    api = (
        f"https://{language}.wikipedia.org/w/api.php?action=query&format=json&formatversion=2"
        f"&prop=extracts&explaintext=1&exsectionformat=wiki&redirects=1&titles={quote(title)}"
    )
    try:
        response = fetch(api, accept="application/json", max_bytes=20_000_000)
        page = json.loads(response.body)["query"]["pages"][0]
    except FetchError as error:
        raise SourceError(str(error)) from error
    except (ValueError, KeyError, IndexError) as error:
        raise SourceError("Wikipedia returned an unexpected response.") from error
    if page.get("missing") or not (page.get("extract") or "").strip():
        raise SourceError(f"Wikipedia has no article called {title!r}.")

    title = page.get("title", title)
    article = f"https://{language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
    document = Document(
        path=document_path("wikipedia", language, title),
        title=title,
        text=wikipedia_to_markdown(page["extract"]),
        url=article,
    )
    return Loaded(f"{title} (Wikipedia)", article, [document])


# --- Site crawl ---------------------------------------------------------------


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


def page_links(html: str, base_url: str) -> list[str]:
    """Links on a page that stay on the same host and look like pages, in document order."""
    parser = _Links()
    with contextlib.suppress(Exception):  # malformed markup just yields fewer links
        parser.feed(html)
    host = urlsplit(base_url).hostname
    found: dict[str, None] = {}
    for href in parser.links:
        url = urldefrag(urljoin(base_url, href.strip()))[0]
        parts = urlsplit(url)
        if parts.scheme in ("http", "https") and parts.hostname == host and not _NOT_PAGES.search(parts.path):
            found.setdefault(url)
    return list(found)


def load_crawl(url: str, max_pages: int, progress: Progress) -> Loaded:
    """Breadth-first crawl of one site, obeying robots.txt, a page limit and a delay."""
    max_pages = max(1, min(max_pages, MAX_CRAWL_PAGES))
    try:
        first = fetch(url)
    except FetchError as error:
        raise SourceError(str(error)) from error

    robots = robots_for(first.url)
    queue: deque[tuple[str, int]] = deque([(first.url, 0)])
    seen = {first.url}
    documents: list[Document] = []
    paths: set[str] = set()
    skipped = 0

    while queue and len(documents) < max_pages:
        page_url, depth = queue.popleft()
        if not robots.can_fetch(USER_AGENT, page_url):
            skipped += 1
            continue
        try:
            page = first if page_url == first.url else fetch(page_url)
        except FetchError:
            skipped += 1
            continue
        if page.content_type not in ("text/html", "application/xhtml+xml"):
            continue

        path = _web_path(page.url)
        document = html_to_document(page.body, path, page.url, urlsplit(page.url).hostname or page.url)
        if document is not None and path not in paths:
            paths.add(path)
            documents.append(document)
            progress(f"fetched {len(documents)}/{max_pages}: {page.url}")

        if depth < MAX_CRAWL_DEPTH:
            for link in page_links(page.body.decode("utf-8", errors="replace"), page.url):
                if link not in seen:
                    seen.add(link)
                    queue.append((link, depth + 1))
        if page_url != first.url:
            time.sleep(CRAWL_DELAY_SECONDS)  # be polite to the site

    if not documents:
        raise SourceError("No readable pages were found. The site may disallow crawling in robots.txt.")
    if skipped:
        progress(f"skipped {skipped} pages (blocked by robots.txt or unreachable)")
    host = urlsplit(first.url).hostname or first.url
    return Loaded(f"{host} ({len(documents)} pages)", first.url, documents)


# --- Uploaded files -----------------------------------------------------------


def _pdf_text(path: Path) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise SourceError("That PDF is password-protected.")
        pages = [(number, (page.extract_text() or "").strip()) for number, page in enumerate(reader.pages, 1)]
    except PdfReadError as error:
        raise SourceError("That file could not be read as a PDF.") from error
    if not any(text for _, text in pages):
        raise SourceError("That PDF has no text layer. Scanned PDFs need OCR, which is not supported.")
    # A heading per page lets a citation be traced back to the page it came from.
    return "\n\n".join(f"## Page {number}\n\n{text}" for number, text in pages if text)


def _epub_text(path: Path) -> str:
    import trafilatura

    namespaces = {
        "c": "urn:oasis:names:tc:opendocument:xmlns:container",
        "o": "http://www.idpf.org/2007/opf",
    }
    try:
        with zipfile.ZipFile(path) as book:
            container = ElementTree.fromstring(book.read("META-INF/container.xml"))
            package_path = container.find(".//c:rootfile", namespaces).attrib["full-path"]
            package = ElementTree.fromstring(book.read(package_path))
            base = PurePosixPath(package_path).parent
            items = {i.attrib["id"]: i.attrib["href"] for i in package.findall(".//o:manifest/o:item", namespaces)}
            chapters = []
            # The spine lists the chapters in reading order.
            for reference in package.findall(".//o:spine/o:itemref", namespaces):
                href = items.get(reference.attrib.get("idref", ""))
                if not href:
                    continue
                html = book.read(str(base / unquote(href)))
                text = trafilatura.extract(html, output_format="markdown", include_links=False)
                text = text or trafilatura.html2txt(html)
                if text and text.strip():
                    chapters.append(text.strip())
    except (zipfile.BadZipFile, KeyError, AttributeError, ElementTree.ParseError) as error:
        raise SourceError("That file could not be read as an EPUB.") from error
    if not chapters:
        raise SourceError("No readable text was found in that EPUB.")
    return "\n\n".join(chapters)


def load_upload(path: Path, filename: str) -> Loaded:
    name = PurePosixPath(filename.replace("\\", "/")).name or "upload"
    suffix = PurePosixPath(name).suffix.lower()
    if suffix not in UPLOAD_TYPES:
        raise SourceError(f"{suffix or 'That file type'} is not supported. Upload one of: {', '.join(UPLOAD_TYPES)}.")
    if path.stat().st_size > MAX_UPLOAD_BYTES:
        raise SourceError(f"That file is larger than {MAX_UPLOAD_BYTES // 1_000_000} MB.")

    title = PurePosixPath(name).stem.replace("_", " ").strip() or name
    document_file = document_path("uploads", name)
    if suffix == ".pdf":
        document = Document(document_file, title, _pdf_text(path))
    elif suffix == ".epub":
        document = Document(document_file, title, _epub_text(path))
    elif suffix in (".html", ".htm"):
        document = html_to_document(path.read_bytes(), document_file, None, title)
        if document is None:
            raise SourceError("No readable text was found in that file.")
    else:
        document = Document(document_file, title, path.read_text(encoding="utf-8", errors="replace"))
    if "\x00" in document.text:
        raise SourceError("That file does not contain readable text.")
    return Loaded(document.title, None, [document])
