"""Token-based C code smell scanner using the generated CLexer."""

from __future__ import annotations

import re
from dataclasses import dataclass

from clenz.domain.model import SourceUnit
from clenz.domain.ports import CSmellScanner
from clenz.domain.smells import CodeSmell, SmellKind, SmellReport, SmellSeverity

_UNSAFE_FUNCTIONS = frozenset(
    {"gets", "strcpy", "sprintf", "strcat", "vsprintf"}
)
_MALLOC_NAMES = frozenset({"malloc", "calloc", "realloc", "strdup", "strndup"})
_IO_FUNCTIONS = frozenset(
    {"printf", "scanf", "fprintf", "fscanf", "sprintf", "snprintf",
     "fopen", "fclose", "fread", "fwrite", "fflush", "getchar", "putchar",
     "gets", "puts", "fgets", "fputs"}
)
_MEMORY_FUNCTIONS = frozenset({"malloc", "calloc", "realloc", "free", "strdup", "strndup"})
_STRING_FUNCTIONS = frozenset({"strcpy", "strncpy", "strcat", "strncat", "sprintf", "snprintf",
                                "strlen", "strcmp", "strncmp", "strchr", "strstr"})
_MATH_FUNCTIONS = frozenset({"abs", "sqrt", "pow", "sin", "cos", "tan", "log", "exp",
                              "ceil", "floor", "round", "fabs", "fmod"})
_ALLOWED_SHORT_NAMES = frozenset(
    {"i", "j", "k", "x", "y", "z", "n", "m", "r", "c", "p",
     "t", "s", "a", "b", "e", "f", "g", "h", "u", "v", "w"}
)
_IGNORED_NUMBERS = frozenset({
    "0", "1", "2", "-1", "0u", "1u", "0U", "1U",
    "0l", "1l", "0L", "1L", "0ul", "1ul", "0ULL", "1ULL",
    "0x0", "0x1",
})
_MAX_FUNCTION_LINES = 60
_MAX_FILE_LINES = 500
_MAX_PARAMETERS = 5
_MAX_RETURN_COUNT = 2
_MAX_NESTING_DEPTH = 4
_MAX_CYCLOMATIC_COMPLEXITY = 8
_TODO_PATTERNS = re.compile(
    r"//\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|REVIEW|OPTIMIZE|WORKAROUND)",
    re.IGNORECASE,
)
_MULTI_COMMENT_TODO = re.compile(
    r"/\*\s*(TODO|FIXME|HACK|XXX|BUG|NOTE|REVIEW|OPTIMIZE|WORKAROUND)",
    re.IGNORECASE,
)


@dataclass
class _Token:
    type: int
    text: str
    line: int
    column: int


@dataclass
class _FunctionRegion:
    """Represents a function body region for scoped analysis."""
    name: str
    start_idx: int
    open_brace_idx: int | None
    close_brace_idx: int | None


# ---------------------------------------------------------------------------
# Lexing helpers
# ---------------------------------------------------------------------------


def _lex_tokens(source: str, lexer_type: type) -> list[_Token]:
    """Get all tokens including hidden/comment channels."""
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
    """Get only default-channel tokens (no comments, no whitespace)."""
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


