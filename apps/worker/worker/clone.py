from __future__ import annotations

import io
import os
import re
import shutil
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

_GITHUB_URL = re.compile(
    r"^https://github\.com/(?P<owner>[A-Za-z0-9][A-Za-z0-9-]*)/(?P<repo>[A-Za-z0-9._-]+?)(?:\.git)?/?$"
)


@dataclass(frozen=True)
class ClonedRepo:
    path: Path
    commit: str


def parse_github_url(url: str) -> tuple[str, str]:
    """Returns (owner, repo), or raises ValueError for anything but an HTTPS GitHub repo URL."""
    match = _GITHUB_URL.match(url.strip())
    if match is None or match["repo"] in (".", ".."):
        raise ValueError(f"Not a GitHub repository URL: {url!r} (expected https://github.com/owner/repo)")
    return match["owner"], match["repo"]


def clone_repo(url: str, dest_root: Path | None = None, token: str | None = None) -> ClonedRepo:
    """Shallow-clones a GitHub repository into a fresh directory under `dest_root`."""
    from dulwich import porcelain

    owner, repo = parse_github_url(url)
    root = Path(dest_root) if dest_root else Path(tempfile.gettempdir())
    root.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix=f"atlas-{owner}-{repo}-", dir=root))

    credentials = {"username": "x-access-token", "password": token} if token else {}
    try:
        with porcelain.clone(
            f"https://github.com/{owner}/{repo}.git",
            str(target),
            depth=1,
            errstream=io.BytesIO(),
            **credentials,
        ) as cloned:
            commit = cloned.head().decode("ascii")
    except BaseException:
        remove_clone(target)
        raise
    return ClonedRepo(path=target, commit=commit)


def remove_clone(path: Path) -> None:
    def make_writable(function, target, _exc):
        # Git marks pack files read-only, which blocks deletion on Windows.
        os.chmod(target, stat.S_IWRITE)
        function(target)

    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=make_writable)
    else:
        shutil.rmtree(path, onerror=make_writable)
