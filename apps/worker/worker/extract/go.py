from __future__ import annotations

from tree_sitter import Node

from worker.extract.base import Extractor, line, text
from worker.extract.types import CLASS, FUNCTION, METHOD, SELF, Import

_TYPE_REFERENCES = ("type_identifier", "qualified_type")


def _type_name(node: Node | None) -> str | None:
    """`*pkg.Base[T]` -> `pkg.Base`."""
    while node is not None:
        if node.type in _TYPE_REFERENCES:
            return text(node)
        if node.type == "pointer_type":
            node = node.named_children[0] if node.named_children else None
        elif node.type == "generic_type":
            node = node.child_by_field_name("type")
        else:
            return None
    return None


class GoExtractor(Extractor):
    language = "go"

    def __init__(self, path: str, source: bytes, root: Node) -> None:
        super().__init__(path, source, root)
        self._receiver: str | None = None

    def visit_package_clause(self, node: Node) -> None:
        for child in node.named_children:
            if child.type == "package_identifier":
                self.out.package = text(child)

    def visit_function_declaration(self, node: Node) -> None:
        symbol = self.define(
            node,
            text(node.child_by_field_name("name")),
            FUNCTION,
            body=node.child_by_field_name("body"),
        )
        with self.inside(symbol):
            self.visit_children(node)

    def visit_method_declaration(self, node: Node) -> None:
        name = text(node.child_by_field_name("name"))
        receiver_name, receiver_type = None, None
        receiver = node.child_by_field_name("receiver")
        for param in receiver.named_children if receiver is not None else []:
            if param.type == "parameter_declaration":
                ident = param.child_by_field_name("name")
                receiver_name = text(ident) if ident is not None else None
                receiver_type = _type_name(param.child_by_field_name("type"))
                break

        symbol = self.define(
            node,
            f"{receiver_type}.{name}" if receiver_type else name,
            METHOD,
            body=node.child_by_field_name("body"),
            owner=receiver_type,
        )
        self._receiver = receiver_name
        with self.inside(symbol):
            self.visit_children(node)
        self._receiver = None

    def visit_type_declaration(self, node: Node) -> None:
        specs = [child for child in node.named_children if child.type == "type_spec"]
        for spec in specs:
            name = text(spec.child_by_field_name("name"))
            definition = spec.child_by_field_name("type")
            shape = {"struct_type": "struct", "interface_type": "interface"}.get(
                definition.type if definition is not None else ""
            )
            symbol = self.define(
                spec,
                name,
                CLASS,
                bases=self._embedded(definition),
                # `type X struct {...}` on its own: the range covers the `type` keyword.
                span=node if len(specs) == 1 else spec,
                signature=f"type {name} {shape}" if shape else f"type {self.signature(spec, None)}",
            )
            if definition is not None and definition.type == "interface_type":
                with self.inside(symbol):
                    self._interface_methods(definition, name)

    def _embedded(self, definition: Node | None) -> list[str]:
        """Embedded structs and interfaces, which Go promotes like inherited members."""
        if definition is None:
            return []
        bases: list[str | None] = []
        if definition.type == "struct_type":
            for fields in definition.named_children:
                if fields.type != "field_declaration_list":
                    continue
                for declaration in fields.named_children:
                    if (
                        declaration.type == "field_declaration"
                        and declaration.child_by_field_name("name") is None
                    ):
                        bases.append(_type_name(declaration.child_by_field_name("type")))
        elif definition.type == "interface_type":
            for element in definition.named_children:
                if element.type in _TYPE_REFERENCES:
                    bases.append(text(element))
                elif (
                    element.type in ("type_elem", "constraint_elem")
                    and element.named_child_count == 1
                ):
                    bases.append(_type_name(element.named_children[0]))
        return [base for base in bases if base]

    def _interface_methods(self, definition: Node, owner: str) -> None:
        for element in definition.named_children:
            if element.type in ("method_elem", "method_spec"):
                name = element.child_by_field_name("name")
                if name is not None:
                    self.define(element, f"{owner}.{text(name)}", METHOD, owner=owner)

    def visit_import_declaration(self, node: Node) -> None:
        pending = list(node.named_children)
        while pending:
            child = pending.pop(0)
            if child.type == "import_spec_list":
                pending = list(child.named_children) + pending
            elif child.type == "import_spec":
                alias = child.child_by_field_name("name")
                self.out.imports.append(
                    Import(
                        module=text(child.child_by_field_name("path")).strip('"`'),
                        line=line(child),
                        alias=text(alias) if alias is not None else None,
                    )
                )

    def visit_call_expression(self, node: Node) -> None:
        function = node.child_by_field_name("function")
        if function is not None and function.type == "identifier":
            self.call(node, text(function), None)
        elif function is not None and function.type == "selector_expression":
            operand = function.child_by_field_name("operand")
            name = function.child_by_field_name("field")
            if operand is not None and name is not None:
                is_self = operand.type == "identifier" and text(operand) == self._receiver
                self.call(node, text(name), SELF if is_self else text(operand))
        self.visit_children(node)
