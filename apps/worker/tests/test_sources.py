import socket
import zipfile

import pytest

from worker import fetch as fetch_module
from worker import sources
from worker.fetch import Fetched, FetchError, check_public_url
from worker.sources import (
    SourceError,
    detect_kind,
    html_to_document,
    load_crawl,
    load_upload,
    load_web,
    load_wikipedia,
    page_links,
    parse_wikipedia_url,
    wikipedia_to_markdown,
)

PAGE = b"""<!doctype html><html><head><title>Signing data - Example Docs</title></head><body>
<nav><a href="/">Home</a><a href="/pricing">Pricing</a></nav>
<article><h1>Signing data</h1>
<p>A signature proves that a value was produced by someone holding the secret key, and that it
has not been changed since. The signer derives a key, computes a digest and appends it.</p>
<h2>Verifying</h2>
<p>To verify, the signature is recomputed and compared in constant time. If the two differ the
value is rejected, and the caller should treat it as untrusted input from that point on.</p>
<p><a href="/guide/keys.html">Key rotation</a> <a href="https://other.example/x">Elsewhere</a>
<a href="/logo.png">Logo</a> <a href="#top">Top</a> <a href="/guide/keys.html#rotate">Again</a></p>
</article><footer>Copyright Example Corp</footer></body></html>"""


def resolves_to(monkeypatch, *addresses):
    def fake(host, port, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


# --- URL safety -----------------------------------------------------------------


def test_public_addresses_are_allowed(monkeypatch):
    resolves_to(monkeypatch, "93.184.216.34")
    assert check_public_url("https://example.com/a?b=1") == "https://example.com/a?b=1"


@pytest.mark.parametrize(
    "address",
    ["127.0.0.1", "10.0.0.5", "192.168.1.10", "172.16.0.1", "169.254.169.254", "::1", "fd00::1", "0.0.0.0"],
)
def test_private_and_internal_addresses_are_refused(monkeypatch, address):
    resolves_to(monkeypatch, address)
    with pytest.raises(FetchError, match="private or internal"):
        check_public_url("http://looks-innocent.example/")


def test_a_name_with_any_private_address_is_refused(monkeypatch):
    resolves_to(monkeypatch, "93.184.216.34", "10.0.0.5")
    with pytest.raises(FetchError, match="private or internal"):
        check_public_url("https://mixed.example/")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com/",
        "https://user:secret@example.com/",
        "https://example.com:8080/",
        "https://example.com:22/",
        "https:///nohost",
        "not a url",
    ],
)
def test_other_schemes_credentials_and_ports_are_refused(monkeypatch, url):
    resolves_to(monkeypatch, "93.184.216.34")
    with pytest.raises(FetchError):
        check_public_url(url)


def test_redirects_are_checked_like_the_first_address(monkeypatch):
    # A public page that redirects to the cloud metadata service must not be followed.
    def fake(host, port, **kwargs):
        address = "169.254.169.254" if host == "metadata.internal" else "93.184.216.34"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    monkeypatch.setattr(socket, "getaddrinfo", fake)

    class Redirecting:
        def open(self, request, timeout):
            import urllib.error
            from email.message import Message

            headers = Message()
            headers["Location"] = "http://metadata.internal/latest/meta-data/"
            raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

    monkeypatch.setattr(fetch_module, "_opener", Redirecting())
    with pytest.raises(FetchError, match="private or internal"):
        fetch_module.fetch("https://example.com/start")


# --- kinds and Wikipedia ---------------------------------------------------------


def test_links_are_routed_by_host():
    assert detect_kind("https://github.com/pallets/flask") == "repo"
    assert detect_kind("https://en.wikipedia.org/wiki/Alan_Turing") == "wikipedia"
    assert detect_kind("https://de.m.wikipedia.org/wiki/K%C3%B6ln") == "wikipedia"
    assert detect_kind("https://docs.python.org/3/library/hmac.html") == "web"
    assert detect_kind("https://wikipedia.org.evil.example/wiki/X") == "web"


def test_wikipedia_links_give_language_and_title():
    assert parse_wikipedia_url("https://en.wikipedia.org/wiki/Alan_Turing") == ("en", "Alan Turing")
    assert parse_wikipedia_url("https://de.m.wikipedia.org/wiki/K%C3%B6ln") == ("de", "Köln")
    for bad in ("https://en.wikipedia.org/", "https://en.wikipedia.org/w/index.php?title=X", "https://example.com/wiki/X"):
        with pytest.raises(SourceError):
            parse_wikipedia_url(bad)