def _lex_all_tokens(source: str, lexer_type: type) -> list[_Token]:
    """Get tokens on all channels, preserving comment tokens."""
    from antlr4 import CommonTokenStream, InputStream

    input_stream = InputStream(source)
    lexer = lexer_type(input_stream)
    lexer.removeErrorListeners()
    all_tokens = lexer.getAllTokens()
    return [
        _Token(type=t.type, text=t.text, line=t.line, column=t.column)
        for t in all_tokens
    ]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class AntlrCSmellScanner(CSmellScanner):
    def scan(self, source_unit: SourceUnit) -> SmellReport:
        from clenz.infrastructure.antlr.runtime import load_generated_types

        generated = load_generated_types()
        lexer_type = generated.lexer_type
        # Prepend newline so that strip()'d content still aligns line numbers
        # with the original source text (which had a leading newline).
        source = "\n" + source_unit.content
        lines = source.splitlines()

        all_tokens = _lex_all_tokens(source, lexer_type)
        default_tokens = _lex_default(source, lexer_type)

        smells: list[CodeSmell] = []

        # --- Token-level checks (on default-channel tokens) ---
        smells.extend(_check_unsafe_functions(default_tokens))
        smells.extend(_check_unchecked_malloc(default_tokens))
        smells.extend(_check_unchecked_return(default_tokens))
        smells.extend(_check_magic_numbers(default_tokens, lexer_type))
        smells.extend(_check_short_names(default_tokens, lexer_type))
        smells.extend(_check_uninitialized_vars(default_tokens, lexer_type))
        smells.extend(_check_global_variables(default_tokens, lexer_type))
        smells.extend(_check_long_functions(default_tokens, lines, lexer_type))
        smells.extend(_check_missing_const(default_tokens, lexer_type))
        smells.extend(_check_too_many_parameters(default_tokens, lexer_type))
        smells.extend(_check_return_count(default_tokens, lexer_type))
        smells.extend(_check_deep_nesting(default_tokens, lexer_type))
        smells.extend(_check_empty_control_flow(default_tokens, lexer_type))
        smells.extend(_check_cyclomatic_complexity(default_tokens, lexer_type))
        smells.extend(_check_mixed_abstraction(default_tokens, lexer_type))

        # --- Comment-level checks (need all tokens including comments) ---
        smells.extend(_check_todo_comments(all_tokens))

        # --- Large file (line count) ---
        smells.extend(_check_large_file(lines))

        # --- Memory leak risk (uses full token stream) ---
        smells.extend(_check_memory_leak_risk(default_tokens, lexer_type))

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
        for j in range(i + 1, min(i + 30, len(tokens))):
            t = tokens[j]
            if t.text == "if" and j + 2 < len(tokens):
                if _is_null_check(tokens, j):
                    found_check = True
                    break
            if t.text in ("}", "{"):
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


def _is_null_check(tokens: list[_Token], if_idx: int) -> bool:
    """Check if an 'if' token is a null-pointer check pattern."""
    if tokens[if_idx].text != "if":
        return False
    # Find matching ( ... ) and look for !, ==, != inside
    if if_idx + 1 >= len(tokens) or tokens[if_idx + 1].text != "(":
        return False
    depth = 0
    for k in range(if_idx + 1, min(if_idx + 15, len(tokens))):
        t = tokens[k]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth == 0:
                break
        elif t.text in ("!", "==", "!="):
            return True
    return False


def _check_unchecked_return(tokens: list[_Token]) -> list[CodeSmell]:
    smells: list[CodeSmell] = []
    for i, tok in enumerate(tokens):
        if tok.text not in _IO_FUNCTIONS:
            continue
        if i >= 2:
            prev = tokens[i - 1]
            if prev.text in ("=", "("):
                found_check = False
                for j in range(i + 1, min(i + 40, len(tokens))):
                    t = tokens[j]
                    if t.text == "if" and j + 2 < len(tokens):
                        if _is_null_check(tokens, j):
                            found_check = True
                            break
                    if t.text in ("||", "&&"):
                        found_check = True
                        break
                    if t.text in ("}", "{"):
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
    for tok in tokens:
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
    """Detect global variables at file scope (outside any function body).

    Skip declarations that are part of a typedef or struct/enum body.
    """
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
            # Skip typedef and extern declarations entirely
            if tok.type == getattr(lexer_type, "Typedef", None):
                continue
            # Skip extern type keyword itself — it's a declaration, not a definition
            if tok.type == getattr(lexer_type, "Extern", None):
                continue
            # Skip if preceded by 'extern' (declaration, not definition)
            is_extern = False
            for k in range(max(i - 5, 0), i):
                if tokens[k].type == getattr(lexer_type, "Extern", None):
                    is_extern = True
                    break
                if tokens[k].text == ";":
                    break
            if is_extern:
                continue

            # Check if this type specifier is part of a struct/enum/union declaration
            is_struct_or_enum_type = False
            for j in range(max(i - 5, 0), i):
                if tokens[j].text in ("struct", "enum", "union"):
                    is_struct_or_enum_type = True
                    break
                if tokens[j].type in type_keywords and tokens[j].type != lexer_type.Const:
                    break
            if is_struct_or_enum_type:
                continue

            # Scan ahead for identifier followed by = or ; (not a function definition)
            for j in range(i + 1, min(i + 8, len(tokens))):
                jt = tokens[j]
                if jt.type == lexer_type.Identifier:
                    if j + 1 < len(tokens) and tokens[j + 1].text in ("=", ";", "["):
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
                    break  # Function declaration, not a variable
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
            # Skip if it's a function call (previous token before name was '=' or ',' or '(' or 'return')
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name not in _UNSAFE_FUNCTIONS and name not in _IO_FUNCTIONS and name not in _MALLOC_NAMES:
                func_name = name
                in_function = True

    return smells


