from __future__ import annotations

from tree_sitter import Node

from worker.extract.base import Extractor, line, text
from worker.extract.types import CLASS, FUNCTION, METHOD, SELF, SUPER, Import


class PythonExtractor(Extractor):
    language = "python"

    def visit_decorated_definition(self, node: Node) -> None:
        for child in node.named_children:
            if child.type == "decorator":
                self.visit(child)
        definition = node.child_by_field_name("definition")
        if definition is None:
            return
        # The symbol's line range includes its decorators.
        if definition.type == "function_definition":
            self.visit_function_definition(definition, span=node)
        elif definition.type == "class_definition":
            self.visit_class_definition(definition, span=node)

    def visit_function_definition(self, node: Node, span: Node | None = None) -> None:
        name = text(node.child_by_field_name("name"))
        is_method = self.scope.kind == CLASS
        symbol = self.define(
            node,
            self.qualify(name),
            METHOD if is_method else FUNCTION,
            body=node.child_by_field_name("body"),
            owner=self.scope.name if is_method else None,
            span=span,
        )
        with self.inside(symbol):
            self.visit_children(node)

    def visit_class_definition(self, node: Node, span: Node | None = None) -> None:
        name = text(node.child_by_field_name("name"))
        symbol = self.define(
            node,
            self.qualify(name),
            CLASS,
            body=node.child_by_field_name("body"),
            bases=self._bases(node.child_by_field_name("superclasses")),
            span=span,
        )
        with self.inside(symbol):
            self.visit_children(node)

    def _bases(self, arguments: Node | None) -> list[str]:
        bases = []
        for arg in arguments.named_children if arguments is not None else []:
            if arg.type == "subscript":  # Generic[T] -> Generic
                arg = arg.child_by_field_name("value")
            if arg is not None and arg.type in ("identifier", "attribute"):
                bases.append(text(arg))
        return bases

    def visit_import_statement(self, node: Node) -> None:
        for child in node.named_children:
            if child.type == "dotted_name":
                module = text(child)
                self.out.imports.append(Import(module=module, line=line(node), alias=module))
            elif child.type == "aliased_import":
                self.out.imports.append(
                    Import(
                        module=text(child.child_by_field_name("name")),
                        line=line(node),
                        alias=text(child.child_by_field_name("alias")),
                    )
                )

    def visit_import_from_statement(self, node: Node) -> None:
        source = node.child_by_field_name("module_name")
        module, level = "", 0
        if source is not None and source.type == "relative_import":
            for child in source.named_children:
                if child.type == "import_prefix":
                    level = text(child).count(".")
                elif child.type == "dotted_name":
                    module = text(child)
        elif source is not None:
            module = text(source)

        names = []
        for child in node.children_by_field_name("name"):
            if child.type == "aliased_import":
                names.append(
                    (
                        text(child.child_by_field_name("name")),
                        text(child.child_by_field_name("alias")),
                    )
                )
            else:
                names.append((text(child), text(child)))

        self.out.imports.append(
            Import(
                module=module,
                line=line(node),
                names=names,
                level=level,
                wildcard=any(c.type == "wildcard_import" for c in node.named_children),
            )
        )

    def visit_call(self, node: Node) -> None:
        function = node.child_by_field_name("function")
        if function is not None and function.type == "identifier":
            if text(function) != "super":  # `super().f()` is recorded as a call to f
                self.call(node, text(function), None)
        elif function is not None and function.type == "attribute":
            self.call(
                node,
                text(function.child_by_field_name("attribute")),
                self._receiver(function.child_by_field_name("object")),
            )
        self.visit_children(node)

    def _receiver(self, node: Node) -> str:
        if node.type == "identifier" and text(node) in ("self", "cls"):
            return SELF
        if node.type == "call":
            function = node.child_by_field_name("function")
            if function is not None and text(function) == "super":
                return SUPER
        return text(node)
