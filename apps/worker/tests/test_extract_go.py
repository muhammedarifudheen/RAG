from support import bases, calls, imports, signatures, symbol_table

from worker.extract import extract_source
from worker.extract.types import SELF


def test_symbols_and_line_ranges(files):
    assert symbol_table(files["geometry/shapes.go"]) == {
        ("geometry/shapes.go", "module", 1, 36),
        ("Shape", "class", 5, 7),
        ("Shape.Area", "method", 6, 6),
        ("Point", "class", 9, 11),
        ("Circle", "class", 13, 16),
        ("Circle.Area", "method", 18, 20),
        ("Circle.Scaled", "method", 22, 24),
        ("square", "function", 26, 28),
        ("Total", "function", 30, 36),
    }
    assert symbol_table(files["main.go"]) == {
        ("main.go", "module", 1, 16),
        ("NewUnit", "function", 9, 11),
        ("main", "function", 13, 16),
    }


def test_signatures(files):
    assert signatures(files["geometry/shapes.go"]) == {
        "Shape": "type Shape interface",
        "Shape.Area": "Area() float64",
        "Point": "type Point struct",
        "Circle": "type Circle struct",
        "Circle.Area": "func (c *Circle) Area() float64",
        "Circle.Scaled": "func (c *Circle) Scaled() float64",
        "square": "func square(x float64) float64",
        "Total": "func Total(shapes ...Shape) float64",
    }


def test_package_receivers_and_embedding(files):
    shapes = files["geometry/shapes.go"]
    assert shapes.package == "geometry"
    assert files["main.go"].package == "main"
    owners = {s.name: s.owner for s in shapes.symbols if s.kind == "method"}
    assert owners == {
        "Shape.Area": "Shape",
        "Circle.Area": "Circle",
        "Circle.Scaled": "Circle",
    }
    assert bases(shapes) == {"Circle": ["Point"]}  # embedded struct


def test_imports(files):
    assert imports(files["geometry/shapes.go"]) == [("math", 0, None, [])]
    assert imports(files["main.go"]) == [
        ("fmt", 0, None, []),
        ("example.com/sample/geometry", 0, "geo", []),
    ]


def test_call_sites(files):
    assert calls(files["geometry/shapes.go"]) == {
        ("Circle.Area", None, "square"),
        ("Circle.Scaled", SELF, "Area"),  # call on the method's own receiver
        ("Total", "s", "Area"),
        ("Total", None, "square"),
    }
    assert calls(files["main.go"]) == {
        ("main", None, "NewUnit"),
        ("main", "fmt", "Println"),
        ("main", "geo", "Total"),
    }


def test_grouped_types_embedded_interfaces_and_value_receivers():
    source = b"""\
package io

type (
	Reader interface {
		Read() int
	}
	ReadCloser interface {
		Reader
		pkg.Closer
		Close()
	}
	Count int
)

type File struct {
	*Base
	name string
}

func (f File) Read() int { return f.size() }

func (Count) Zero() Count { return Count(0) }
"""
    f = extract_source("io/io.go", source)

    assert symbol_table(f) == {
        ("io/io.go", "module", 1, 22),
        ("Reader", "class", 4, 6),
        ("Reader.Read", "method", 5, 5),
        ("ReadCloser", "class", 7, 11),
        ("ReadCloser.Close", "method", 10, 10),
        ("Count", "class", 12, 12),
        ("File", "class", 15, 18),
        ("File.Read", "method", 20, 20),
        ("Count.Zero", "method", 22, 22),
    }
    assert signatures(f)["Count"] == "type Count int"
    assert bases(f) == {"ReadCloser": ["Reader", "pkg.Closer"], "File": ["Base"]}
    assert calls(f) == {
        ("File.Read", SELF, "size"),
        ("Count.Zero", None, "Count"),
    }
