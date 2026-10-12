import pytest
from support import edge_set

from worker.extract import extract_source
from worker.resolve import CALLS, IMPORTS, INHERITS, Edge, resolve


@pytest.fixture(scope="module")
def edges(repo) -> list[Edge]:
    return resolve(repo.files, repo.go_modules)


def test_go_module_is_read_from_go_mod(repo):
    assert repo.go_modules == {"": "example.com/sample"}


def test_import_edges(edges):
    assert edge_set(edges, IMPORTS) == {
        # `from . import models` targets the module, `from .models import X` the symbol.
        ("pyapp/service.py", "pyapp/models.py"),
        ("pyapp/service.py", "pyapp/models.py:User"),
        ("pyapp/service.py", "pyapp/models.py:format_name"),
        ("web/main.ts", "web/shapes.ts:Circle"),
        ("web/main.ts", "web/shapes.ts:double"),
        ("web/main.ts", "web/shapes.ts"),
        ("main.go", "geometry/shapes.go"),
    }


def test_inherits_edges(edges):
    assert edge_set(edges, INHERITS) == {
        ("pyapp/models.py:User", "pyapp/models.py:Base"),
        ("pyapp/service.py:Admin", "pyapp/models.py:User"),  # written as models.User
        ("web/shapes.ts:Circle", "web/shapes.ts:Shape"),
        ("web/shapes.ts:Disc", "web/shapes.ts:Circle"),
        ("geometry/shapes.go:Circle", "geometry/shapes.go:Point"),
    }


def test_call_edges(edges):
    assert edge_set(edges, CALLS) == {
        ("pyapp/models.py:Base.describe", "pyapp/models.py:Base.label"),
        ("pyapp/models.py:User.label", "pyapp/models.py:format_name"),
        ("pyapp/service.py:create_user", "pyapp/models.py:User"),
        ("pyapp/service.py:create_user", "pyapp/models.py:format_name"),  # imported as fmt
        ("pyapp/service.py:default_user", "pyapp/service.py:create_user"),
        ("pyapp/service.py:Admin.label", "pyapp/models.py:User.label"),  # super()
        ("web/shapes.ts:Circle.area", "web/shapes.ts:square"),
        ("web/shapes.ts:Disc.describe", "web/shapes.ts:Circle.area"),  # inherited via this
        ("web/main.ts:run", "web/shapes.ts:Circle"),
        ("web/main.ts:run", "web/shapes.ts:double"),  # imported as twice
        ("web/main.ts:run", "web/shapes.ts:square"),  # shapes.square via namespace import
        ("web/main.ts", "web/main.ts:run"),
        ("geometry/shapes.go:Circle.Area", "geometry/shapes.go:square"),
        ("geometry/shapes.go:Circle.Scaled", "geometry/shapes.go:Circle.Area"),
        ("geometry/shapes.go:Total", "geometry/shapes.go:square"),
        ("main.go:main", "main.go:NewUnit"),
        ("main.go:main", "geometry/shapes.go:Total"),  # geo.Total via import alias
    }


def test_calls_on_values_of_unknown_type_are_dropped(edges):
    # `user.describe()`, `c.area()` and `s.Area()` would need type inference.
    targets = {dst for _, dst in edge_set(edges, CALLS)}
    assert "pyapp/models.py:Base.describe" not in targets
    callers_of_area = {src for src, dst in edge_set(edges, CALLS) if dst.endswith("Circle.area")}
    assert callers_of_area == {"web/shapes.ts:Disc.describe"}


def test_edges_are_unique(edges):
    assert len(edges) == len(set(edges))


def test_python_absolute_imports_resolve_from_a_source_root():
    files = [
        extract_source("src/pkg/__init__.py", b""),
        extract_source("src/pkg/util.py", b"def helper():\n    pass\n"),
        extract_source(
            "src/pkg/app.py",
            b"import json\nimport pkg.util\nfrom pkg import util as u\n\n"
            b"def go():\n    pkg.util.helper()\n    u.helper()\n    json.dumps(1)\n",
        ),
        extract_source("tools/json.py", b"def dumps(x):\n    pass\n"),
    ]
    edges = resolve(files)

    assert edge_set(edges, IMPORTS) == {
        ("src/pkg/app.py", "src/pkg/util.py"),
        # Known limitation: a repo file named like a stdlib module shadows it.
        ("src/pkg/app.py", "tools/json.py"),
    }
    assert ("src/pkg/app.py:go", "src/pkg/util.py:helper") in edge_set(edges, CALLS)


def test_typescript_default_import_and_index_resolution():
    files = [
        extract_source("lib/index.ts", b"export default function make() {}\n"),
        extract_source("app.ts", b'import build from "./lib";\nimport x from "pkg";\nbuild();\n'),
    ]
    edges = resolve(files)

    assert edge_set(edges, IMPORTS) == {("app.ts", "lib/index.ts:make")}
    assert edge_set(edges, CALLS) == {("app.ts", "lib/index.ts:make")}


def test_go_calls_across_files_of_one_package():
    files = [
        extract_source("pkg/a.go", b"package pkg\n\nfunc A() { b() }\n"),
        extract_source("pkg/b.go", b"package pkg\n\nfunc b() {}\n"),
    ]
    assert edge_set(resolve(files), CALLS) == {("pkg/a.go:A", "pkg/b.go:b")}
