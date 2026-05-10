"""Tests for the token-based C code smell scanner."""

from __future__ import annotations

import pytest

from clenz.domain.errors import GeneratedParserNotAvailableError
from clenz.domain.model import SourceUnit, SourceUnitId
from clenz.domain.smells import CodeSmell, SmellKind, SmellSeverity
from clenz.infrastructure.linting.smell_scanner import AntlrCSmellScanner


def _scan(source_text: str) -> list[CodeSmell]:
    """Helper: scan a C source string and return sorted smells."""
    source = SourceUnit(
        identifier=SourceUnitId("test.c"),
        location="test.c",
        content=source_text.strip(),
    )
    scanner = AntlrCSmellScanner()
    try:
        report = scanner.scan(source)
    except GeneratedParserNotAvailableError:
        pytest.skip("generated ANTLR parser not available")
    return sorted(report.smells, key=lambda s: (s.line, s.column))


def _kinds(smells: list[CodeSmell]) -> set[str]:
    return {s.kind.value for s in smells}


# ---------------------------------------------------------------------------
# Unsafe functions
# ---------------------------------------------------------------------------


class TestUnsafeFunction:
    def test_detects_gets(self) -> None:
        smells = _scan("""
void read() {
    char buf[100];
    gets(buf);
}
""")
        assert SmellKind.UNSAFE_FUNCTION in _kinds(smells)

    def test_detects_strcpy(self) -> None:
        smells = _scan("""
void copy(char *dst, const char *src) {
    strcpy(dst, src);
}
""")
        assert SmellKind.UNSAFE_FUNCTION in _kinds(smells)

    def test_detects_sprintf(self) -> None:
        smells = _scan("""
void fmt(char *buf) {
    sprintf(buf, "%s", "hello");
}
""")
        assert SmellKind.UNSAFE_FUNCTION in _kinds(smells)

    def test_detects_multiple_unsafe(self) -> None:
        smells = _scan("""
void bad() {
    char buf[100];
    gets(buf);
    strcpy(buf, "a");
    sprintf(buf, "%d", 1);
}
""")
        kinds = _kinds(smells)
        assert SmellKind.UNSAFE_FUNCTION in kinds
        # Gets + strcpy + sprintf = 3 instances
        unsafe = [s for s in smells if s.kind == SmellKind.UNSAFE_FUNCTION]
        assert len(unsafe) >= 3

    def test_safe_functions_not_flagged(self) -> None:
        smells = _scan("""
#include <string.h>
void safe() {
    char buf[100];
    strncpy(buf, "a", 10);
    snprintf(buf, 100, "%d", 1);
}
""")
        unsafe = [s for s in smells if s.kind == SmellKind.UNSAFE_FUNCTION]
        assert unsafe == []


# ---------------------------------------------------------------------------
# Unchecked malloc
# ---------------------------------------------------------------------------