def test_wikipedia_headings_become_markdown():
    extract = "Intro text.\n\n\n== Early life ==\nBorn in London.\n\n\n=== School ===\nSherborne.\n"
    assert wikipedia_to_markdown(extract) == (
        "Intro text.\n\n\n## Early life\nBorn in London.\n\n\n### School\nSherborne.\n"
    )


def test_wikipedia_article_is_loaded_through_the_api(monkeypatch):
    requested = []

    def fake_fetch(url, **kwargs):
        requested.append(url)
        body = b'{"query":{"pages":[{"title":"Alan Turing","extract":"English mathematician.\\n\\n\\n== Work ==\\nCodebreaking."}]}}'
        return Fetched(url, body, "application/json")

    monkeypatch.setattr(sources, "fetch", fake_fetch)

    loaded = load_wikipedia("https://en.wikipedia.org/wiki/Alan_Turing")

    assert requested[0].startswith("https://en.wikipedia.org/w/api.php?")
    assert "titles=Alan%20Turing" in requested[0] and "explaintext=1" in requested[0]
    assert loaded.title == "Alan Turing (Wikipedia)"
    assert loaded.url == "https://en.wikipedia.org/wiki/Alan_Turing"
    [document] = loaded.documents
    assert document.path == "wikipedia/en/Alan_Turing"
    assert document.text == "English mathematician.\n\n\n## Work\nCodebreaking."


def test_missing_wikipedia_article_is_reported(monkeypatch):
    body = b'{"query":{"pages":[{"title":"Nope","missing":true}]}}'
    monkeypatch.setattr(sources, "fetch", lambda url, **k: Fetched(url, body, "application/json"))
    with pytest.raises(SourceError, match="no article called"):
        load_wikipedia("https://en.wikipedia.org/wiki/Nope")


# --- web pages -------------------------------------------------------------------


def test_html_is_reduced_to_its_article_text():
    document = html_to_document(PAGE, "web/example.com/signing", "https://example.com/signing", "example.com")

    assert document is not None
    # The article's own heading, not the browser-tab title with the site name appended.
    assert document.title == "Signing data"
    assert "A signature proves that a value was produced" in document.text
    assert "compared in constant time" in document.text
    # Navigation and footer are not part of the article.
    assert "Pricing" not in document.text
    assert "Copyright Example Corp" not in document.text


def test_web_page_load(monkeypatch):
    monkeypatch.setattr(
        sources, "fetch", lambda url, **k: Fetched("https://example.com/docs/signing", PAGE, "text/html")
    )

    loaded = load_web("http://example.com/docs/signing")

    assert loaded.url == "https://example.com/docs/signing"  # after the redirect
    assert loaded.title == "Signing data"
    assert [d.path for d in loaded.documents] == ["web/example.com/docs/signing"]


def test_non_pages_and_fetch_failures_are_reported(monkeypatch):
    monkeypatch.setattr(sources, "fetch", lambda url, **k: Fetched(url, b"%PDF-1.7", "application/pdf"))
    with pytest.raises(SourceError, match="Upload the file instead"):
        load_web("https://example.com/paper.pdf")

    def refuse(url, **kwargs):
        raise FetchError("That link points at a private or internal address.")

    monkeypatch.setattr(sources, "fetch", refuse)
    with pytest.raises(SourceError, match="private or internal"):
        load_web("http://localhost/")


# --- crawl -----------------------------------------------------------------------


def test_page_links_stay_on_the_host_and_skip_assets():
    assert page_links(PAGE.decode(), "https://example.com/docs/signing") == [
        "https://example.com/",
        "https://example.com/pricing",
        "https://example.com/guide/keys.html",
        "https://example.com/docs/signing",  # "#top", with the fragment removed
    ]


def site(pages, robots=""):
    def fake_fetch(url, **kwargs):
        if url.endswith("/robots.txt"):
            if robots is None:
                raise FetchError("404")
            return Fetched(url, robots.encode(), "text/plain")
        if url not in pages:
            raise FetchError(f"The site answered 404 for {url}.")
        return Fetched(url, pages[url], "text/html")

    return fake_fetch


def page(title, *links):
    anchors = "".join(f'<a href="{href}">link</a>' for href in links)
    text = f"{title} explains one part of the system in enough words to count as an article. " * 4
    return f"<html><head><title>{title}</title></head><body><article><h1>{title}</h1><p>{text}</p>{anchors}</article></body></html>".encode()


