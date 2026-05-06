"""Token-based C code smell scanner using the generated CLexer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from clenz.domain.model import SourceUnit
from clenz.domain.ports import CSmellScanner
from clenz.domain.smells import CodeSmell, SmellKind, SmellReport, SmellSeverity

_UNSAFE_FUNCTIONS = frozenset({"gets", "strcpy", "sprintf", "strcat", "vsprintf"})
_MALLOC_NAMES = frozenset({"malloc", "calloc", "realloc"})
_IO_FUNCTIONS = frozenset({"fopen", "fclose", "fread", "fwrite", "fflush"})
_ALLOWED_SHORT_NAMES = frozenset({"i", "j", "k", "x", "y", "z", "n", "m", "r", "c", "p"})
_IGNORED_NUMBERS = frozenset({"0", "1", "2", "-1", "0u", "1u", "0U", "1U", "NULL"})
_MAX_FUNCTION_LINES = 60
_MAX_FILE_LINES = 500


@dataclass(slots=True)
class _Token:
    type: int
    text: str
    line: int
    column: int


def _lex_tokens(source: str, lexer_type: type) -> list[_Token]:
    from antlr4 import CommonTokenStream, InputStream

    input_stream = InputStream(source)
    lexer = lexer_type(input_stream)
    lexer.removeErrorListeners()
    all_tokens = lexer.getAllTokens()
    return [
        _Token(type=t.type, text=t.text, line=t.line, column=t.column)
        for t in all_tokens
    ]


def _lex_default(source: str, lexer_type: type) -> list[_Token]:
    from antlr4 import CommonTokenStream, InputStream

    input_stream = InputStream(source)
    lexer = lexer_type(input_stream)
    lexer.removeErrorListeners()
    stream = CommonTokenStream(lexer)
    stream.fill()
    return [
        _Token(type=t.type, text=t.text, line=t.line, column=t.column)
        for t in stream.tokens
        if t.channel == 0 and t.type != -1
    ]


class AntlrCSmellScanner(CSmellScanner):
    def scan(self, source_unit: SourceUnit) -> SmellReport:
        from clenz.infrastructure.antlr.runtime import load_generated_types

        generated = load_generated_types()
        lexer_type = generated.lexer_type
        source = source_unit.content
        lines = source.splitlines()

        all_tokens = _lex_tokens(source, lexer_type)
        default_tokens = _lex_default(source, lexer_type)

        smells: list[CodeSmell] = []
        smells.extend(_check_unsafe_functions(default_tokens))
        smells.extend(_check_unchecked_malloc(default_tokens))
        smells.extend(_check_unchecked_return(default_tokens))
        smells.extend(_check_magic_numbers(default_tokens, lexer_type))
        smells.extend(_check_short_names(default_tokens, lexer_type))
        smells.extend(_check_uninitialized_vars(default_tokens, lexer_type))
        smells.extend(_check_global_variables(default_tokens, lexer_type))
        smells.extend(_check_long_functions(default_tokens, lines, lexer_type))
        smells.extend(_check_missing_const(default_tokens, lexer_type))
        smells.extend(_check_large_file(lines))
        smells.extend(_check_memory_leak_risk(default_tokens))

        function_count = sum(
            1
            for i, t in enumerate(default_tokens)
            if t.text == "("
            and i >= 2
            and default_tokens[i - 1].type == lexer_type.Identifier
            and (i < 2 or default_tokens[i - 2].type != lexer_type.Identifier)
        )

        return SmellReport(
            source_location=source_unit.location,
            smells=tuple(sorted(smells, key=lambda s: (s.line, s.column))),
            line_count=len(lines),
            function_count=function_count,
        )


# ---------------------------------------------------------------------------
# Individual rule checks
# ---------------------------------------------------------------------------


def _check_unsafe_functions(tokens: list[_Token]) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    for tok in tokens:
        if tok.text in _UNSAFE_FUNCTIONS:
            smells.append(
                CodeSmell(
                    kind=SmellKind.UNSAFE_FUNCTION,
                    severity=SmellSeverity.ERROR,
                    message=f"unsafe function '{tok.text}' — use safer alternative",
                    line=tok.line,
                    column=tok.column,
                )
            )
    return smells


def _check_unchecked_malloc(tokens: list[_Token]) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    for i, tok in enumerate(tokens):
        if tok.text not in _MALLOC_NAMES:
            continue
        # Look ahead for a null-check pattern: if (!ptr or if (ptr == NULL
        found_check = False
        for j in range(i + 1, min(i + 15, len(tokens))):
            t = tokens[j]
            if t.text == ";":
                break
            if t.text == "if" and j + 2 < len(tokens):
                next_t = tokens[j + 2] if tokens[j + 1].text == "(" else tokens[j + 1]
                if next_t.text in ("!", "==", "!="):
                    found_check = True
                    break
        if not found_check:
            var_name = _find_assigned_var(tokens, i)
            msg = f"unchecked {tok.text}()"
            if var_name:
                msg += f" — add null check for '{var_name}'"
            smells.append(
                CodeSmell(
                    kind=SmellKind.UNCHECKED_MALLOC,
                    severity=SmellSeverity.ERROR,
                    message=msg,
                    line=tok.line,
                    column=tok.column,
                )
            )
    return smells


def _find_assigned_var(tokens: list[_Token], malloc_idx: int) -> str:
    for j in range(malloc_idx - 1, max(malloc_idx - 10, -1), -1):
        if tokens[j].text == "=" and j > 0:
            return tokens[j - 1].text
        if tokens[j].text == ";":
            break
    return ""


def _check_unchecked_return(tokens: list[_Token]) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    for i, tok in enumerate(tokens):
        if tok.text not in _IO_FUNCTIONS:
            continue
        # Look back — if previous non-whitespace token is 'if' or '==' or '!=', it's checked
        if i >= 2:
            prev = tokens[i - 1]
            if prev.text in ("=", "("):
                # Assignment or direct arg — check if followed by error handling
                found_check = False
                for j in range(i + 1, min(i + 20, len(tokens))):
                    if tokens[j].text == "if" or tokens[j].text == "||" or tokens[j].text == "&&":
                        found_check = True
                        break
                    if tokens[j].text == ";":
                        break
                if not found_check:
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.UNCHECKED_RETURN,
                            severity=SmellSeverity.WARNING,
                            message=f"unchecked return value of '{tok.text}'",
                            line=tok.line,
                            column=tok.column,
                        )
                    )
    return smells


def _check_magic_numbers(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    const_type = getattr(lexer_type, "Constant", None)
    if const_type is None:
        return []

    smells: list[CodeSmell] = []
    for tok in tokens:
        if tok.type != const_type:
            continue
        text = tok.text
        if not text or text in _IGNORED_NUMBERS:
            continue
        if text.startswith("0x") or text.startswith("0X"):
            continue
        smells.append(
            CodeSmell(
                kind=SmellKind.MAGIC_NUMBER,
                severity=SmellSeverity.INFO,
                message=f"magic number '{text}' — consider defining a named constant",
                line=tok.line,
                column=tok.column,
            )
        )
    return smells


def _check_short_names(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    id_type = getattr(lexer_type, "Identifier", None)
    if id_type is None:
        return smells

    seen: set[tuple[int, int]] = set()
    for i, tok in enumerate(tokens):
        if tok.type != id_type:
            continue
        if len(tok.text) <= 2 and tok.text not in _ALLOWED_SHORT_NAMES:
            if tok.text.isalpha() and (tok.line, tok.column) not in seen:
                seen.add((tok.line, tok.column))
                smells.append(
                    CodeSmell(
                        kind=SmellKind.SHORT_NAME,
                        severity=SmellSeverity.INFO,
                        message=f"short name '{tok.text}' — consider a more descriptive name",
                        line=tok.line,
                        column=tok.column,
                    )
                )
    return smells


def _check_uninitialized_vars(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    type_keywords = {
        lexer_type.Int, lexer_type.Char, lexer_type.Float, lexer_type.Double,
        lexer_type.Long, lexer_type.Short, lexer_type.Signed, lexer_type.Unsigned,
        lexer_type.Void, lexer_type.Bool,
    }
    type_keywords = {t for t in type_keywords if t is not None}

    for i, tok in enumerate(tokens):
        if tok.type not in type_keywords:
            continue
        # Look ahead for: type Identifier ;
        if i + 2 < len(tokens):
            name_tok = tokens[i + 1]
            after_tok = tokens[i + 2]
            if name_tok.type == lexer_type.Identifier and after_tok.text == ";":
                smells.append(
                    CodeSmell(
                        kind=SmellKind.UNINITIALIZED_VAR,
                        severity=SmellSeverity.WARNING,
                        message=f"uninitialized variable '{name_tok.text}' — initialize at declaration",
                        line=name_tok.line,
                        column=name_tok.column,
                    )
                )
    return smells


def _check_global_variables(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    brace_depth = 0
    paren_depth = 0
    type_keywords = {
        lexer_type.Int, lexer_type.Char, lexer_type.Float, lexer_type.Double,
        lexer_type.Long, lexer_type.Short, lexer_type.Signed, lexer_type.Unsigned,
        lexer_type.Static, lexer_type.Extern, lexer_type.Const,
        lexer_type.Volatile, lexer_type.Void, lexer_type.Bool,
    }
    type_keywords = {t for t in type_keywords if t is not None}

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth = max(brace_depth - 1, 0)
        elif tok.text == "(":
            paren_depth += 1
        elif tok.text == ")":
            paren_depth = max(paren_depth - 1, 0)

        if brace_depth == 0 and paren_depth == 0 and tok.type in type_keywords:
            # Scan ahead for identifier followed by = or ; (not a function definition)
            for j in range(i + 1, min(i + 8, len(tokens))):
                jt = tokens[j]
                if jt.type == lexer_type.Identifier:
                    if j + 1 < len(tokens) and tokens[j + 1].text in ("=", ";", "["):
                        # Check it's not a function parameter list
                        is_typedef = any(
                            tokens[k].type == lexer_type.Typedef for k in range(max(i - 3, 0), i)
                        )
                        if not is_typedef:
                            smells.append(
                                CodeSmell(
                                    kind=SmellKind.GLOBAL_VARIABLE,
                                    severity=SmellSeverity.WARNING,
                                    message=f"global variable '{jt.text}' — prefer passing through parameters",
                                    line=jt.line,
                                    column=jt.column,
                                )
                            )
                    break
                if jt.text == "(":
                    break
    return smells


def _check_long_functions(
    tokens: list[_Token], lines: list[str], lexer_type: type
) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    brace_depth = 0
    in_function = False
    func_name = ""
    func_start_line = 0

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            if brace_depth == 0 and in_function:
                func_start_line = tok.line
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
            if brace_depth == 0 and in_function:
                span = tok.line - func_start_line
                if span > _MAX_FUNCTION_LINES:
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.LONG_FUNCTION,
                            severity=SmellSeverity.WARNING,
                            message=(
                                f"function '{func_name}' is {span} lines "
                                f"(max {_MAX_FUNCTION_LINES}) — split into smaller functions"
                            ),
                            line=func_start_line,
                            column=0,
                        )
                    )
                in_function = False
        elif (
            brace_depth == 0
            and tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
        ):
            name = tokens[i - 1].text
            # Skip if it's a function call (previous token before name was '=' or ',' or '(')
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return"):
                continue
            if name not in _UNSAFE_FUNCTIONS and name not in _IO_FUNCTIONS and name not in _MALLOC_NAMES:
                func_name = name
                in_function = True
    return smells


def _check_missing_const(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    # Pattern: function parameter ( char *name ) or ( char * name ) without const
    for i, tok in enumerate(tokens):
        if tok.type != getattr(lexer_type, "Char", None):
            continue
        if i + 1 < len(tokens) and tokens[i + 1].text == "*":
            # Check if this is inside a parameter list
            if i + 2 < len(tokens) and tokens[i + 2].type == lexer_type.Identifier:
                # Look back for const
                has_const = False
                for j in range(max(i - 3, 0), i):
                    if tokens[j].text == "const":
                        has_const = True
                        break
                if not has_const:
                    var_name = tokens[i + 2].text
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.MISSING_CONST,
                            severity=SmellSeverity.INFO,
                            message=f"parameter 'char *{var_name}' could be 'const char *{var_name}'",
                            line=tok.line,
                            column=tok.column,
                        )
                    )
    return smells


def _check_large_file(lines: list[str]) -> list[CodeSmell]:
    if len(lines) > _MAX_FILE_LINES:
        return [
            CodeSmell(
                kind=SmellKind.LARGE_FILE,
                severity=SmellSeverity.WARNING,
                message=(
                    f"file is {len(lines)} lines (max {_MAX_FILE_LINES}) "
                    "— split into modules"
                ),
                line=1,
                column=0,
            )
        ]
    return []


def _check_memory_leak_risk(tokens: list[_Token]) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    alloc_vars: dict[str, int] = {}

    for tok in tokens:
        if tok.text in _MALLOC_NAMES:
            var = _find_assigned_var(tokens, tokens.index(tok))
            if var:
                alloc_vars[var] = tok.line
        elif tok.text == "free":
            # Look for free(ptr)
            idx = tokens.index(tok)
            for j in range(idx + 1, min(idx + 5, len(tokens))):
                if tokens[j].type != -1 and tokens[j].text in alloc_vars:
                    del alloc_vars[tokens[j].text]
                    break
        elif tok.text == "return":
            # At return, check if allocated vars are freed
            idx = tokens.index(tok)
            for j in range(idx + 1, min(idx + 5, len(tokens))):
                if tokens[j].text in alloc_vars:
                    del alloc_vars[tokens[j].text]
                    break

    for var, line in alloc_vars.items():
        smells.append(
            CodeSmell(
                kind=SmellKind.MEMORY_LEAK_RISK,
                severity=SmellSeverity.WARNING,
                message=f"'{var}' allocated at line {line} — ensure it is freed on all paths",
                line=line,
                column=0,
            )
        )
    return smells
