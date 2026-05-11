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
_MAX_SWITCH_CASES = 8
_MAX_MESSAGE_CHAIN = 4
_DATA_CLUMP_MIN_OCCURRENCES = 3
_FEATURE_ENVY_RATIO = 0.6
_PRIMITIVE_SAME_TYPE_MIN = 3
_MIDDLE_MAN_RATIO = 0.5
_SHOTGUN_SURGERY_MIN_FUNCS = 5
_TEMP_FIELD_MIN_FUNCS = 4
_TEMP_FIELD_MAX_ACCESSORS = 1
_REFUSED_BEQUEST_MIN_RATIO = 0.3
_COMMENT_DENSITY_RATIO = 0.4
_COMMENT_DENSITY_MIN_LINES = 10
_PRIMITIVE_TYPES = frozenset(
    {"int", "char", "float", "double", "long", "short",
     "unsigned", "signed", "size_t", "ssize_t"}
)
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

        # --- Fowler smell checks ---
        smells.extend(_check_switch_statements(default_tokens, lexer_type))
        smells.extend(_check_message_chains(default_tokens, lexer_type))
        smells.extend(_check_primitive_obsession(default_tokens, lexer_type))
        smells.extend(_check_speculative_generality(default_tokens, lexer_type))
        smells.extend(_check_data_clumps(default_tokens, lexer_type))
        smells.extend(_check_feature_envy(default_tokens, lexer_type))
        smells.extend(_check_divergent_change(default_tokens, lexer_type))
        smells.extend(_check_shotgun_surgery(default_tokens, lexer_type))
        smells.extend(_check_temporary_field(default_tokens, lexer_type))
        smells.extend(_check_refused_bequest(default_tokens, lexer_type))
        smells.extend(_check_middle_man(default_tokens, lexer_type))

        # --- Comment-level checks (need all tokens including comments) ---
        smells.extend(_check_todo_comments(all_tokens))
        smells.extend(_check_comment_density(all_tokens, default_tokens, lexer_type))

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


# ---------------------------------------------------------------------------
# Shared helpers for Fowler smell checks
# ---------------------------------------------------------------------------


def _extract_param_names(tokens: list[_Token], region: _FunctionRegion, lexer_type: type) -> list[str]:
    """Extract parameter names from a function's signature."""
    # Search backward from open_brace_idx to find '('
    search_start = region.open_brace_idx if region.open_brace_idx is not None else min(region.start_idx, len(tokens) - 1)
    paren_idx = None
    for j in range(search_start, max(search_start - 30, -1), -1):
        if tokens[j].text == "(":
            paren_idx = j
            break
    if paren_idx is None:
        return []

    names: list[str] = []
    depth = 0
    last_ident: str | None = None
    for j in range(paren_idx + 1, min(paren_idx + 80, len(tokens))):
        t = tokens[j]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            if depth > 0:
                depth -= 1
            else:
                if last_ident is not None:
                    names.append(last_ident)
                break
        elif t.text == "," and depth == 0:
            if last_ident is not None:
                names.append(last_ident)
            last_ident = None
        elif depth == 0 and t.type == lexer_type.Identifier:
            last_ident = t.text

    return names


def _extract_function_param_types(tokens: list[_Token], open_paren_idx: int, lexer_type: type) -> list[str]:
    """Extract parameter type strings from a function signature."""
    type_keywords = {
        lexer_type.Int, lexer_type.Char, lexer_type.Float, lexer_type.Double,
        lexer_type.Long, lexer_type.Short, lexer_type.Signed, lexer_type.Unsigned,
        lexer_type.Void, lexer_type.Bool, lexer_type.Struct, lexer_type.Enum,
        lexer_type.Const, lexer_type.Volatile, lexer_type.Static,
        lexer_type.Identifier,
    }
    type_keywords = {t for t in type_keywords if t is not None}

    depth = 0
    params: list[str] = []
    current_tokens: list[str] = []

    for j in range(open_paren_idx + 1, min(open_paren_idx + 80, len(tokens))):
        t = tokens[j]
        if t.text == "(":
            depth += 1
            continue
        elif t.text == ")":
            depth -= 1
            if depth < 0:
                if current_tokens:
                    params.append(" ".join(current_tokens))
                break
        elif t.text == "," and depth == 0:
            if current_tokens:
                params.append(" ".join(current_tokens))
            current_tokens = []
        elif depth == 0:
            if t.type in type_keywords or t.text == "*":
                current_tokens.append(t.text)

    # Normalize: keep only base type (first 1-2 meaningful tokens)
    normalized: list[str] = []
    for p in params:
        parts = p.split()
        # Strip const/volatile/static qualifiers
        parts = [x for x in parts if x not in ("const", "volatile", "static", "restrict")]
        if not parts:
            continue
        # For "struct Name" keep both; for "unsigned int" keep both
        if len(parts) >= 2 and parts[0] in ("struct", "enum", "unsigned", "signed"):
            base = " ".join(parts[:2])
        else:
            base = parts[0]
        normalized.append(base)

    return normalized


