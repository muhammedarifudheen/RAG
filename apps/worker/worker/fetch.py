"""HTTP fetching for URLs typed in by users.

The server downloads whatever address it is given, so this module refuses
anything that is not a public web address: internal hosts, private networks and
cloud metadata endpoints would otherwise be reachable through the server.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.request
import urllib.robotparser
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

USER_AGENT = "AtlasBot/0.1 (knowledge-base ingestion; contact the site operator of this deployment)"
MAX_BYTES = 5_000_000
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 20
_ALLOWED_PORTS = {None, 80, 443}


class FetchError(Exception):
    """The URL could not or must not be fetched; the message is safe to show."""


@dataclass
class Fetched:
    url: str  # after redirects
    body: bytes
    content_type: str


def check_public_url(url: str) -> str:
    """Returns the URL if it points at a public web address; raises FetchError otherwise."""
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        raise FetchError("Only http and https links can be fetched.")
    if not parts.hostname:
        raise FetchError("That link has no host name.")
    if parts.username or parts.password:
        raise FetchError("Links containing a user name or password are not fetched.")
    try:
        port = parts.port
    except ValueError as error:
        raise FetchError("That link has an invalid port.") from error
    if port not in _ALLOWED_PORTS:
        raise FetchError("Only the standard web ports (80 and 443) are fetched.")

    try:
        infos = socket.getaddrinfo(parts.hostname, port or 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise FetchError(f"Could not find the host {parts.hostname!r}.") from error
    for info in infos:
        address = ipaddress.ip_address(info[4][0].split("%")[0])
        # Every address must be public: a name can resolve to several.
        if not address.is_global:
            raise FetchError("That link points at a private or internal address.")
    return parts.geturl()


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # surface the 3xx so each hop can be checked


_opener = urllib.request.build_opener(_NoRedirect)


def fetch(url: str, *, max_bytes: int = MAX_BYTES, accept: str = "text/html,*/*;q=0.5") -> Fetched:
    """GETs a public URL, following redirects only to other public URLs."""
    for _ in range(MAX_REDIRECTS + 1):
        url = check_public_url(url)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
        try:
            with _opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                body = response.read(max_bytes + 1)
                if len(body) > max_bytes:
                    raise FetchError(f"That page is larger than {max_bytes // 1_000_000} MB.")
                return Fetched(url, body, response.headers.get_content_type())
        except urllib.error.HTTPError as error:
            location = error.headers.get("Location") if error.headers else None
            if error.code in (301, 302, 303, 307, 308) and location:
                url = urljoin(url, location)
                continue
            raise FetchError(f"The site answered {error.code} for {url}.") from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", error)
            raise FetchError(f"Could not reach {urlsplit(url).hostname}: {reason}") from error
    raise FetchError("Too many redirects.")


def robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    """The site's robots.txt rules. A missing or unreadable file allows everything."""
    parts = urlsplit(url)
    parser = urllib.robotparser.RobotFileParser()
    try:
        fetched = fetch(f"{parts.scheme}://{parts.netloc}/robots.txt", max_bytes=500_000, accept="text/plain")
        parser.parse(fetched.body.decode("utf-8", errors="replace").splitlines())
    except FetchError:
        parser.parse([])
    return parser