def _count_function_parameters(tokens: list[_Token], open_paren_idx: int) -> int:
    """Count the number of comma-separated parameters in a function definition."""
    depth = 0
    count = 0
    in_param = False
    for j in range(open_paren_idx, min(open_paren_idx + 50, len(tokens))):
        t = tokens[j]
        if t.text == "(":
            depth += 1
            if depth == 1:
                continue
        elif t.text == ")":
            depth -= 1
            if depth == 0:
                if in_param:
                    count += 1
                break
        elif t.text == "," and depth == 1:
            count += 1
            in_param = False
        elif depth == 1 and t.type != -1 and t.text not in (" ", "\t", "\n"):
            in_param = True
    return count


def _check_too_many_parameters(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag functions with more than _MAX_PARAMETERS parameters."""
    smells: list[CodeSmell] = []
    brace_depth = 0
    paren_depth = 0

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
        elif tok.text == "(":
            paren_depth += 1
        elif tok.text == ")":
            paren_depth -= 1

        # Only at top level (outside any function body)
        if brace_depth != 0:
            continue

        if (
            tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
            and paren_depth == 1
        ):
            name = tokens[i - 1].text
            # Skip function calls
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name in _UNSAFE_FUNCTIONS or name in _IO_FUNCTIONS or name in _MALLOC_NAMES:
                continue

            param_count = _count_function_parameters(tokens, i)
            if param_count > _MAX_PARAMETERS:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.TOO_MANY_PARAMETERS,
                        severity=SmellSeverity.WARNING,
                        message=(
                            f"function '{name}' has {param_count} parameters "
                            f"(max {_MAX_PARAMETERS}) — group into a struct"
                        ),
                        line=tok.line,
                        column=tok.column,
                    )
                )

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


def _check_deep_nesting(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag when brace nesting depth exceeds _MAX_NESTING_DEPTH within a function body."""
    smells: list[CodeSmell] = []
    func_regions = _find_function_regions(tokens, lexer_type)

    for region in func_regions:
        if region.open_brace_idx is None:
            continue
        start = region.open_brace_idx + 1  # skip function's own brace
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        depth = 0
        for idx in range(start, min(end + 1, len(tokens))):
            tok = tokens[idx]
            if tok.text == "{":
                depth += 1
            elif tok.text == "}":
                if depth > _MAX_NESTING_DEPTH:
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.DEEP_NESTING,
                            severity=SmellSeverity.WARNING,
                            message=(
                                f"deep nesting (depth {depth}) in '{region.name}' "
                                "— extract inner logic into helper functions"
                            ),
                            line=tok.line - 1,
                            column=tok.column,
                        )
                    )
                depth = max(depth - 1, 0)

    return smells


