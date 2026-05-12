"""Fuzz tests for the C code smell scanner using Hypothesis."""

import string

from hypothesis import given, settings, strategies as st
import pytest

from clenz.domain.errors import GeneratedParserNotAvailableError
from clenz.domain.model import SourceUnit, SourceUnitId
from clenz.infrastructure.linting.smell_scanner import AntlrCSmellScanner

# A list of common C keywords, symbols, and standard library functions to build C-like structures
C_KEYWORDS_AND_SYMBOLS = [
    "int", "char", "float", "double", "void", "if", "else", "while", "for", "do",
    "return", "struct", "switch", "case", "default", "break", "continue",
    "malloc", "free", "calloc", "realloc", "NULL", "const", "static",
    "extern", "typedef", "enum", "union", "{", "}", "(", ")", "[", "]", ";",
    ",", ".", "->", "=", "==", "!=", "<", ">", "+", "-", "*", "/", "!", "&&", "||",
    "printf", "scanf", "fopen", "fclose", "gets", "strcpy", "sprintf",
    "// comment", "/* comment */"
]

@given(st.text())
@settings(max_examples=100)
def test_fuzz_scanner_does_not_crash_on_random_text(source_text: str) -> None:
    """Ensure the scanner does not crash on completely random text input."""
    scanner = AntlrCSmellScanner()
    unit = SourceUnit(
        identifier=SourceUnitId("fuzz_random.c"),
        location="fuzz_random.c",
        content=source_text,
    )
    try:
        scanner.scan(unit)
    except GeneratedParserNotAvailableError:
        pytest.skip("generated ANTLR parser not available")
    # If the scanner crashes with IndexError, TypeError, etc., Hypothesis will catch and report it

@given(
    st.lists(
        st.sampled_from(C_KEYWORDS_AND_SYMBOLS) | st.text(alphabet=string.ascii_letters, min_size=1, max_size=8),
        max_size=200
    ).map(lambda l: " ".join(l))
)
@settings(max_examples=200)
def test_fuzz_scanner_does_not_crash_on_c_like_input(source_text: str) -> None:
    """Ensure the scanner does not crash on random sequences of C-like tokens."""
    scanner = AntlrCSmellScanner()
    unit = SourceUnit(
        identifier=SourceUnitId("fuzz_c_like.c"),
        location="fuzz_c_like.c",
        content=source_text,
    )
    try:
        scanner.scan(unit)
    except GeneratedParserNotAvailableError:
        pytest.skip("generated ANTLR parser not available")
