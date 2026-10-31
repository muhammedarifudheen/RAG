"""Defence in depth: clear prompt-injection attempts are refused on the way in; secrets,
tokens, keys and email addresses are redacted on the way out (as the answer streams);
links outside the knowledge base are removed from grounded answers; and identities in logs
are hashed."""

from __future__ import annotations

import hashlib
import ipaddress
import re
from collections.abc import Iterable
from urllib.parse import urlparse

from app.config import settings

REFUSED = "This request can't be processed."

# Unambiguous attacks only; code blocks and attachments are left out before matching, as
# "system:" or base64 there is data, not an attempt.
_ATTACKS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        (
            r"\b(ignore|disregard|forget|override)\s+(all\s+|any\s+|the\s+|your\s+)?"
            r"(previous|prior|above|earlier|preceding|system)\s+"
            r"(instructions|prompts?|rules|messages)"
        ),
        (
            r"\b(reveal|print|show|repeat|output|dump|leak)\s+(me\s+)?(your|the)\s+"
            r"(full\s+|entire\s+|hidden\s+|initial\s+)?"
            r"(system\s+prompt|instructions|hidden\s+prompt)"
        ),
        (
            r"\byou\s+are\s+now\s+(a|an|in|the)?\s*"
            r"(unrestricted|jailbroken|dan\b|developer\s+mode|evil|uncensored)"
        ),
        r"\b(enter|enable|activate)\s+(dan|developer|god|jailbreak)\s+mode\b",
        r"\bpretend\s+(that\s+)?you\s+(have\s+no|are\s+not\s+bound\s+by)\s+(rules|restrictions)",
        r"^\s*(###\s*)?(system|assistant)\s*:\s*you\s+(are|must|will)\b",
    )
]
_FENCE = re.compile(r"```.*?```", re.DOTALL)


def injection(text: str) -> str | None:
    """The attack pattern a question carries, or None. Fenced code is not matched."""
    prose = _FENCE.sub(" ", text or "")
    for pattern in _ATTACKS:
        found = pattern.search(prose)
        if found:
            return found.group(0)[:120]
    return None


# Secrets, by shape: provider API keys, JWTs, private keys, email addresses.
_SECRETS = [
    (
        "private key",
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL
        ),
    ),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    (
        "API key",
        re.compile(
            r"\b(sk-(?:ant-|or-v1-|proj-)?[A-Za-z0-9_-]{20,}|gsk_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
            r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|xox[abprs]-[A-Za-z0-9-]{10,}|"
            r"AIza[0-9A-Za-z_-]{35}|nvapi-[A-Za-z0-9_-]{20,}|hf_[A-Za-z0-9]{30,}|rnd_[A-Za-z0-9]{20,}|"
            r"atl_[A-Za-z0-9]{24,})"
        ),
    ),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]
_URL = re.compile(r"https?://[^\s)\]>\"'`]+")
# How far back a secret may start before the end of what has streamed so far.
_HOLD = 600


def redact(text: str, allowed_hosts: set[str] | None = None) -> tuple[str, list[str]]:
    """The text with secrets replaced, and, when `allowed_hosts` is given, links to other
    hosts removed; with what was redacted (kinds only, never the values)."""
    found: list[str] = []
    for kind, pattern in _SECRETS:
        text, n = pattern.subn(f"[redacted {kind}]", text)
        found += [kind] * n
    if allowed_hosts is not None:

        def keep(match: re.Match) -> str:
            host = (urlparse(match.group(0)).hostname or "").lower()
            if any(host == h or host.endswith("." + h) for h in allowed_hosts):
                return match.group(0)
            found.append("link")
            return "[link removed]"

        text = _URL.sub(keep, text)
    return text, found


class Redactor:
    """Redacts a streamed answer piece by piece: holds back what could still be the start
    of a secret (an unfinished private key, or the last unfinished word)."""

    def __init__(self, allowed_hosts: set[str] | None = None) -> None:
        self.allowed = allowed_hosts
        self.buffer = ""
        self.found: list[str] = []

    def feed(self, piece: str) -> str:
        self.buffer += piece
        cut = self._safe_end()
        if cut <= 0:
            return ""
        out, found = redact(self.buffer[:cut], self.allowed)
        self.found += found
        self.buffer = self.buffer[cut:]
        return out

    def flush(self) -> str:
        out, found = redact(self.buffer, self.allowed)
        self.found += found
        self.buffer = ""
        return out

    def _safe_end(self) -> int:
        text = self.buffer
        begin = text.rfind("-----BEGIN")
        if begin != -1 and "-----END" not in text[begin:]:
            return begin
        # Up to the last whitespace: a token still streaming is not judged yet.
        space = max(text.rfind(" "), text.rfind("\n"), text.rfind("\t"))
        if space == -1:
            return 0 if len(text) < _HOLD else len(text) - _HOLD
        return space + 1


def allowed_hosts(urls: Iterable[str | None]) -> set[str]:
    """The hosts of the knowledge base's sources, and the site's own."""
    hosts = {(urlparse(u).hostname or "").lower() for u in urls if u}
    hosts |= {"github.com", "raw.githubusercontent.com"} & {h for h in hosts}
    return {h for h in hosts if h}


def digest(value: str | None) -> str | None:
    """A salted SHA-256 of an identity or a text, for logs that must not hold it."""
    if not value:
        return None
    salt = (settings.admin_token or "atlas").encode()
    return hashlib.sha256(salt + value.encode()).hexdigest()[:16]


def private_client(host: str | None) -> str:
    """A client address for the logs: hashed if it is an IP address."""
    if not host:
        return "unknown"
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return host
    return f"ip-{digest(host)}"