def _check_empty_control_flow(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Detect empty bodies in if, while, for, do-while statements."""
    smells: list[CodeSmell] = []

    # --- Check if / while / for ---
    for i, tok in enumerate(tokens):
        if tok.text not in ("if", "while", "for"):
            continue

        # Find the opening brace
        brace_start = None
        depth = 0
        for j in range(i + 1, min(i + 30, len(tokens))):
            if tokens[j].text == "(":
                depth += 1
            elif tokens[j].text == ")":
                depth -= 1
                if depth == 0:
                    for k in range(j + 1, min(j + 5, len(tokens))):
                        if tokens[k].text == "{":
                            brace_start = k
                            break
                        if tokens[k].text not in (" ", "\t", "\n", ""):
                            break
                    break

        if brace_start is None:
            continue

        # Find the matching closing brace
        depth = 0
        brace_end = None
        for j in range(brace_start, min(brace_start + 100, len(tokens))):
            if tokens[j].text == "{":
                depth += 1
            elif tokens[j].text == "}":
                depth -= 1
                if depth == 0:
                    brace_end = j
                    break

        if brace_end is None:
            continue

        # Check if there's anything meaningful between { and }
        has_content = False
        for j in range(brace_start + 1, brace_end):
            if tokens[j].type == lexer_type.Identifier:
                has_content = True
                break
            if tokens[j].text not in (" ", "\t", "\n", "", ";"):
                has_content = True
                break

        if not has_content:
            smells.append(
                CodeSmell(
                    kind=SmellKind.EMPTY_CONTROL_FLOW,
                    severity=SmellSeverity.WARNING,
                    message=f"empty body in '{tok.text}' statement at line {tok.line}",
                    line=tok.line,
                    column=tok.column,
                )
            )

    # --- Check do-while ---
    for i, tok in enumerate(tokens):
        if tok.text != "do":
            continue

        depth = 0
        body_start = None
        body_end = None
        for j in range(i + 1, min(i + 100, len(tokens))):
            if tokens[j].text == "{":
                if depth == 0:
                    body_start = j
                depth += 1
            elif tokens[j].text == "}":
                depth -= 1
                if depth == 0:
                    body_end = j
                    break

        if body_start is None:
            continue

        has_content = False
        for j in range(body_start + 1, body_end if body_end else body_start + 1):
            if tokens[j].type == lexer_type.Identifier:
                has_content = True
                break
            if tokens[j].text not in (" ", "\t", "\n", "", ";"):
                has_content = True
                break

        if not has_content:
            smells.append(
                CodeSmell(
                    kind=SmellKind.EMPTY_CONTROL_FLOW,
                    severity=SmellSeverity.WARNING,
                    message=f"empty body in 'do-while' statement at line {tok.line}",
                    line=tok.line,
                    column=tok.column,
                )
            )

    return smells


def _check_return_count(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag functions with too many return statements (> _MAX_RETURN_COUNT)."""
    smells: list[CodeSmell] = []
    func_regions = _find_function_regions(tokens, lexer_type)

    for region in func_regions:
        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        return_count = 0
        for idx in range(start, min(end + 1, len(tokens))):
            if tokens[idx].text == "return":
                return_count += 1

        # For deeply nested functions, use a stricter threshold
        max_body_depth = 0
        body_depth = 0
        for idx in range(start, min(end + 1, len(tokens))):
            t = tokens[idx]
            if t.text == "{":
                body_depth += 1
                max_body_depth = max(max_body_depth, body_depth)
            elif t.text == "}":
                body_depth = max(body_depth - 1, 0)

        effective_max = _MAX_RETURN_COUNT
        if max_body_depth > _MAX_NESTING_DEPTH:
            effective_max = _MAX_RETURN_COUNT - 1

        if return_count > effective_max:
            smells.append(
                CodeSmell(
                    kind=SmellKind.RETURN_COUNT,
                    severity=SmellSeverity.INFO,
                    message=(
                        f"function '{region.name}' has {return_count} return statements "
                        f"(max {_MAX_RETURN_COUNT}) — consider using a single exit point"
                    ),
                    line=tokens[start].line,
                    column=0,
                )
            )

    return smells


def _check_cyclomatic_complexity(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Calculate cyclomatic complexity per function: 1 + decision points."""
    smells: list[CodeSmell] = []
    func_regions = _find_function_regions(tokens, lexer_type)

    for region in func_regions:
        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        complexity = 1
        for idx in range(start, min(end + 1, len(tokens))):
            t = tokens[idx]
            if t.text in ("if", "while", "for", "do", "switch", "case", "catch"):
                complexity += 1
            elif t.text in ("&&", "||", "?"):
                complexity += 1

        if complexity > _MAX_CYCLOMATIC_COMPLEXITY:
            smells.append(
                CodeSmell(
                    kind=SmellKind.CYCLOMATIC_COMPLEXITY,
                    severity=SmellSeverity.WARNING,
                    message=(
                        f"function '{region.name}' has cyclomatic complexity {complexity} "
                        f"(max {_MAX_CYCLOMATIC_COMPLEXITY}) — split into smaller functions"
                    ),
                    line=tokens[start].line,
                    column=0,
                )
            )

    return smells


def _check_mixed_abstraction(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Detect functions that mix different levels of abstraction.

    A function is flagged if it combines memory management (malloc/free)
    with I/O operations (printf/scanf/etc.) or string manipulation,
    suggesting it has too many responsibilities.
    """
    smells: list[CodeSmell] = []
    func_regions = _find_function_regions(tokens, lexer_type)

    for region in func_regions:
        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        body_tokens = tokens[start : end + 1] if end < len(tokens) else tokens[start:]
        body_text = " ".join(t.text for t in body_tokens)

        has_memory = any(name in body_text for name in _MEMORY_FUNCTIONS)
        has_io = any(name in body_text for name in _IO_FUNCTIONS)
        has_string = any(name in body_text for name in _STRING_FUNCTIONS)
        has_math = any(name in body_text for name in _MATH_FUNCTIONS)

        categories = sum([has_memory, has_io, has_string, has_math])

        if categories >= 3:
            smells.append(
                CodeSmell(
                    kind=SmellKind.MIXED_ABSTRACTION,
                    severity=SmellSeverity.INFO,
                    message=(
                        f"function '{region.name}' mixes {categories} different concerns "
                        "(memory, I/O, string, math) — split into focused functions"
                    ),
                    line=tokens[start].line,
                    column=0,
                )
            )

    return smells


def _check_todo_comments(all_tokens: list[_Token]) -> list[CodeSmell]:
    """Scan all tokens (including comments) for TODO/FIXME markers."""
    smells: list[CodeSmell] = []

    for tok in all_tokens:
        # Match single-line comments
        if tok.text.startswith("//"):
            match = _TODO_PATTERNS.search(tok.text)
            if match:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.TODO_COMMENT,
                        severity=SmellSeverity.INFO,
                        message=f"found '{match.group(1)}' in comment",
                        line=tok.line,
                        column=tok.column,
                    )
                )
        # Match multi-line comment start lines
        elif tok.text.startswith("/*") or tok.text.startswith("*"):
            match = _MULTI_COMMENT_TODO.search(tok.text)
            if match:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.TODO_COMMENT,
                        severity=SmellSeverity.INFO,
                        message=f"found '{match.group(1)}' in comment",
                        line=tok.line,
                        column=tok.column,
                    )
                )

    return smells


