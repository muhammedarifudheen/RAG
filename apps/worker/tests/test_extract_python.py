from support import bases, calls, imports, signatures, symbol_table

from worker.extract import extract_source
from worker.extract.types import SELF, SUPER


def test_symbols_and_line_ranges(files):
    assert symbol_table(files["pyapp/models.py"]) == {
        ("pyapp/models.py", "module", 1, 21),
        ("Base", "class", 4, 9),
        ("Base.describe", "method", 5, 6),
        ("Base.label", "method", 8, 9),
        ("User", "class", 12, 17),
        ("User.__init__", "method", 13, 14),
        ("User.label", "method", 16, 17),
        ("format_name", "function", 20, 21),
    }
    assert symbol_table(files["pyapp/service.py"]) == {
        ("pyapp/service.py", "module", 1, 19),
        ("create_user", "function", 7, 10),
        ("default_user", "function", 13, 14),
        ("Admin", "class", 17, 19),
        ("Admin.label", "method", 18, 19),
    }


def test_empty_file_has_only_a_module_symbol(files):
    assert symbol_table(files["pyapp/__init__.py"]) == {("pyapp/__init__.py", "module", 1, 1)}


def test_signatures(files):
    assert signatures(files["pyapp/models.py"]) == {
        "Base": "class Base",
        "Base.describe": "def describe(self) -> str",
        "Base.label": "def label(self) -> str",
        "User": "class User(Base)",
        "User.__init__": "def __init__(self, name: str) -> None",
        "User.label": "def label(self) -> str",
        "format_name": "def format_name(name: str) -> str",
    }


def test_methods_know_their_class_and_classes_their_bases(files):
    models = files["pyapp/models.py"]
    owners = {s.name: s.owner for s in models.symbols if s.kind == "method"}
    assert owners == {
        "Base.describe": "Base",
        "Base.label": "Base",
        "User.__init__": "User",
        "User.label": "User",
    }
    assert bases(models) == {"User": ["Base"]}
    assert bases(files["pyapp/service.py"]) == {"Admin": ["models.User"]}


def test_imports(files):
    assert imports(files["pyapp/service.py"]) == [
        ("os", 0, "os", []),
        ("", 1, None, [("models", "models")]),
        ("models", 1, None, [("User", "User"), ("format_name", "fmt")]),
    ]
    assert files["pyapp/models.py"].imports == []


def test_call_sites(files):
    assert calls(files["pyapp/models.py"]) == {
        ("Base.describe", SELF, "label"),
        ("User.label", None, "format_name"),
        ("format_name", "name", "strip"),
        ("format_name", "name.strip()", "title"),
    }
    assert calls(files["pyapp/service.py"]) == {
        ("create_user", None, "User"),
        ("create_user", None, "fmt"),
        ("create_user", "user", "describe"),
        ("default_user", None, "create_user"),
        ("default_user", "os.environ", "get"),
        ("Admin.label", SUPER, "label"),
        ("Admin.label", "super().label()", "upper"),
    }


def test_decorators_nesting_and_async():
    source = b"""\
import functools as ft
from pkg.sub import *


@ft.cache
def outer(x):
    def inner(y):
        return y

    return inner(x)


class Box(Generic[T], metaclass=Meta):
    @property
    def value(self):
        return 1

    async def load(self):
        await fetch()


setup()
"""
    f = extract_source("mod.py", source)

    assert symbol_table(f) == {
        ("mod.py", "module", 1, 22),
        ("outer", "function", 5, 10),  # starts at its decorator
        ("outer.inner", "function", 7, 8),
        ("Box", "class", 13, 19),
        ("Box.value", "method", 14, 16),
        ("Box.load", "method", 18, 19),
    }
    assert signatures(f)["Box.load"] == "async def load(self)"
    assert bases(f) == {"Box": ["Generic"]}
    assert imports(f) == [("functools", 0, "ft", []), ("pkg.sub", 0, None, [])]
    assert f.imports[1].wildcard
    assert calls(f) == {
        ("outer", None, "inner"),
        ("Box.load", None, "fetch"),
        ("mod.py", None, "setup"),  # module-level calls belong to the module symbol
    }