def test_crawl_follows_links_breadth_first_up_to_the_limit(monkeypatch):
    pages = {
        "https://example.com/": page("Home", "/a", "/b", "https://elsewhere.example/x"),
        "https://example.com/a": page("Page A", "/c", "/"),
        "https://example.com/b": page("Page B"),
        "https://example.com/c": page("Page C"),
    }
    monkeypatch.setattr(sources, "fetch", site(pages))
    monkeypatch.setattr(sources, "robots_for", lambda url: _allow_all())
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    messages = []

    loaded = load_crawl("https://example.com/", 3, messages.append)

    assert [d.title for d in loaded.documents] == ["Home", "Page A", "Page B"]
    assert [d.path for d in loaded.documents] == ["web/example.com/index", "web/example.com/a", "web/example.com/b"]
    assert loaded.title == "example.com (3 pages)"
    assert messages[0] == "fetched 1/3: https://example.com/"


def _allow_all():
    import urllib.robotparser

    parser = urllib.robotparser.RobotFileParser()
    parser.parse([])
    return parser


def test_crawl_obeys_robots_txt(monkeypatch):
    import urllib.robotparser

    pages = {
        "https://example.com/": page("Home", "/private/secret", "/public"),
        "https://example.com/private/secret": page("Secret"),
        "https://example.com/public": page("Public"),
    }
    rules = urllib.robotparser.RobotFileParser()
    rules.parse(["User-agent: *", "Disallow: /private/"])
    monkeypatch.setattr(sources, "fetch", site(pages))
    monkeypatch.setattr(sources, "robots_for", lambda url: rules)
    monkeypatch.setattr(sources.time, "sleep", lambda seconds: None)
    messages = []

    loaded = load_crawl("https://example.com/", 10, messages.append)

    assert [d.title for d in loaded.documents] == ["Home", "Public"]
    assert messages[-1] == "skipped 1 pages (blocked by robots.txt or unreachable)"


def test_crawl_of_a_fully_disallowed_site_says_so(monkeypatch):
    import urllib.robotparser

    rules = urllib.robotparser.RobotFileParser()
    rules.parse(["User-agent: *", "Disallow: /"])
    monkeypatch.setattr(sources, "fetch", site({"https://example.com/": page("Home")}))
    monkeypatch.setattr(sources, "robots_for", lambda url: rules)

    with pytest.raises(SourceError, match="robots.txt"):
        load_crawl("https://example.com/", 5, lambda message: None)


# --- uploads ---------------------------------------------------------------------


def test_text_and_markdown_uploads(tmp_path):
    note = tmp_path / "blob"
    note.write_text("# Notes\n\nSignatures are compared in constant time.\n", encoding="utf-8")

    loaded = load_upload(note, "My Notes.md")

    assert loaded.title == "My Notes"
    assert loaded.url is None
    [document] = loaded.documents
    assert document.path == "uploads/My_Notes.md"
    assert "constant time" in document.text


def test_epub_upload_reads_chapters_in_spine_order(tmp_path):
    book = tmp_path / "book.epub"
    chapter = "<html><body><h1>{0}</h1><p>{0} is about the thing in enough words to be kept as text.</p></body></html>"
    with zipfile.ZipFile(book, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
            '<rootfile full-path="OEBPS/content.opf"/></rootfiles></container>',
        )
        z.writestr(
            "OEBPS/content.opf",
            '<package xmlns="http://www.idpf.org/2007/opf"><manifest>'
            '<item id="two" href="text/second.xhtml"/><item id="one" href="text/first.xhtml"/>'
            '</manifest><spine><itemref idref="one"/><itemref idref="two"/></spine></package>',
        )
        z.writestr("OEBPS/text/first.xhtml", chapter.format("Chapter One"))
        z.writestr("OEBPS/text/second.xhtml", chapter.format("Chapter Two"))

    loaded = load_upload(book, "book.epub")

    text = loaded.documents[0].text
    assert "Chapter One is about the thing" in text and "Chapter Two is about the thing" in text
    assert text.index("Chapter One") < text.index("Chapter Two")  # spine order, not manifest order


def test_unsupported_broken_and_binary_uploads_are_rejected(tmp_path):
    blob = tmp_path / "blob"
    blob.write_bytes(b"MZ\x00\x01\x02")

    with pytest.raises(SourceError, match="not supported"):
        load_upload(blob, "setup.exe")
    with pytest.raises(SourceError, match="does not contain readable text"):
        load_upload(blob, "notes.txt")
    with pytest.raises(SourceError, match="could not be read as an EPUB"):
        load_upload(blob, "book.epub")
    with pytest.raises(SourceError, match="could not be read as a PDF"):
        load_upload(blob, "paper.pdf")


def test_upload_names_cannot_escape_the_uploads_folder(tmp_path):
    note = tmp_path / "blob"
    note.write_text("Some text that is long enough to keep.", encoding="utf-8")
    loaded = load_upload(note, "..\\..\\secret/../../etc/passwd.txt")
    assert loaded.documents[0].path == "uploads/passwd.txt"