def _collect_struct_definitions(tokens: list[_Token], lexer_type: type) -> dict[str, list[str]]:
    """Find struct definitions at file scope and collect their field names."""
    result: dict[str, list[str]] = {}
    brace_depth = 0
    in_struct = False
    struct_name = ""
    struct_brace_start = -1
    inner_depth = 0

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            if brace_depth == 0 and in_struct:
                struct_brace_start = i
                inner_depth = 0
            brace_depth += 1
            if in_struct and i != struct_brace_start:
                inner_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
            if in_struct and brace_depth == 0:
                in_struct = False
            elif in_struct and inner_depth > 0:
                inner_depth -= 1
        elif brace_depth == 0 and tok.text == "struct":
            # Look ahead for struct name
            if i + 1 < len(tokens) and tokens[i + 1].type == lexer_type.Identifier:
                # Check if this is a definition (followed by { eventually)
                for j in range(i + 2, min(i + 5, len(tokens))):
                    if tokens[j].text == "{":
                        struct_name = tokens[i + 1].text
                        in_struct = True
                        break
                    if tokens[j].text == ";":
                        break
        elif in_struct and inner_depth == 0 and tok.type == lexer_type.Identifier:
            # Collect field names: identifier inside struct body at depth 0
            # Check if it's followed by ';' or '[' (field declaration)
            if struct_brace_start >= 0:
                # Only add if it looks like a field (preceded by a type-like token)
                if i > struct_brace_start:
                    prev = tokens[i - 1]
                    if prev.type in {
                        lexer_type.Int, lexer_type.Char, lexer_type.Float, lexer_type.Double,
                        lexer_type.Long, lexer_type.Short, lexer_type.Signed, lexer_type.Unsigned,
                        lexer_type.Void, lexer_type.Bool, lexer_type.Struct, lexer_type.Identifier,
                    } or prev.text == "*":
                        if i + 1 < len(tokens) and tokens[i + 1].text in (";", "[", "="):
                            result.setdefault(struct_name, []).append(tok.text)

    return result


def _extract_struct_params(tokens: list[_Token], region: _FunctionRegion, lexer_type: type) -> list[tuple[str, str]]:
    """Extract (struct_type_name, param_name) from function signature."""
    # Search backward from open_brace_idx to find '('
    search_start = region.open_brace_idx if region.open_brace_idx is not None else min(region.start_idx, len(tokens) - 1)
    paren_idx = None
    for j in range(search_start, max(search_start - 50, -1), -1):
        if tokens[j].text == "(":
            paren_idx = j
            break
    if paren_idx is None:
        return []

    results: list[tuple[str, str]] = []
    depth = 0
    # Look for pattern: 'struct' Identifier '*'? Identifier
    i = paren_idx + 1
    end = min(paren_idx + 80, len(tokens))
    # Find matching close paren
    while i < end:
        if tokens[i].text == "(":
            depth += 1
            i += 1
            continue
        if tokens[i].text == ")":
            if depth == 0:
                break
            depth -= 1
            i += 1
            continue
        if depth == 0 and tokens[i].text == "struct":
            # Look ahead: struct Name * paramName
            if i + 3 < end and tokens[i + 1].type == lexer_type.Identifier:
                struct_name = tokens[i + 1].text
                j = i + 2
                # Skip stars
                while j < end and tokens[j].text == "*":
                    j += 1
                if j < end and tokens[j].type == lexer_type.Identifier:
                    results.append((struct_name, tokens[j].text))
                    i = j + 1
                    continue
        i += 1

    return results


# ---------------------------------------------------------------------------
# Fowler smell checks
# ---------------------------------------------------------------------------


