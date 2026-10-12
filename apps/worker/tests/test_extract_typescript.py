from support import bases, calls, imports, signatures, symbol_table

from worker.extract import extract_source
from worker.extract.types import SELF, SUPER


def test_symbols_and_line_ranges(files):
    assert symbol_table(files["web/shapes.ts"]) == {
        ("web/shapes.ts", "module", 1, 23),
        ("Shape", "class", 1, 3),
        ("Shape.area", "method", 2, 2),
        ("Circle", "class", 5, 11),
        ("Circle.constructor", "method", 6, 6),
        ("Circle.area", "method", 8, 10),
        ("Disc", "class", 13, 17),
        ("Disc.describe", "method", 14, 16),
        ("square", "function", 19, 21),
        ("double", "function", 23, 23),
    }
    assert symbol_table(files["web/main.ts"]) == {
        ("web/main.ts", "module", 1, 9),
        ("run", "function", 4, 7),
    }


def test_signatures(files):
    assert signatures(files["web/shapes.ts"]) == {
        "Shape": "interface Shape",
        "Shape.area": "area(): number",
        "Circle": "class Circle implements Shape",
        "Circle.constructor": "constructor(private radius: number)",
        "Circle.area": "area(): number",
        "Disc": "class Disc extends Circle",
        "Disc.describe": "describe(): string",
        "square": "function square(x: number): number",
        "double": "const double = (x: number): number =>",
    }


def test_extends_and_implements_are_bases(files):
    assert bases(files["web/shapes.ts"]) == {"Circle": ["Shape"], "Disc": ["Circle"]}


def test_imports(files):
    assert imports(files["web/main.ts"]) == [
        ("./shapes", 0, None, [("Circle", "Circle"), ("double", "twice")]),
        ("./shapes", 0, "shapes", []),
    ]


def test_call_sites(files):
    assert calls(files["web/shapes.ts"]) == {
        ("Circle.area", None, "square"),
        ("Disc.describe", SELF, "area"),
    }
    assert calls(files["web/main.ts"]) == {
        ("run", None, "Circle"),  # `new Circle(...)`
        ("run", None, "twice"),
        ("run", "shapes", "square"),
        ("run", "c", "area"),
        ("web/main.ts", None, "run"),
    }


def test_default_exports_abstract_classes_and_tsx():
    source = b"""\
import React, { useState } from "react";
export { helper } from "./helper";

export default abstract class Widget<T> extends Base<T> implements A, B<T> {
  abstract render(): void;

  onClick = () => {
    super.onClick();
  };
}

export function View() {
  return <div>{format(1)}</div>;
}
"""
    f = extract_source("widget.tsx", source)

    assert f.language == "typescript"
    assert f.default_export == "Widget"
    assert symbol_table(f) == {
        ("widget.tsx", "module", 1, 14),
        ("Widget", "class", 4, 10),
        ("Widget.render", "method", 5, 5),
        ("Widget.onClick", "method", 7, 9),
        ("View", "function", 12, 14),
    }
    assert bases(f) == {"Widget": ["Base", "A", "B"]}
    assert imports(f) == [
        ("react", 0, None, [("default", "React"), ("useState", "useState")]),
        ("./helper", 0, None, []),
    ]
    assert calls(f) == {
        ("Widget.onClick", SUPER, "onClick"),
        ("View", None, "format"),
    }