def _check_memory_leak_risk(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Track allocations and frees per function to detect leaks.

    FIXED: uses enumerate instead of tokens.index() which was buggy.
    """
    smells: list[CodeSmell] = []

    # Find function regions
    func_regions = _find_function_regions(tokens, lexer_type)

    for region in func_regions:
        # Track {var_name: allocation_line} for this function
        alloc_vars: dict[str, int] = {}

        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        for idx in range(start, min(end + 1, len(tokens))):
            tok = tokens[idx]

            if tok.text in _MALLOC_NAMES:
                var = _find_assigned_var(tokens, idx)
                if var:
                    alloc_vars[var] = tok.line
            elif tok.text == "free":
                # Look ahead for the variable name being freed
                for j in range(idx + 1, min(idx + 6, len(tokens))):
                    if tokens[j].text in alloc_vars:
                        del alloc_vars[tokens[j].text]
                        break
                    if tokens[j].text == ";":
                        break

        # Report any still-allocated variables at function end
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


def _find_function_regions(tokens: list[_Token], lexer_type: type) -> list[_FunctionRegion]:
    """Find all function definition bodies in the token stream."""
    regions: list[_FunctionRegion] = []
    brace_depth = 0
    in_function = False
    func_name = ""
    func_start = 0
    open_brace = None

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
            if not in_function and func_name:
                open_brace = i
                in_function = True
        elif tok.text == "}":
            brace_depth -= 1
            if in_function and brace_depth == 0:
                regions.append(_FunctionRegion(
                    name=func_name,
                    start_idx=func_start,
                    open_brace_idx=open_brace,
                    close_brace_idx=i,
                ))
                in_function = False
                open_brace = None
        elif (
            not in_function
            and tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
        ):
            name = tokens[i - 1].text
            # Skip function calls — check that there's no '=' or ',' or '(' before the name
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name not in _UNSAFE_FUNCTIONS and name not in _IO_FUNCTIONS:
                func_name = name
                func_start = tokens[i - 1].line if i >= 1 else 0

    return regions