def _check_switch_statements(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag switch statements with too many case labels."""
    switch_type = getattr(lexer_type, "Switch", None)
    case_type = getattr(lexer_type, "Case", None)
    default_type = getattr(lexer_type, "Default", None)
    if switch_type is None or case_type is None:
        return []

    smells: list[CodeSmell] = []
    for i, tok in enumerate(tokens):
        if tok.type != switch_type:
            continue
        # Find the opening brace after the switch expression
        paren_end = None
        depth = 0
        for j in range(i + 1, min(i + 20, len(tokens))):
            if tokens[j].text == "(":
                depth += 1
            elif tokens[j].text == ")":
                depth -= 1
                if depth == 0:
                    paren_end = j
                    break
        if paren_end is None:
            continue

        brace_start = None
        for j in range(paren_end + 1, min(paren_end + 5, len(tokens))):
            if tokens[j].text == "{":
                brace_start = j
                break
        if brace_start is None:
            continue

        # Count cases at depth 1 within the switch body
        case_count = 0
        switch_depth = 0
        for j in range(brace_start, min(brace_start + 500, len(tokens))):
            t = tokens[j]
            if t.text == "{":
                switch_depth += 1
            elif t.text == "}":
                switch_depth -= 1
                if switch_depth == 0:
                    break
            elif switch_depth == 1:
                if t.type == case_type or t.type == default_type:
                    case_count += 1

        if case_count > _MAX_SWITCH_CASES:
            smells.append(
                CodeSmell(
                    kind=SmellKind.SWITCH_STATEMENTS,
                    severity=SmellSeverity.WARNING,
                    message=f"switch has {case_count} cases (max {_MAX_SWITCH_CASES}) — consider polymorphism or table lookup",
                    line=tok.line,
                    column=tok.column,
                )
            )

    return smells


def _check_message_chains(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag long chains of -> and . accesses."""
    arrow_type = getattr(lexer_type, "Arrow", None)
    dot_type = getattr(lexer_type, "Dot", None)
    if arrow_type is None and dot_type is None:
        return []

    smells: list[CodeSmell] = []
    i = 0
    while i < len(tokens):
        if tokens[i].type != lexer_type.Identifier:
            i += 1
            continue
        # Start tracking a potential chain
        chain_start = i
        chain_length = 0
        j = i + 1
        while j < len(tokens):
            if tokens[j].type in (arrow_type, dot_type):
                chain_length += 1
                j += 1
                # Expect an identifier after -> or .
                if j < len(tokens) and tokens[j].type == lexer_type.Identifier:
                    j += 1
                    # Skip function call arguments: identifier ( ... )
                    if j < len(tokens) and tokens[j].text == "(":
                        depth = 0
                        while j < len(tokens):
                            if tokens[j].text == "(":
                                depth += 1
                            elif tokens[j].text == ")":
                                depth -= 1
                                if depth == 0:
                                    j += 1
                                    break
                            j += 1
                    continue
                break
            else:
                break

        if chain_length >= _MAX_MESSAGE_CHAIN:
            smells.append(
                CodeSmell(
                    kind=SmellKind.MESSAGE_CHAINS,
                    severity=SmellSeverity.INFO,
                    message=f"chain of {chain_length} '->'/'.' accesses — consider Law of Demeter",
                    line=tokens[chain_start].line,
                    column=tokens[chain_start].column,
                )
            )
        i = j

    return smells


def _check_data_clumps(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag repeated parameter type pairs across multiple functions."""
    brace_depth = 0
    paren_depth = 0
    pair_occurrences: dict[tuple[str, str], list[tuple[str, int]]] = {}

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
        elif tok.text == "(":
            paren_depth += 1
        elif tok.text == ")":
            paren_depth = max(paren_depth - 1, 0)

        if brace_depth != 0:
            continue

        if (
            tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
            and paren_depth == 1
        ):
            name = tokens[i - 1].text
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name in _UNSAFE_FUNCTIONS or name in _IO_FUNCTIONS or name in _MALLOC_NAMES:
                continue

            param_types = _extract_function_param_types(tokens, i, lexer_type)
            # Generate sorted type pairs
            if len(param_types) < 2:
                continue
            for a in range(len(param_types)):
                for b in range(a + 1, len(param_types)):
                    pair = tuple(sorted([param_types[a], param_types[b]]))
                    pair_occurrences.setdefault(pair, []).append((name, tok.line))

    smells: list[CodeSmell] = []
    seen: set[tuple[str, str]] = {}
    for pair, occurrences in pair_occurrences.items():
        if len(occurrences) >= _DATA_CLUMP_MIN_OCCURRENCES:
            key = (pair[0], pair[1])
            if key not in seen:
                seen[key] = key
                func_names = ", ".join(o[0] for o in occurrences)
                smells.append(
                    CodeSmell(
                        kind=SmellKind.DATA_CLUMPS,
                        severity=SmellSeverity.INFO,
                        message=(
                            f"parameter types '{pair[0]}' and '{pair[1]}' appear together "
                            f"in {len(occurrences)} functions ({func_names}) — consider grouping into a struct"
                        ),
                        line=occurrences[0][1],
                        column=0,
                    )
                )

    return smells


def _check_feature_envy(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag functions that primarily access one struct pointer parameter's fields."""
    func_regions = _find_function_regions(tokens, lexer_type)
    smells: list[CodeSmell] = []

    for region in func_regions:
        param_names = _extract_param_names(tokens, region, lexer_type)
        if not param_names:
            continue

        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        access_counts: dict[str, int] = {n: 0 for n in param_names}
        for idx in range(start, min(end + 1, len(tokens))):
            if tokens[idx].text == "->" and idx > 0:
                prev = tokens[idx - 1]
                if prev.type == lexer_type.Identifier and prev.text in access_counts:
                    access_counts[prev.text] += 1

        total = sum(access_counts.values())
        if total < 3:
            continue

        for name, count in access_counts.items():
            if count > 0 and count / total >= _FEATURE_ENVY_RATIO:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.FEATURE_ENVY,
                        severity=SmellSeverity.INFO,
                        message=(
                            f"function '{region.name}' primarily accesses '{name}' fields "
                            f"({count}/{total} '->' accesses) — consider moving to {name}'s module"
                        ),
                        line=tokens[start].line,
                        column=0,
                    )
                )

    return smells


