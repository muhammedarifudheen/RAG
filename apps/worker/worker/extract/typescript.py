from __future__ import annotations

from tree_sitter import Node

from worker.extract.base import Extractor, line, text
from worker.extract.types import CLASS, FUNCTION, METHOD, SELF, SUPER, Import

_FUNCTION_VALUES = ("arrow_function", "function_expression", "generator_function")


def _type_name(node: Node) -> str:
    """`Base<T>` -> `Base`."""
    if node.type == "generic_type":
        name = node.child_by_field_name("name")
        if name is not None:
            return text(name)
    return text(node)


def _string(node: Node) -> str:
    return text(node).strip("'\"`")


class TypeScriptExtractor(Extractor):
    language = "typescript"

    # --- functions ---------------------------------------------------------

    def visit_function_declaration(self, node: Node) -> None:
        symbol = self.define(
            node,
            self.qualify(text(node.child_by_field_name("name"))),
            FUNCTION,
            body=node.child_by_field_name("body"),
        )
        with self.inside(symbol):
            self.visit_children(node)

    visit_generator_function_declaration = visit_function_declaration

    def visit_variable_declarator(self, node: Node) -> None:
        """`const f = () => ...` and `const f = function () {}` define a function named f."""
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if (
            name is None
            or value is None
            or name.type != "identifier"
            or value.type not in _FUNCTION_VALUES
        ):
            self.visit_children(node)
            return

        declaration = node.parent
        whole = declaration is not None and declaration.named_child_count == 1
        span = declaration if whole else node
        symbol = self.define(
            span,
            self.qualify(text(name)),
            FUNCTION,
            body=value.child_by_field_name("body"),
        )
        with self.inside(symbol):
            self.visit_children(value)

    # --- classes and interfaces --------------------------------------------

    def visit_class_declaration(self, node: Node) -> None:
        bases = []
        for heritage in node.named_children:
            if heritage.type != "class_heritage":
                continue
            for clause in heritage.named_children:
                if clause.type == "extends_clause":
                    value = clause.child_by_field_name("value")
                    if value is not None:
                        bases.append(text(value))
                elif clause.type == "implements_clause":
                    bases.extend(_type_name(t) for t in clause.named_children)
        self._class(node, bases)

    visit_abstract_class_declaration = visit_class_declaration

    def visit_interface_declaration(self, node: Node) -> None:
        bases = []
        for clause in node.named_children:
            if clause.type == "extends_type_clause":
                bases.extend(_type_name(t) for t in clause.named_children)
        self._class(node, bases)

    def _class(self, node: Node, bases: list[str]) -> None:
        symbol = self.define(
            node,
            self.qualify(text(node.child_by_field_name("name"))),
            CLASS,
            body=node.child_by_field_name("body"),
            bases=bases,
        )
        with self.inside(symbol):
            self.visit_children(node)

    def visit_method_definition(self, node: Node) -> None:
        name = node.child_by_field_name("name")
        if name is None or self.scope.kind != CLASS:  # e.g. a method in an object literal
            self.visit_children(node)
            return
        symbol = self.define(
            node,
            self.qualify(text(name)),
            METHOD,
            body=node.child_by_field_name("body"),
            owner=self.scope.name,
        )
        with self.inside(symbol):
            self.visit_children(node)

    visit_method_signature = visit_method_definition
    visit_abstract_method_signature = visit_method_definition

    def visit_public_field_definition(self, node: Node) -> None:
        """`handler = () => ...` as a class property is a method."""
        name = node.child_by_field_name("name")
        value = node.child_by_field_name("value")
        if (
            name is None
            or value is None
            or value.type not in _FUNCTION_VALUES
            or self.scope.kind != CLASS
        ):
            self.visit_children(node)
            return
        symbol = self.define(
            node,
            self.qualify(text(name)),
            METHOD,
            body=value.child_by_field_name("body"),
            owner=self.scope.name,
        )
        with self.inside(symbol):
            self.visit_children(value)

    # --- imports and exports -----------------------------------------------

    def visit_import_statement(self, node: Node) -> None:
        source = node.child_by_field_name("source")
        if source is None:  # `import x = require(...)`
            return
        imported = Import(module=_string(source), line=line(node))
        for clause in node.named_children:
            if clause.type != "import_clause":
                continue
            for child in clause.named_children:
                if child.type == "identifier":
                    imported.names.append(("default", text(child)))
                elif child.type == "namespace_import":
                    imported.alias = text(child.named_children[-1])
                elif child.type == "named_imports":
                    for spec in child.named_children:
                        if spec.type != "import_specifier":
                            continue
                        name = text(spec.child_by_field_name("name"))
                        alias = spec.child_by_field_name("alias")
                        imported.names.append((name, text(alias) if alias else name))
        self.out.imports.append(imported)

    def visit_export_statement(self, node: Node) -> None:
        source = node.child_by_field_name("source")
        if source is not None:  # `export { a } from "./b"` re-exports are imports too
            self.out.imports.append(Import(module=_string(source), line=line(node)))
            return

        if any(child.type == "default" for child in node.children):
            target = node.child_by_field_name("declaration") or node.child_by_field_name("value")
            if target is not None and target.type == "identifier":
                self.out.default_export = text(target)
            elif target is not None:
                name = target.child_by_field_name("name")
                if name is not None:
                    self.out.default_export = text(name)
        self.visit_children(node)

    # --- calls -------------------------------------------------------------

    def visit_call_expression(self, node: Node) -> None:
        self._call(node, node.child_by_field_name("function"))
        self.visit_children(node)

    def visit_new_expression(self, node: Node) -> None:
        self._call(node, node.child_by_field_name("constructor"))
        self.visit_children(node)

    def _call(self, node: Node, function: Node | None) -> None:
        if function is None:
            return
        if function.type == "identifier":
            self.call(node, text(function), None)
        elif function.type == "member_expression":
            target = function.child_by_field_name("object")
            name = function.child_by_field_name("property")
            if target is None or name is None:
                return
            if target.type == "this":
                receiver = SELF
            elif target.type == "super":
                receiver = SUPER
            else:
                receiver = text(target)
            self.call(node, text(name), receiver)
