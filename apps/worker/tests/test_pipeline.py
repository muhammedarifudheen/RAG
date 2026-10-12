import hashlib

import pytest
from support import FIXTURE_REPO

from worker.clone import parse_github_url
from worker.embed import MAX_CHARS, symbol_text
from worker.pipeline import discover, embed_symbols, parse_repo


def test_fixture_repo_files(repo, files):
    assert sorted(files) == [
        "geometry/shapes.go",
        "main.go",
        "pyapp/__init__.py",
        "pyapp/models.py",
        "pyapp/service.py",
        "web/main.ts",
        "web/shapes.ts",
    ]
    assert {f.language for f in repo.files} == {"python", "typescript", "go"}
    assert repo.skipped == []


def test_hash_and_loc(files):
    models = files["pyapp/models.py"]
    source = (FIXTURE_REPO / "pyapp" / "models.py").read_bytes()
    assert models.hash == hashlib.sha256(source).hexdigest()
    assert models.loc == 21
    assert files["pyapp/__init__.py"].loc == 0


def test_file_content_is_kept_for_snippets(files):
    source = (FIXTURE_REPO / "pyapp" / "models.py").read_bytes()
    assert files["pyapp/models.py"].content == source.decode()
    assert files["pyapp/__init__.py"].content == ""


def test_binary_files_are_skipped(tmp_path):
    (tmp_path / "blob.py").write_bytes(b"x = 1\n\x00\x01\x02")
    repo = parse_repo(tmp_path)
    assert repo.files == []
    assert repo.skipped == [("blob.py", "binary")]


def test_discover_skips_dependencies_hidden_dirs_and_other_languages(tmp_path):
    for name in ("a.py", "node_modules/dep.ts", ".git/hook.py", "vendor/x.go", "README.md"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    sources, go_mods = discover(tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in sources] == ["a.py"]
    assert go_mods == []


def test_oversized_files_are_skipped(tmp_path):
    (tmp_path / "big.py").write_text("x = 1\n" * 100)
    repo = parse_repo(tmp_path, max_file_bytes=10)
    assert repo.files == []
    assert repo.skipped == [("big.py", "too large")]


def test_embed_symbols_assigns_one_vector_per_symbol(files):
    class FakeEmbedder:
        def encode(self, texts, on_progress=None):
            return [[float(len(text))] for text in texts]

    messages = []
    extraction = files["pyapp/service.py"]
    embed_symbols([extraction], FakeEmbedder(), messages.append)
    assert all(s.embedding == [float(len(symbol_text(s)))] for s in extraction.symbols)


def test_symbol_text_names_the_symbol_and_truncates_its_source(files):
    create_user = next(s for s in files["pyapp/service.py"].symbols if s.name == "create_user")
    assert symbol_text(create_user).startswith(
        "function create_user in pyapp/service.py\ndef create_user(raw: str) -> User:"
    )
    create_user_long = type(create_user)(**{**vars(create_user), "text": "x" * 5000})
    assert len(symbol_text(create_user_long).split("\n", 1)[1]) == MAX_CHARS


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/pallets/flask",
        "https://github.com/pallets/flask.git",
        "https://github.com/pallets/flask/",
    ],
)
def test_github_urls_are_accepted(url):
    assert parse_github_url(url) == ("pallets", "flask")


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:pallets/flask.git",
        "http://github.com/pallets/flask",
        "https://gitlab.com/pallets/flask",
        "https://github.com/pallets",
        "https://github.com/pallets/flask/tree/main",
        "file:///etc/passwd",
        "https://github.com/pallets/..",
    ],
)
def test_other_urls_are_rejected(url):
    with pytest.raises(ValueError):
        parse_github_url(url)
