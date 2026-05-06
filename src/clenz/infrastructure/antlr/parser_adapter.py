"""ANTLR-backed C parser adapter."""

from __future__ import annotations

import re
from time import perf_counter

from antlr4.Token import CommonToken

from clenz.domain.model import (
    GrammarVersion,
    ParseOutcome,
    ParseStatistics,
    SourceUnit,
    StructuralElement,
    StructuralElementKind,
)
from clenz.domain.ports import CSyntaxParser
from clenz.infrastructure.antlr.runtime import (
    ANTLR_GRAMMAR_VERSION,
    load_generated_types,
    parse_source_text,
)


class AntlrCSyntaxParser(CSyntaxParser):
    def __init__(self) -> None:
        self._generated = load_generated_types()

    @property
    def grammar_version(self) -> GrammarVersion:
        return ANTLR_GRAMMAR_VERSION

    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        started_at = perf_counter()
        try:
            parse_result = parse_source_text(source_unit.content, self._generated)
            structure_visitor = _build_structure_visitor(self._generated.visitor_type)(
                token_stream=parse_result.token_stream,
            )
            structure_visitor.visit(parse_result.tree)
            structure_visitor.scan_hidden_tokens()

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
    class CStructureVisitor(visitor_base):
        def __init__(self, *, token_stream) -> None:
            super().__init__()
            self.elements: list[StructuralElement] = []
            self._containers: list[str] = []
            self._token_stream = token_stream
            self._seen_token_indices: set[int] = set()

        # -- Tree visitor methods ------------------------------------------------

        def visitFunctionDefinition(self, ctx):
            declarator = ctx.declarator()
            name = _extract_declarator_name(declarator)
            signature = ctx.getText()
            self._append(
                StructuralElementKind.FUNCTION,
                name,
                ctx,
                signature=signature,
            )
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitStructOrUnionSpecifier(self, ctx):
            struct_or_union_ctx = ctx.structOrUnion()
            is_union = struct_or_union_ctx.Union() is not None
            kind = StructuralElementKind.UNION if is_union else StructuralElementKind.STRUCT
            keyword = "union" if is_union else "struct"

            identifier = ctx.Identifier()
            name = identifier.getText() if identifier is not None else f"<anonymous {keyword}>"
            self._append(kind, name, ctx, signature=f"{keyword} {name}")

            # Only descend into the body if there is one (brace-delimited form)
            if ctx.LeftBrace() is not None:
                return self._with_container(name, lambda: self.visitChildren(ctx))
            return None

        def visitEnumSpecifier(self, ctx):
            identifier = ctx.Identifier()
            name = identifier.getText() if identifier is not None else "<anonymous enum>"
            self._append(StructuralElementKind.ENUM, name, ctx, signature=f"enum {name}")

            if ctx.LeftBrace() is not None:
                return self._with_container(name, lambda: self.visitChildren(ctx))
            return None

        def visitDeclaration(self, ctx):
            decl_specs = ctx.declarationSpecifiers()
            if decl_specs is None:
                return self.visitChildren(ctx)

            if self._is_typedef(decl_specs):
                # In the ANTLR C grammar, typedef names appear as typeSpecifier
                # > typedefName within declarationSpecifiers, NOT as initDeclarator.
                # We collect all typedefName occurrences in the specifiers.  The
                # last one is the name being introduced (earlier ones are
                # type references, e.g. typedef struct {..} Point;).
                typedef_names = _extract_typedef_names(decl_specs)
                for td_name in typedef_names:
                    self._append(
                        StructuralElementKind.TYPEDEF,
                        td_name,
                        ctx,
                        signature=f"typedef ... {td_name}",
                    )

                # Also check for initDeclaratorList (rare but possible for
                # declarator-style typedefs like typedef int *pint;).
                init_decls = ctx.initDeclaratorList()
                if init_decls is not None:
                    for init_decl in init_decls.initDeclarator():
                        decl_name = _extract_declarator_name(init_decl.declarator())
                        self._append(
                            StructuralElementKind.TYPEDEF,
                            decl_name,
                            ctx,
                            signature=f"typedef ... {decl_name}",
                        )
                return self.visitChildren(ctx)

            # Non-typedef top-level declarations with init declarators are
            # treated as global variables.  Declarations inside function bodies
            # will still fire this visitor but they are not "global" in the
            # strict sense; however, the parse tree alone does not distinguish
            # scope, so we record them and let downstream consumers filter.
            if self._is_at_top_level():
                init_decls = ctx.initDeclaratorList()
                if init_decls is not None:
                    for init_decl in init_decls.initDeclarator():
                        decl_name = _extract_declarator_name(init_decl.declarator())
                        self._append(
                            StructuralElementKind.GLOBAL_VARIABLE,
                            decl_name,
                            ctx,
                            signature=ctx.getText(),
                        )

            return self.visitChildren(ctx)

        # -- Hidden-channel preprocessor scanning --------------------------------

        def scan_hidden_tokens(self) -> None:
            tokens = self._token_stream.tokens
            for idx, token in enumerate(tokens):
                if not isinstance(token, CommonToken):
                    continue
                if token.channel != CommonToken.HIDDEN_CHANNEL:
                    continue
                if idx in self._seen_token_indices:
                    continue

                text = token.text
                if text is None:
                    continue

                # Single-line directive: #include <...> or #include "..."
                if text.startswith("#include"):
                    path = _extract_include_path(text)
                    self._seen_token_indices.add(idx)
                    self._append_from_token(
                        StructuralElementKind.INCLUDE,
                        path,
                        token,
                        signature=text.strip(),
                    )
                # Single-line or multi-line macro: #define ...
                elif text.startswith("#define"):
                    macro_name = _extract_macro_name(text)
                    self._seen_token_indices.add(idx)
                    self._append_from_token(
                        StructuralElementKind.MACRO_DEFINITION,
                        macro_name,
                        token,
                        signature=text.strip(),
                    )

        # -- Helpers -------------------------------------------------------------

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

        def _append_from_token(
            self,
            kind,
            name: str,
            token: CommonToken,
            signature: str | None = None,
        ) -> None:
            container = ".".join(self._containers) if self._containers else None
            self.elements.append(
                StructuralElement(
                    kind=kind,
                    name=name,
                    line=token.line,
                    column=token.column,
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

        def _is_typedef(self, decl_specs_ctx) -> bool:
            for decl_spec in decl_specs_ctx.declarationSpecifier():
                storage = decl_spec.storageClassSpecifier()
                if storage is not None and storage.Typedef() is not None:
                    return True
            return False

        def _is_at_top_level(self) -> bool:
            return len(self._containers) == 0

    return CStructureVisitor


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _extract_typedef_names(decl_specs_ctx) -> list[str]:
    """Extract typedef names from declarationSpecifiers.

    In the ANTLR C grammar, a typedef declaration like ``typedef struct {..} Point;``
    parses ``Point`` as a typeSpecifier > typedefName inside declarationSpecifiers.
    The *last* typedefName in the specifier list is the name being introduced;
    earlier ones are references to existing typedefs used as types.
    """
    names: list[str] = []
    for decl_spec in decl_specs_ctx.declarationSpecifier():
        ts = decl_spec.typeSpecifier()
        if ts is None:
            continue
        td = ts.typedefName()
        if td is not None:
            ident = td.Identifier()
            if ident is not None:
                names.append(ident.getText())
    # Only the last typedefName is the name being defined.
    return names[-1:] if names else []


def _extract_declarator_name(declarator_ctx) -> str:
    """Walk a declarator to find the identifier at its core.

    The C grammar nests through pointer -> directDeclarator -> ( ... ) ->
    directDeclarator for parenthesised declarators, and directDeclarator is
    recursive for array/ function suffixes.  We chase the left-most
    Identifier token.
    """
    if declarator_ctx is None:
        return "<unknown>"

    direct = declarator_ctx.directDeclarator()
    if direct is None:
        return declarator_ctx.getText()

    return _drill_direct_declarator(direct)


def _drill_direct_declarator(dd_ctx) -> str:
    # If the directDeclarator has an Identifier, that is the name.
    ident = dd_ctx.Identifier()
    if ident is not None:
        return ident.getText()

    # Otherwise it may be a parenthesised declarator, e.g. (*fp).
    inner_declarator = dd_ctx.declarator()
    if inner_declarator is not None:
        return _extract_declarator_name(inner_declarator)

    # Recursive case: has a child directDeclarator (for array/function suffixes).
    child_dd = dd_ctx.directDeclarator()
    if child_dd is not None:
        return _drill_direct_declarator(child_dd)

    return dd_ctx.getText()


_INCLUDE_PATH_RE = re.compile(r'#include\s+(<[^>]+>|"[^"]+")')
_MACRO_NAME_RE = re.compile(r'#define\s+([A-Za-z_]\w*)')


def _extract_include_path(directive_text: str) -> str:
    match = _INCLUDE_PATH_RE.search(directive_text)
    if match is not None:
        return match.group(1)
    # Fallback: return everything after #include, stripped.
    return directive_text.split(None, 1)[1].strip() if len(directive_text.split(None, 1)) > 1 else "<unknown>"


def _extract_macro_name(directive_text: str) -> str:
    match = _MACRO_NAME_RE.search(directive_text)
    if match is not None:
        return match.group(1)
    return "<unknown>"
