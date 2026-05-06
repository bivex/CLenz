"""ANTLR-backed Swift parser adapter."""

from __future__ import annotations

from time import perf_counter

from swifta.domain.model import (
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    SourceUnit,
    StructuralElement,
    StructuralElementKind,
)
from swifta.domain.ports import SwiftSyntaxParser
from swifta.infrastructure.antlr.runtime import (
    ANTLR_GRAMMAR_VERSION,
    load_generated_types,
    parse_source_text,
)


class AntlrSwiftSyntaxParser(SwiftSyntaxParser):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    @property
    def grammar_version(self) -> GrammarVersion:
        return ANTLR_GRAMMAR_VERSION

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        started_at = perf_counter()
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            structure_visitor = _build_structure_visitor(self._generated.visitor_type)()
            structure_visitor.visit(parse_result.tree)

            elements = tuple(structure_visitor.elements)
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)

            return ParseOutcome.success(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                diagnostics=parse_result.diagnostics,
                structural_elements=elements,
                statistics=ParseStatistics(
                    token_count=len(parse_result.token_stream.tokens),
                    structural_element_count=len(elements),
                    diagnostic_count=len(parse_result.diagnostics),
                    elapsed_ms=elapsed_ms,
                ),
            )
        except Exception as error:
            elapsed_ms = round((perf_counter() - started_at) * 1000, 3)
            return ParseOutcome.technical_failure(
                source_unit=source_unit,
                grammar_version=self.grammar_version,
                message=str(error),
                elapsed_ms=elapsed_ms,
            )


def _build_structure_visitor(visitor_base: type) -> type:
    class SwiftStructureVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.elements: list[StructuralElement] = []
            self._containers: list[str] = []

        def visitImport_declaration(self, ctx):
            import_path = ctx.import_path().getText()
            self._append(
                StructuralElementKind.IMPORT,
                import_path,
                ctx,
                signature=f"import {import_path}",
            )
            return None

        def visitTypealias_declaration(self, ctx):
            name = ctx.typealias_name().getText()
            self._append(
                StructuralElementKind.TYPE_ALIAS,
                name,
                ctx,
                signature=f"typealias {name}",
            )
            return None

        def visitConstant_declaration(self, ctx):
            for name in self._extract_pattern_names(ctx.pattern_initializer_list()):
                self._append(
                    StructuralElementKind.CONSTANT,
                    name,
                    ctx,
                    signature=f"let {name}",
                )
            return None

        def visitVariable_declaration(self, ctx):
            if ctx.variable_name() is not None:
                variable_name = ctx.variable_name().getText()
                self._append(
                    StructuralElementKind.VARIABLE,
                    variable_name,
                    ctx,
                    signature=f"var {variable_name}",
                )
                return None

            for name in self._extract_pattern_names(ctx.pattern_initializer_list()):
                self._append(
                    StructuralElementKind.VARIABLE,
                    name,
                    ctx,
                    signature=f"var {name}",
                )
            return None

        def visitFunction_declaration(self, ctx):
            name = ctx.function_name().getText()
            signature = ctx.function_signature().getText()
            self._append(
                StructuralElementKind.FUNCTION,
                name,
                ctx,
                signature=f"func {name}{signature}",
            )
            return None

        def visitEnum_declaration(self, ctx):
            name = self._extract_enum_name(ctx)
            self._append(StructuralElementKind.ENUM, name, ctx, signature=f"enum {name}")
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitStruct_declaration(self, ctx):
            name = ctx.struct_name().getText()
            self._append(StructuralElementKind.STRUCT, name, ctx, signature=f"struct {name}")
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitClass_declaration(self, ctx):
            name = ctx.class_name().getText()
            self._append(StructuralElementKind.CLASS, name, ctx, signature=f"class {name}")
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitProtocol_declaration(self, ctx):
            name = ctx.protocol_name().getText()
            self._append(
                StructuralElementKind.PROTOCOL,
                name,
                ctx,
                signature=f"protocol {name}",
            )
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitExtension_declaration(self, ctx):
            name = ctx.type_identifier().getText()
            self._append(
                StructuralElementKind.EXTENSION,
                name,
                ctx,
                signature=f"extension {name}",
            )
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def _append(self, kind, name: str, ctx, signature: str | None = None) -> None:
            container = ".".join(self._containers) if self._containers else None
            self.elements.append(
                StructuralElement(
                    kind=kind,
                    name=name,
                    line=ctx.start.line,
                    column=ctx.start.column,
                    container=container,
                    signature=signature,
                )
            )

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_enum_name(self, enum_ctx) -> str:
            if enum_ctx.union_style_enum() is not None:
                return enum_ctx.union_style_enum().enum_name().getText()
            if enum_ctx.raw_value_style_enum() is not None:
                return enum_ctx.raw_value_style_enum().enum_name().getText()
            return "enum"

        def _extract_pattern_names(self, pattern_initializer_list_ctx) -> tuple[str, ...]:
            names: list[str] = []
            for pattern_initializer_ctx in pattern_initializer_list_ctx.pattern_initializer():
                names.extend(self._extract_names_from_pattern(pattern_initializer_ctx.pattern()))
            return tuple(names)

        def _extract_names_from_pattern(self, pattern_ctx) -> list[str]:
            if pattern_ctx is None:
                return []

            names: list[str] = []
            identifier_pattern_ctx = getattr(pattern_ctx, "identifier_pattern", None)
            if callable(identifier_pattern_ctx):
                identifier = pattern_ctx.identifier_pattern()
                if identifier is not None:
                    names.append(identifier.getText())

            tuple_pattern_ctx = getattr(pattern_ctx, "tuple_pattern", None)
            if callable(tuple_pattern_ctx):
                tuple_pattern = pattern_ctx.tuple_pattern()
                if tuple_pattern is not None and tuple_pattern.tuple_pattern_element_list() is not None:
                    for element in tuple_pattern.tuple_pattern_element_list().tuple_pattern_element():
                        names.extend(self._extract_names_from_pattern(element.pattern()))

            nested_pattern_accessor = getattr(pattern_ctx, "pattern", None)
            if callable(nested_pattern_accessor):
                nested_pattern = pattern_ctx.pattern()
                if nested_pattern is not None and nested_pattern is not pattern_ctx:
                    names.extend(self._extract_names_from_pattern(nested_pattern))

            if not names:
                names.append(pattern_ctx.getText())

            return names

    return SwiftStructureVisitor