def _check_primitive_obsession(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag functions with many parameters of the same primitive type."""
    brace_depth = 0
    paren_depth = 0
    smells: list[CodeSmell] = []

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
        elif tok.text == "(":
            paren_depth += 1
        elif tok.text == ")":
            paren_depth = max(paren_depth - 1, 0)

        if brace_depth != 0:
            continue

        if (
            tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
            and paren_depth == 1
        ):
            name = tokens[i - 1].text
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name in _UNSAFE_FUNCTIONS or name in _IO_FUNCTIONS or name in _MALLOC_NAMES:
                continue

            param_types = _extract_function_param_types(tokens, i, lexer_type)
            type_counts: dict[str, int] = {}
            for pt in param_types:
                # Normalize for comparison
                base = pt.split()[0] if pt.startswith(("unsigned", "signed")) else pt
                if base in _PRIMITIVE_TYPES or pt in _PRIMITIVE_TYPES:
                    key = pt
                    type_counts[key] = type_counts.get(key, 0) + 1

            for type_str, count in type_counts.items():
                if type_str == "void *" or type_str.startswith("void"):
                    continue
                if count >= _PRIMITIVE_SAME_TYPE_MIN:
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.PRIMITIVE_OBSESSION,
                            severity=SmellSeverity.INFO,
                            message=(
                                f"function '{name}' has {count} '{type_str}' parameters "
                                f"— consider grouping related values into a struct"
                            ),
                            line=tok.line,
                            column=tok.column,
                        )
                    )

    return smells


def _check_middle_man(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag files where most functions are trivial delegations."""
    func_regions = _find_function_regions(tokens, lexer_type)
    if len(func_regions) < 2:
        return []

    delegation_count = 0
    for region in func_regions:
        if region.open_brace_idx is None or region.close_brace_idx is None:
            continue
        start = region.open_brace_idx + 1
        end = region.close_brace_idx

        call_count = 0
        control_flow_count = 0
        for idx in range(start, end):
            t = tokens[idx]
            if t.text in ("if", "for", "while", "switch", "do"):
                control_flow_count += 1
            elif t.type == lexer_type.Identifier and idx + 1 < len(tokens) and tokens[idx + 1].text == "(":
                call_count += 1

        if call_count == 1 and control_flow_count == 0:
            delegation_count += 1

    if delegation_count / len(func_regions) >= _MIDDLE_MAN_RATIO:
        return [
            CodeSmell(
                kind=SmellKind.MIDDLE_MAN,
                severity=SmellSeverity.INFO,
                message=(
                    f"{delegation_count}/{len(func_regions)} functions are trivial delegations "
                    "— consider removing middle-man wrappers"
                ),
                line=1,
                column=0,
            )
        ]
    return []


def _check_speculative_generality(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag unused function parameters and unused static functions."""
    smells: list[CodeSmell] = []
    func_regions = _find_function_regions(tokens, lexer_type)

    # Sub-check A: unused parameters
    for region in func_regions:
        param_names = _extract_param_names(tokens, region, lexer_type)
        if not param_names:
            continue

        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        body_idents: set[str] = set()
        for idx in range(start, min(end + 1, len(tokens))):
            if tokens[idx].type == lexer_type.Identifier:
                body_idents.add(tokens[idx].text)

        for name in param_names:
            if name not in body_idents:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.SPECULATIVE_GENERALITY,
                        severity=SmellSeverity.WARNING,
                        message=f"unused parameter '{name}' in function '{region.name}'",
                        line=tokens[start].line,
                        column=0,
                    )
                )

    # Sub-check B: unused static functions
    static_funcs: list[tuple[str, int, _FunctionRegion]] = []
    for region in func_regions:
        # Find the '(' token that starts the function signature
        search_start = region.open_brace_idx if region.open_brace_idx is not None else min(region.start_idx, len(tokens) - 1)
        paren_idx = None
        for j in range(search_start, max(search_start - 30, -1), -1):
            if tokens[j].text == "(":
                paren_idx = j
                break
        if paren_idx is None:
            continue

        # Walk backward from '(' to find 'static'
        found_static = False
        for j in range(paren_idx - 1, max(paren_idx - 15, -1), -1):
            if tokens[j].type == getattr(lexer_type, "Static", -1):
                found_static = True
                break
            if tokens[j].text == ";":
                break
        if found_static:
            static_funcs.append((region.name, tokens[paren_idx].line, region))

    for func_name, func_line, region in static_funcs:
        # Count occurrences of the function name in the entire file
        total_refs = sum(
            1 for t in tokens if t.type == lexer_type.Identifier and t.text == func_name
        )
        # The name appears in the definition (at least once in the signature).
        # If it appears only once (definition), it's unused.
        if total_refs <= 1:
            smells.append(
                CodeSmell(
                    kind=SmellKind.SPECULATIVE_GENERALITY,
                    severity=SmellSeverity.WARNING,
                    message=f"static function '{func_name}' is defined but never called",
                    line=func_line,
                    column=0,
                )
            )

    return smells


def _check_divergent_change(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag structs where different functions access completely disjoint field subsets."""
    func_regions = _find_function_regions(tokens, lexer_type)
    struct_accesses: dict[str, list[tuple[str, set[str]]]] = {}

    for region in func_regions:
        struct_params = _extract_struct_params(tokens, region, lexer_type)
        if not struct_params:
            continue

        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        for struct_name, param_name in struct_params:
            fields: set[str] = set()
            for idx in range(start, min(end + 1, len(tokens))):
                if (
                    tokens[idx].text == "->"
                    and idx > 0
                    and tokens[idx - 1].text == param_name
                    and idx + 1 < len(tokens)
                    and tokens[idx + 1].type == lexer_type.Identifier
                ):
                    fields.add(tokens[idx + 1].text)
            struct_accesses.setdefault(struct_name, []).append((region.name, fields))

    smells: list[CodeSmell] = []
    for struct_name, func_list in struct_accesses.items():
        if len(func_list) < 2:
            continue
        for a in range(len(func_list)):
            for b in range(a + 1, len(func_list)):
                _, fields_a = func_list[a]
                _, fields_b = func_list[b]
                if len(fields_a) >= 2 and len(fields_b) >= 2 and not (fields_a & fields_b):
                    smells.append(
                        CodeSmell(
                            kind=SmellKind.DIVERGENT_CHANGE,
                            severity=SmellSeverity.WARNING,
                            message=(
                                f"struct '{struct_name}' accessed with disjoint field sets — "
                                f"'{func_list[a][0]}' uses {sorted(fields_a)}, "
                                f"'{func_list[b][0]}' uses {sorted(fields_b)} — "
                                "consider splitting the struct"
                            ),
                            line=1,
                            column=0,
                        )
                    )

    return smells


def _check_shotgun_surgery(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag struct types that appear in many function signatures."""
    brace_depth = 0
    paren_depth = 0
    struct_usage: dict[str, list[tuple[str, int]]] = {}

    for i, tok in enumerate(tokens):
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
        elif tok.text == "(":
            paren_depth += 1
        elif tok.text == ")":
            paren_depth = max(paren_depth - 1, 0)

        if brace_depth != 0:
            continue

        if (
            tok.text == "("
            and i >= 1
            and tokens[i - 1].type == lexer_type.Identifier
            and paren_depth == 1
        ):
            name = tokens[i - 1].text
            if i >= 2 and tokens[i - 2].text in ("=", ",", "(", "return", "&", "|", "^", "+", "-", "*", "/", "!"):
                continue
            if name in _UNSAFE_FUNCTIONS or name in _IO_FUNCTIONS or name in _MALLOC_NAMES:
                continue

            param_types = _extract_function_param_types(tokens, i, lexer_type)
            for pt in param_types:
                if pt.startswith("struct "):
                    parts = pt.split()
                    if len(parts) >= 2:
                        sname = parts[1]
                        struct_usage.setdefault(sname, []).append((name, tok.line))

    smells: list[CodeSmell] = []
    for sname, usages in struct_usage.items():
        if len(usages) >= _SHOTGUN_SURGERY_MIN_FUNCS:
            smells.append(
                CodeSmell(
                    kind=SmellKind.SHOTGUN_SURGERY,
                    severity=SmellSeverity.WARNING,
                    message=(
                        f"struct '{sname}' is passed to {len(usages)} functions — "
                        "changes may require widespread modifications"
                    ),
                    line=usages[0][1],
                    column=0,
                )
            )

    return smells


def _check_temporary_field(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag struct fields that are rarely accessed relative to other fields."""
    struct_defs = _collect_struct_definitions(tokens, lexer_type)
    if not struct_defs:
        return []

    func_regions = _find_function_regions(tokens, lexer_type)
    # Track which fields each function accesses per struct type
    struct_field_accesses: dict[str, list[tuple[str, set[str]]]] = {}

    for region in func_regions:
        struct_params = _extract_struct_params(tokens, region, lexer_type)
        if not struct_params:
            continue

        start = region.open_brace_idx if region.open_brace_idx is not None else region.start_idx
        end = region.close_brace_idx if region.close_brace_idx is not None else len(tokens)

        for struct_name, param_name in struct_params:
            if struct_name not in struct_defs:
                continue
            accessed: set[str] = set()
            for idx in range(start, min(end + 1, len(tokens))):
                if (
                    tokens[idx].text == "->"
                    and idx > 0
                    and tokens[idx - 1].text == param_name
                    and idx + 1 < len(tokens)
                    and tokens[idx + 1].type == lexer_type.Identifier
                ):
                    accessed.add(tokens[idx + 1].text)
            struct_field_accesses.setdefault(struct_name, []).append((region.name, accessed))

    smells: list[CodeSmell] = []
    for struct_name, fields in struct_defs.items():
        func_list = struct_field_accesses.get(struct_name, [])
        if len(func_list) < _TEMP_FIELD_MIN_FUNCS:
            continue

        field_accessor_count: dict[str, int] = {f: 0 for f in fields}
        for _, accessed in func_list:
            for f in accessed:
                if f in field_accessor_count:
                    field_accessor_count[f] += 1

        for field_name, accessor_count in field_accessor_count.items():
            if accessor_count <= _TEMP_FIELD_MAX_ACCESSORS:
                smells.append(
                    CodeSmell(
                        kind=SmellKind.TEMPORARY_FIELD,
                        severity=SmellSeverity.INFO,
                        message=(
                            f"struct '{struct_name}' field '{field_name}' accessed by "
                            f"{accessor_count}/{len(func_list)} functions — "
                            "consider removing or restructuring"
                        ),
                        line=1,
                        column=0,
                    )
                )

    return smells


def _check_refused_bequest(tokens: list[_Token], lexer_type: type) -> list[CodeSmell]:
    """Flag structs that embed another struct but rarely use the embedded fields."""
    struct_defs = _collect_struct_definitions(tokens, lexer_type)
    if not struct_defs:
        return []

    # Find embedded structs: struct Child { struct Base base; ... }
    brace_depth = 0
    in_struct = False
    struct_name = ""
    embedded: list[tuple[str, str, str]] = []  # (child_name, base_name, field_name)

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.text == "{":
            brace_depth += 1
        elif tok.text == "}":
            brace_depth -= 1
            if brace_depth == 0:
                in_struct = False
        elif brace_depth == 0 and tok.text == "struct" and in_struct is False:
            # Check for struct definition
            if i + 1 < len(tokens) and tokens[i + 1].type == lexer_type.Identifier:
                for j in range(i + 2, min(i + 5, len(tokens))):
                    if tokens[j].text == "{":
                        struct_name = tokens[i + 1].text
                        in_struct = True
                        break
                    if tokens[j].text == ";":
                        break
        elif in_struct and brace_depth == 1 and tok.text == "struct":
            # Look for embedded struct: struct Base field_name;
            if i + 2 < len(tokens) and tokens[i + 1].type == lexer_type.Identifier:
                base_name = tokens[i + 1].text
                # Skip pointer markers
                j = i + 2
                if j < len(tokens) and tokens[j].text == "*":
                    i += 1
                    continue  # Pointer embedding, skip
                if j < len(tokens) and tokens[j].type == lexer_type.Identifier:
                    field_name = tokens[j].text
                    if base_name in struct_defs:
                        embedded.append((struct_name, base_name, field_name))
        i += 1

    smells: list[CodeSmell] = []
    for child_name, base_name, field_name in embedded:
        base_fields = struct_defs.get(base_name, [])
        if not base_fields:
            continue

        # Count how many base fields are accessed via field_name->
        used_fields: set[str] = set()
        for idx, tok2 in enumerate(tokens):
            if (
                tok2.text == "->"
                and idx > 0
                and tokens[idx - 1].text == field_name
                and idx + 1 < len(tokens)
                and tokens[idx + 1].type == lexer_type.Identifier
            ):
                if tokens[idx + 1].text in base_fields:
                    used_fields.add(tokens[idx + 1].text)

        if not base_fields:
            continue
        ratio = len(used_fields) / len(base_fields)
        if ratio < _REFUSED_BEQUEST_MIN_RATIO:
            smells.append(
                CodeSmell(
                    kind=SmellKind.REFUSED_BEQUEST,
                    severity=SmellSeverity.INFO,
                    message=(
                        f"struct '{child_name}' embeds '{base_name}' via '{field_name}' "
                        f"but only uses {len(used_fields)}/{len(base_fields)} of its fields "
                        f"({ratio:.0%}) — consider composition instead of embedding"
                    ),
                    line=1,
                    column=0,
                )
            )

    return smells


def _check_comment_density(
    all_tokens: list[_Token], default_tokens: list[_Token], lexer_type: type
) -> list[CodeSmell]:
    """Flag functions where comments dominate the code."""
    func_regions = _find_function_regions(default_tokens, lexer_type)
    block_comment_type = getattr(lexer_type, "BlockComment", None)
    line_comment_type = getattr(lexer_type, "LineComment", None)

    # Build a set of comment lines from all_tokens
    comment_lines: set[int] = set()
    for tok in all_tokens:
        if tok.type == block_comment_type:
            # Block comments may span multiple lines
            for line in range(tok.line, tok.line + tok.text.count("\n") + 1):
                comment_lines.add(line)
        elif tok.type == line_comment_type:
            comment_lines.add(tok.line)

    smells: list[CodeSmell] = []
    for region in func_regions:
        if region.open_brace_idx is None or region.close_brace_idx is None:
            continue
        start_line = default_tokens[region.open_brace_idx].line
        end_line = default_tokens[region.close_brace_idx].line
        total_lines = end_line - start_line + 1
        if total_lines < _COMMENT_DENSITY_MIN_LINES:
            continue

        func_comment_lines = sum(
            1 for line in comment_lines if start_line <= line <= end_line
        )
        if total_lines > 0 and func_comment_lines / total_lines > _COMMENT_DENSITY_RATIO:
            smells.append(
                CodeSmell(
                    kind=SmellKind.COMMENT_DENSITY,
                    severity=SmellSeverity.INFO,
                    message=(
                        f"function '{region.name}' has {func_comment_lines} comment lines "
                        f"out of {total_lines} ({func_comment_lines / total_lines:.0%}) "
                        "— consider making the code self-documenting"
                    ),
                    line=start_line,
                    column=0,
                )
            )

    return smells