class TestUncheckedMalloc:
    def test_detects_unchecked_malloc(self) -> None:
        smells = _scan("""
void leak() {
    int *p = malloc(sizeof(int) * 10);
    // no free, no null check
    *p = 42;
}
""")
        assert SmellKind.UNCHECKED_MALLOC in _kinds(smells)

    def test_malloc_with_null_check_passes(self) -> None:
        smells = _scan("""
void ok() {
    int *p = malloc(sizeof(int) * 10);
    if (!p) return;
    *p = 42;
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_MALLOC]
        assert unchecked == []

    def test_malloc_with_paren_check_passes(self) -> None:
        smells = _scan("""
void ok() {
    int *p = malloc(sizeof(int) * 10);
    if (p != NULL) {
        *p = 42;
    }
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_MALLOC]
        assert unchecked == []

    def test_calloc_detected(self) -> None:
        smells = _scan("""
void leak() {
    int *p = calloc(10, sizeof(int));
    *p = 42;
}
""")
        assert SmellKind.UNCHECKED_MALLOC in _kinds(smells)

    def test_realloc_detected(self) -> None:
        smells = _scan("""
void leak() {
    int *p = realloc(NULL, sizeof(int) * 10);
    *p = 42;
}
""")
        assert SmellKind.UNCHECKED_MALLOC in _kinds(smells)

    def test_multiple_mallocs_unchecked(self) -> None:
        """Each unchecked malloc should produce its own smell (regression for tokens.index bug)."""
        smells = _scan("""
void leak() {
    int *a = malloc(sizeof(int) * 10);
    *a = 1;
    int *b = malloc(sizeof(int) * 20);
    *b = 2;
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_MALLOC]
        assert len(unchecked) >= 2, f"expected >=2 unchecked malloc smells, got {len(unchecked)}: {unchecked}"


# ---------------------------------------------------------------------------
# Unchecked return value
# ---------------------------------------------------------------------------


class TestUncheckedReturn:
    def test_detects_unchecked_fopen(self) -> None:
        smells = _scan("""
void open_file() {
    FILE *f = fopen("test.txt", "r");
    // no check
    fprintf(f, "hello");
}
""")
        assert SmellKind.UNCHECKED_RETURN in _kinds(smells)

    def scanf_without_check(self) -> None:
        smells = _scan("""
void read_input() {
    int x;
    scanf("%d", &x);
}
""")
        assert SmellKind.UNCHECKED_RETURN in _kinds(smells)

    def test_checked_fopen_passes(self) -> None:
        smells = _scan("""
void open_file() {
    FILE *f = fopen("test.txt", "r");
    if (f == NULL) return;
    fprintf(f, "hello");
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_RETURN]
        assert unchecked == []

    def test_printf_not_flagged_as_unchecked(self) -> None:
        """printf return value is rarely checked — only flag file I/O."""
        smells = _scan("""
void greet() {
    printf("hello");
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_RETURN]
        assert unchecked == []


# ---------------------------------------------------------------------------
# Magic numbers
# ---------------------------------------------------------------------------


class TestMagicNumber:
    def test_detects_magic_number(self) -> None:
        smells = _scan("""
int calc() {
    return 42 * 100;
}
""")
        assert SmellKind.MAGIC_NUMBER in _kinds(smells)

    def test_ignores_zero(self) -> None:
        smells = _scan("""
int zero() {
    return 0;
}
""")
        magic = [s for s in smells if s.kind == SmellKind.MAGIC_NUMBER]
        assert magic == []

    def test_ignores_one(self) -> None:
        smells = _scan("""
int one() {
    return 1;
}
""")
        magic = [s for s in smells if s.kind == SmellKind.MAGIC_NUMBER]
        assert magic == []

    def test_ignores_hex(self) -> None:
        smells = _scan("""
int mask() {
    return 0xFF;
}
""")
        magic = [s for s in smells if s.kind == SmellKind.MAGIC_NUMBER]
        assert magic == []

    def test_ignores_NULL(self) -> None:
        smells = _scan("""
void null_check() {
    int *p = NULL;
}
""")
        magic = [s for s in smells if s.kind == SmellKind.MAGIC_NUMBER]
        assert magic == []


# ---------------------------------------------------------------------------
# Short names
# ---------------------------------------------------------------------------


class TestShortName:
    def test_detects_short_name(self) -> None:
        smells = _scan("""
int calc(int ab) {
    int cd = ab + 1;
    return cd;
}
""")
        assert SmellKind.SHORT_NAME in _kinds(smells)

    def test_allowed_short_names_pass(self) -> None:
        """i, j, k, n, x, y, z are allowed in loops/math."""
        smells = _scan("""
int sum(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += i;
    }
    return total;
}
""")
        short = [s for s in smells if s.kind == SmellKind.SHORT_NAME]
        assert short == []


# ---------------------------------------------------------------------------
# Uninitialized variable
# ---------------------------------------------------------------------------


class TestUninitializedVar:
    def test_detects_uninitialized_int(self) -> None:
        smells = _scan("""
void bad() {
    int x;
    printf("%d", x);
}
""")
        assert SmellKind.UNINITIALIZED_VAR in _kinds(smells)

    def test_initialized_passes(self) -> None:
        smells = _scan("""
void ok() {
    int x = 0;
}
""")
        uninit = [s for s in smells if s.kind == SmellKind.UNINITIALIZED_VAR]
        assert uninit == []


# ---------------------------------------------------------------------------
# Global variable
# ---------------------------------------------------------------------------


class TestGlobalVariable:
    def test_detects_global_var(self) -> None:
        smells = _scan("""
int global_count = 0;

void increment() {
    global_count++;
}
""")
        assert SmellKind.GLOBAL_VARIABLE in _kinds(smells)

    def test_static_global_flagged(self) -> None:
        smells = _scan("""
static int file_scope = 0;
""")
        assert SmellKind.GLOBAL_VARIABLE in _kinds(smells)

    def test_extern_passes(self) -> None:
        """extern declarations are declarations, not definitions."""
        smells = _scan("""
extern int external_var;
""")
        globals_ = [s for s in smells if s.kind == SmellKind.GLOBAL_VARIABLE]
        assert globals_ == []

    def test_within_function_not_flagged(self) -> None:
        smells = _scan("""
void local() {
    int local_var = 0;
}
""")
        globals_ = [s for s in smells if s.kind == SmellKind.GLOBAL_VARIABLE]
        assert globals_ == []


# ---------------------------------------------------------------------------
# Long function
# ---------------------------------------------------------------------------


class TestLongFunction:
    def test_detects_long_function(self) -> None:
        """A function with >60 lines between braces should be flagged."""
        body_lines = "\n".join(f"    int x{i} = {i};" for i in range(65))
        source = f"""
void long_func() {{
{body_lines}
}}
"""
        smells = _scan(source)
        assert SmellKind.LONG_FUNCTION in _kinds(smells)

    def test_short_function_passes(self) -> None:
        smells = _scan("""
void short() {
    int x = 1;
    return x;
}
""")
        long_ = [s for s in smells if s.kind == SmellKind.LONG_FUNCTION]
        assert long_ == []


# ---------------------------------------------------------------------------
# Missing const
# ---------------------------------------------------------------------------


class TestMissingConst:
    def test_detects_missing_const_in_param(self) -> None:
        smells = _scan("""
void copy(char *dst) {
}
""")
        assert SmellKind.MISSING_CONST in _kinds(smells)

    def test_const_param_passes(self) -> None:
        smells = _scan("""
void copy(const char *dst) {
}
""")
        missing = [s for s in smells if s.kind == SmellKind.MISSING_CONST]
        assert missing == []


# ---------------------------------------------------------------------------
# Deep nesting
# ---------------------------------------------------------------------------


class TestDeepNesting:
    def test_detects_deep_nesting(self) -> None:
        """5+ levels of nesting should be flagged."""
        source = """
void deeply_nested(int a, int b, int c, int d, int e) {
    if (a) {
        if (b) {
            if (c) {
                if (d) {
                    if (e) {
                        return 1;
                    }
                }
            }
        }
    }
}
"""
        smells = _scan(source)
        assert SmellKind.DEEP_NESTING in _kinds(smells)

    def test_shallow_nesting_passes(self) -> None:
        smells = _scan("""
void shallow() {
    if (1) {
        if (2) {
            if (3) {
                if (4) {
                    return 1;
                }
            }
        }
    }
}
""")
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert deep == []

    def test_multiple_deep_nested_blocks(self) -> None:
        """A function with multiple deeply nested blocks — count the deepest."""
        source = """
void multi_deep(int x) {
    if (x) {
        for (int i = 0; i < 10; i++) {
            while (x) {
                if (x > 0) {
                    if (x > 1) {
                        return;
                    }
                }
            }
        }
    }
}
"""
        smells = _scan(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) >= 1

    def test_deep_nesting_reports_correct_line(self) -> None:
        source = """
void deep() {
    if (1) {
        if (2) {
            if (3) {
                if (4) {
                    if (5) {
                        return;
                    }
                }
            }
        }
    }
}
"""
        smells = _scan(source)
        deep = [s for s in smells if s.kind == SmellKind.DEEP_NESTING]
        assert len(deep) >= 1
        # The deepest brace should be on line 8
        assert any(s.line == 8 for s in deep)


# ---------------------------------------------------------------------------
# Empty control flow
# ---------------------------------------------------------------------------


class TestEmptyControlFlow:
    def test_detects_empty_if(self) -> None:
        smells = _scan("""
void empty() {
    int x = 1;
    if (x) {}
}
""")
        assert SmellKind.EMPTY_CONTROL_FLOW in _kinds(smells)

    def test_detects_empty_while(self) -> None:
        smells = _scan("""
void empty_loop() {
    while (1) {}
}
""")
        assert SmellKind.EMPTY_CONTROL_FLOW in _kinds(smells)

    def test_detects_empty_for(self) -> None:
        smells = _scan("""
void empty_for() {
    for (int i = 0; i < 10; i++) {}
}
""")
        assert SmellKind.EMPTY_CONTROL_FLOW in _kinds(smells)

    def test_non_empty_if_passes(self) -> None:
        smells = _scan("""
void ok() {
    int x = 1;
    if (x) {
        x = 0;
    }
}
""")
        empty = [s for s in smells if s.kind == SmellKind.EMPTY_CONTROL_FLOW]
        assert empty == []


# ---------------------------------------------------------------------------
# Too many parameters
# ---------------------------------------------------------------------------


class TestTooManyParameters:
    def test_detects_too_many_params(self) -> None:
        smells = _scan("""
int too_many(int a, int b, int c, int d, int e, int f) {
    return a + b + c + d + e + f;
}
""")
        assert SmellKind.TOO_MANY_PARAMETERS in _kinds(smells)

    def test_few_params_passes(self) -> None:
        smells = _scan("""
int ok(int a, int b, int c, int d, int e) {
    return a + b + c + d + e;
}
""")
        too_many = [s for s in smells if s.kind == SmellKind.TOO_MANY_PARAMETERS]
        assert too_many == []

    def test_no_params_passes(self) -> None:
        smells = _scan("""
int no_params() {
    return 42;
}
""")
        too_many = [s for s in smells if s.kind == SmellKind.TOO_MANY_PARAMETERS]
        assert too_many == []


# ---------------------------------------------------------------------------
# Return count
# ---------------------------------------------------------------------------


class TestReturnCount:
    def test_detects_too_many_returns(self) -> None:
        smells = _scan("""
int multi_return(int x) {
    if (x > 0) return 1;
    if (x < 0) return -1;
    return 0;
}
""")
        assert SmellKind.RETURN_COUNT in _kinds(smells)

    def test_few_returns_passes(self) -> None:
        smells = _scan("""
int ok(int x) {
    if (x > 0) return 1;
    return 0;
}
""")
        rc = [s for s in smells if s.kind == SmellKind.RETURN_COUNT]
        assert rc == []


# ---------------------------------------------------------------------------
# Cyclomatic complexity
# ---------------------------------------------------------------------------


class TestCyclomaticComplexity:
    def test_detects_high_complexity(self) -> None:
        """Many branches → high cyclomatic complexity."""
        source = """
int complex(int x, int y) {
    int r = 0;
    if (x > 0) r += 1;
    if (x < 0) r -= 1;
    if (y > 0) r += 2;
    if (y < 0) r -= 2;
    if (x == 0) r += 3;
    if (y == 0) r -= 3;
    if (x > y) r += 4;
    if (y > x) r -= 4;
    return r;
}
"""
        smells = _scan(source)
        assert SmellKind.CYCLOMATIC_COMPLEXITY in _kinds(smells)

    def test_low_complexity_passes(self) -> None:
        smells = _scan("""
int simple(int x) {
    if (x > 0) return 1;
    return 0;
}
""")
        cc = [s for s in smells if s.kind == SmellKind.CYCLOMATIC_COMPLEXITY]
        assert cc == []


# ---------------------------------------------------------------------------
# Mixed abstraction
# ---------------------------------------------------------------------------


class TestMixedAbstraction:
    def test_detects_mixed_memory_io_string(self) -> None:
        smells = _scan("""
void process(const char *filename) {
    char *buffer = malloc(1024);
    FILE *f = fopen(filename, "r");
    fgets(buffer, 1024, f);
    size_t len = strlen(buffer);
    free(buffer);
    fclose(f);
}
""")
        assert SmellKind.MIXED_ABSTRACTION in _kinds(smells)

    def test_pure_function_passes(self) -> None:
        smells = _scan("""
int add(int a, int b) {
    return a + b;
}
""")
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_ABSTRACTION]
        assert mixed == []

    def test_pure_io_passes(self) -> None:
        smells = _scan("""
void log_msg(const char *msg) {
    printf("%s", msg);
}
""")
        mixed = [s for s in smells if s.kind == SmellKind.MIXED_ABSTRACTION]
        assert mixed == []


# ---------------------------------------------------------------------------
# TODO comments
# ---------------------------------------------------------------------------


class TestTodoComment:
    def test_detects_todo_in_single_line_comment(self) -> None:
        smells = _scan("""
void f() {
    // TODO: fix this later
    int x = 1;
}
""")
        assert SmellKind.TODO_COMMENT in _kinds(smells)

    def test_detects_fixme(self) -> None:
        smells = _scan("""
// FIXME: this is a temporary hack
void g() {}
""")
        assert SmellKind.TODO_COMMENT in _kinds(smells)

    def test_detects_hack(self) -> None:
        smells = _scan("""
void h() {
    // HACK: workaround for compiler bug
    int x = 0;
}
""")
        assert SmellKind.TODO_COMMENT in _kinds(smells)

    def test_detects_multiline_todo(self) -> None:
        smells = _scan("""
/* TODO: refactor this entire module */
void m() {}
""")
        assert SmellKind.TODO_COMMENT in _kinds(smells)

    def test_no_todo_passes(self) -> None:
        smells = _scan("""
// This is a normal comment
int add(int a, int b) {
    return a + b;
}
""")
        todos = [s for s in smells if s.kind == SmellKind.TODO_COMMENT]
        assert todos == []


# ---------------------------------------------------------------------------
# Memory leak risk
# ---------------------------------------------------------------------------


class TestMemoryLeakRisk:
    def test_detects_unfreed_malloc(self) -> None:
        smells = _scan("""
void leak() {
    char *buf = (char *)malloc(256);
    // no free
    buf[0] = '\\0';
}
""")
        assert SmellKind.MEMORY_LEAK_RISK in _kinds(smells)

    def test_freed_malloc_passes(self) -> None:
        smells = _scan("""
void ok() {
    char *buf = (char *)malloc(256);
    free(buf);
}
""")
        leak = [s for s in smells if s.kind == SmellKind.MEMORY_LEAK_RISK]
        assert leak == []

    def test_multiple_allocs_one_freed(self) -> None:
        """Only the unfreed allocation should be reported."""
        smells = _scan("""
void partial_free() {
    char *a = (char *)malloc(100);
    char *b = (char *)malloc(200);
    free(a);
    // b is not freed
    b[0] = 0;
}
""")
        leak = [s for s in smells if s.kind == SmellKind.MEMORY_LEAK_RISK]
        assert len(leak) >= 1
        # b should be flagged
        assert any("'b'" in s.message for s in leak), f"Expected 'b' in leak messages: {leak}"

    def test_alloc_freed_in_loop(self) -> None:
        smells = _scan("""
void loop_free() {
    for (int i = 0; i < 10; i++) {
        char *p = (char *)malloc(100);
        free(p);
    }
}
""")
        leak = [s for s in smells if s.kind == SmellKind.MEMORY_LEAK_RISK]
        assert leak == []

    def test_strdup_detected(self) -> None:
        smells = _scan("""
void str_leak() {
    char *s = strdup("hello");
    // no free
    (void)s;
}
""")
        assert SmellKind.MEMORY_LEAK_RISK in _kinds(smells)
        freed = [s for s in smells if s.kind == SmellKind.MEMORY_LEAK_RISK]
        assert len(freed) >= 1


# ---------------------------------------------------------------------------
# Integration / full-file tests
# ---------------------------------------------------------------------------


class TestCleanFile:
    def test_clean_c_code_has_no_smells(self) -> None:
        smells = _scan("""
#include <stddef.h>

static int helper(int x) {
    return x * 2;
}

int compute(int a, int b) {
    if (a > 0) {
        return helper(a) + b;
    }
    return 0;
}
""")
        assert smells == []


class TestMultipleSmellsInOneFile:
    def test_file_with_multiple_issues(self) -> None:
        smells = _scan("""
// TODO: refactor this file
int global_counter = 0;

int messy(int a, int b, int c, int d, int e, int f) {
    int *p = malloc(sizeof(int) * 10);
    if (a) {
        if (b) {
            if (c) {
                if (d) {
                    if (e) {
                        if (f) {
                            return *p;
                        }
                    }
                }
            }
        }
    }
    return 1;
}
""")
        kinds = _kinds(smells)
        assert SmellKind.TODO_COMMENT in kinds
        assert SmellKind.GLOBAL_VARIABLE in kinds
        assert SmellKind.TOO_MANY_PARAMETERS in kinds
        assert SmellKind.UNCHECKED_MALLOC in kinds
        assert SmellKind.DEEP_NESTING in kinds
        # return 1 at depth 1 + return *p at depth 6 → multiple returns
        assert SmellKind.RETURN_COUNT in kinds


class TestSmellSeverity:
    def test_unchecked_malloc_is_error(self) -> None:
        smells = _scan("""
void leak() {
    int *p = malloc(sizeof(int));
    *p = 1;
}
""")
        s = [s for s in smells if s.kind == SmellKind.UNCHECKED_MALLOC]
        assert s and s[0].severity == SmellSeverity.ERROR

    def test_todo_is_info(self) -> None:
        smells = _scan("""
// TODO: do something
void f() {}
""")
        s = [s for s in smells if s.kind == SmellKind.TODO_COMMENT]
        assert s and s[0].severity == SmellSeverity.INFO

    def test_global_var_is_warning(self) -> None:
        smells = _scan("""
int g;
""")
        s = [s for s in smells if s.kind == SmellKind.GLOBAL_VARIABLE]
        assert s and s[0].severity == SmellSeverity.WARNING


class TestSourceLocation:
    def test_smell_reports_correct_location(self) -> None:
        smells = _scan("""
int global_thing = 42;
""")
        s = [s for s in smells if s.kind == SmellKind.GLOBAL_VARIABLE]
        assert s
        assert s[0].line == 2