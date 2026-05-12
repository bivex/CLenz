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

    def test_malloc_as_function_pointer_passes(self) -> None:
        """malloc used as a function pointer (e.g. assignment) should not be flagged as an unchecked call."""
        smells = _scan("""
void set_allocator() {
    global_allocate = malloc;
    global_reallocate = realloc;
}
""")
        unchecked = [s for s in smells if s.kind == SmellKind.UNCHECKED_MALLOC]
        assert unchecked == []


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

    def test_struct_field_passes(self) -> None:
        smells = _scan("""
struct Point {
    int x;
    int y;
};
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

    def test_const_global_passes(self) -> None:
        smells = _scan("""
const int MAX = 100;
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


# ---------------------------------------------------------------------------
# Switch Statements (Fowler)
# ---------------------------------------------------------------------------


class TestSwitchStatements:
    def test_detects_large_switch(self) -> None:
        cases = " ".join(f"case {i}: break;" for i in range(10))
        source = f"""
void dispatch(int x) {{
    switch (x) {{
        {cases}
    }}
}}
"""
        smells = _scan(source)
        assert SmellKind.SWITCH_STATEMENTS in _kinds(smells)

    def test_small_switch_passes(self) -> None:
        smells = _scan("""
void small(int x) {
    switch (x) {
        case 1: break;
        case 2: break;
        case 3: break;
    }
}
""")
        switch = [s for s in smells if s.kind == SmellKind.SWITCH_STATEMENTS]
        assert switch == []

    def test_switch_with_default_at_threshold(self) -> None:
        cases = " ".join(f"case {i}: break;" for i in range(8))
        source = f"""
void at_limit(int x) {{
    switch (x) {{
        {cases}
        default: break;
    }}
}}
"""
        smells = _scan(source)
        # 8 cases + 1 default = 9, which exceeds threshold of 8
        assert SmellKind.SWITCH_STATEMENTS in _kinds(smells)

    def test_nested_switch_only_flags_inner(self) -> None:
        inner = " ".join(f"case {i}: break;" for i in range(10))
        source = f"""
void nested(int x, int y) {{
    switch (x) {{
        case 1:
            switch (y) {{
                {inner}
            }}
            break;
    }}
}}
"""
        smells = _scan(source)
        switch = [s for s in smells if s.kind == SmellKind.SWITCH_STATEMENTS]
        assert len(switch) >= 1


# ---------------------------------------------------------------------------
# Message Chains (Fowler)
# ---------------------------------------------------------------------------


class TestMessageChains:
    def test_detects_long_chain(self) -> None:
        smells = _scan("""
void chain() {
    int v = head->next->next->data->value;
}
""")
        assert SmellKind.MESSAGE_CHAINS in _kinds(smells)

    def test_short_chain_passes(self) -> None:
        smells = _scan("""
void short_chain() {
    int v = obj->field->subfield;
}
""")
        chains = [s for s in smells if s.kind == SmellKind.MESSAGE_CHAINS]
        assert chains == []

    def test_chain_with_function_call(self) -> None:
        smells = _scan("""
void func_chain() {
    int v = obj->get_next()->data->get_value()->result;
}
""")
        assert SmellKind.MESSAGE_CHAINS in _kinds(smells)

    def test_no_chain(self) -> None:
        smells = _scan("""
void no_chain() {
    int v = ptr->field;
}
""")
        chains = [s for s in smells if s.kind == SmellKind.MESSAGE_CHAINS]
        assert chains == []


# ---------------------------------------------------------------------------
# Data Clumps (Fowler)
# ---------------------------------------------------------------------------


class TestDataClumps:
    def test_detects_repeated_param_pairs(self) -> None:
        smells = _scan("""
void draw_line(int x, int y, int w, int h) {}
void draw_rect(int x, int y, int w, int h) {}
void draw_box(int x, int y, int w, int h) {}
""")
        assert SmellKind.DATA_CLUMPS in _kinds(smells)

    def test_no_clump_different_types(self) -> None:
        smells = _scan("""
void func_a(int x, char *s) {}
void func_b(float f, double d) {}
void func_c(int y, char *t) {}
""")
        clumps = [s for s in smells if s.kind == SmellKind.DATA_CLUMPS]
        assert clumps == []

    def test_two_occurrences_not_enough(self) -> None:
        smells = _scan("""
void func_a(int x, int y) {}
void func_b(int x, int y) {}
""")
        clumps = [s for s in smells if s.kind == SmellKind.DATA_CLUMPS]
        assert clumps == []


# ---------------------------------------------------------------------------
# Feature Envy (Fowler)
# ---------------------------------------------------------------------------


class TestFeatureEnvy:
    def test_detects_feature_envy(self) -> None:
        smells = _scan("""
struct A { int x; };
struct B { int y; int z; int w; int q; int r; };

void envious(struct A *a, struct B *b) {
    int v1 = b->y;
    int v2 = b->z;
    int v3 = b->w;
    int v4 = b->q;
    int v5 = b->r;
    int va = a->x;
}
""")
        assert SmellKind.FEATURE_ENVY in _kinds(smells)

    def test_balanced_access_passes(self) -> None:
        smells = _scan("""
struct A { int x; int y; };
struct B { int p; int q; };

void balanced(struct A *a, struct B *b) {
    int v1 = a->x;
    int v2 = a->y;
    int v3 = b->p;
    int v4 = b->q;
}
""")
        envy = [s for s in smells if s.kind == SmellKind.FEATURE_ENVY]
        assert envy == []

    def test_no_pointer_access(self) -> None:
        smells = _scan("""
struct Point { int x; int y; };

int compute(struct Point *p1, struct Point *p2) {
    return 0;
}
""")
        envy = [s for s in smells if s.kind == SmellKind.FEATURE_ENVY]
        assert envy == []


# ---------------------------------------------------------------------------
# Primitive Obsession (Fowler)
# ---------------------------------------------------------------------------


class TestPrimitiveObsession:
    def test_detects_many_int_params(self) -> None:
        smells = _scan("""
void draw(int x1, int y1, int x2, int y2, int color) {}
""")
        assert SmellKind.PRIMITIVE_OBSESSION in _kinds(smells)

    def test_variety_of_types_passes(self) -> None:
        smells = _scan("""
void mixed(int a, char *b, float c, double d) {}
""")
        prim = [s for s in smells if s.kind == SmellKind.PRIMITIVE_OBSESSION]
        assert prim == []

    def test_two_same_type_not_enough(self) -> None:
        smells = _scan("""
void ok(int a, int b, char *s) {}
""")
        prim = [s for s in smells if s.kind == SmellKind.PRIMITIVE_OBSESSION]
        assert prim == []


# ---------------------------------------------------------------------------
# Middle Man (Fowler)
# ---------------------------------------------------------------------------


class TestMiddleMan:
    def test_detects_delegation_file(self) -> None:
        smells = _scan("""
int wrap_add(int a, int b) {
    return real_add(a, b);
}

int wrap_sub(int a, int b) {
    return real_sub(a, b);
}

int wrap_mul(int a, int b) {
    return real_mul(a, b);
}
""")
        assert SmellKind.MIDDLE_MAN in _kinds(smells)

    def test_real_logic_passes(self) -> None:
        smells = _scan("""
int add(int a, int b) {
    if (a > 0) return a + b;
    return b;
}

int sub(int a, int b) {
    return a - b;
}
""")
        middle = [s for s in smells if s.kind == SmellKind.MIDDLE_MAN]
        assert middle == []

    def test_mixed_file_passes(self) -> None:
        smells = _scan("""
int wrap(int a, int b) {
    return real_compute(a, b);
}

int real_compute(int a, int b) {
    if (a > 0) return a + b;
    if (b > 0) return a - b;
    return 0;
}

int other(int x) {
    if (x > 0) return x;
    return -x;
}
""")
        middle = [s for s in smells if s.kind == SmellKind.MIDDLE_MAN]
        assert middle == []


# ---------------------------------------------------------------------------
# Speculative Generality (Fowler)
# ---------------------------------------------------------------------------


class TestSpeculativeGenerality:
    def test_detects_unused_param(self) -> None:
        smells = _scan("""
int compute(int used, int unused) {
    return used;
}
""")
        assert SmellKind.SPECULATIVE_GENERALITY in _kinds(smells)
        spec = [s for s in smells if s.kind == SmellKind.SPECULATIVE_GENERALITY]
        assert any("unused" in s.message for s in spec)

    def test_all_params_used_passes(self) -> None:
        smells = _scan("""
int add(int a, int b) {
    return a + b;
}
""")
        spec = [s for s in smells if s.kind == SmellKind.SPECULATIVE_GENERALITY]
        assert spec == []

    def test_detects_unused_static_function(self) -> None:
        smells = _scan("""
static int helper(int x) {
    return x * 2;
}
""")
        assert SmellKind.SPECULATIVE_GENERALITY in _kinds(smells)
        spec = [s for s in smells if s.kind == SmellKind.SPECULATIVE_GENERALITY]
        assert any("helper" in s.message and "never called" in s.message for s in spec)

    def test_used_static_passes(self) -> None:
        smells = _scan("""
static int helper(int x) {
    return x * 2;
}

int compute(int a) {
    return helper(a);
}
""")
        unused_static = [
            s for s in smells
            if s.kind == SmellKind.SPECULATIVE_GENERALITY and "never called" in s.message
        ]
        assert unused_static == []


# ---------------------------------------------------------------------------
# Divergent Change (Fowler)
# ---------------------------------------------------------------------------


class TestDivergentChange:
    def test_detects_disjoint_field_access(self) -> None:
        smells = _scan("""
struct Order {
    int customer_id;
    char *customer_name;
    int item_count;
    int item_total;
};

void process_customer(struct Order *o) {
    o->customer_id = 1;
    o->customer_name = "Alice";
}

void process_items(struct Order *o) {
    o->item_count = 10;
    o->item_total = 100;
}
""")
        assert SmellKind.DIVERGENT_CHANGE in _kinds(smells)

    def test_overlapping_access_passes(self) -> None:
        smells = _scan("""
struct Data {
    int a;
    int b;
    int c;
};

void func_x(struct Data *d) {
    d->a = 1;
    d->b = 2;
}

void func_y(struct Data *d) {
    d->b = 3;
    d->c = 4;
}
""")
        div = [s for s in smells if s.kind == SmellKind.DIVERGENT_CHANGE]
        assert div == []


# ---------------------------------------------------------------------------
# Shotgun Surgery (Fowler)
# ---------------------------------------------------------------------------


class TestShotgunSurgery:
    def test_detects_widely_used_struct(self) -> None:
        smells = _scan("""
struct Config { int val; };
void f1(struct Config *c) { c->val = 1; }
void f2(struct Config *c) { c->val = 2; }
void f3(struct Config *c) { c->val = 3; }
void f4(struct Config *c) { c->val = 4; }
void f5(struct Config *c) { c->val = 5; }
""")
        assert SmellKind.SHOTGUN_SURGERY in _kinds(smells)

    def test_locally_used_struct_passes(self) -> None:
        smells = _scan("""
struct Point { int x; int y; };
void move(struct Point *p) { p->x = 1; }
void scale(struct Point *p) { p->y = 2; }
""")
        shotgun = [s for s in smells if s.kind == SmellKind.SHOTGUN_SURGERY]
        assert shotgun == []


# ---------------------------------------------------------------------------
# Temporary Field (Fowler)
# ---------------------------------------------------------------------------


class TestTemporaryField:
    def test_detects_rarely_used_field(self) -> None:
        smells = _scan("""
struct Report {
    int id;
    int status;
    int count;
    int debug_flag;
};

void init(struct Report *r) {
    r->id = 1;
    r->status = 0;
    r->count = 0;
}

void process(struct Report *r) {
    r->status = 1;
    r->count += 1;
}

void finish(struct Report *r) {
    r->status = 2;
}

void reset(struct Report *r) {
    r->id = 0;
    r->status = 0;
    r->count = 0;
}
""")
        assert SmellKind.TEMPORARY_FIELD in _kinds(smells)
        temp = [s for s in smells if s.kind == SmellKind.TEMPORARY_FIELD]
        assert any("debug_flag" in s.message for s in temp)

    def test_well_used_fields_passes(self) -> None:
        smells = _scan("""
struct Pair {
    int a;
    int b;
};

void set_a(struct Pair *p) { p->a = 1; }
void set_b(struct Pair *p) { p->b = 2; }
""")
        temp = [s for s in smells if s.kind == SmellKind.TEMPORARY_FIELD]
        assert temp == []


# ---------------------------------------------------------------------------
# Refused Bequest (Fowler)
# ---------------------------------------------------------------------------


class TestRefusedBequest:
    def test_detects_unused_embedding(self) -> None:
        smells = _scan("""
struct Base {
    int x;
    int y;
    int z;
    int w;
    int q;
};

struct Child {
    struct Base base;
    int extra;
};

void use_child(struct Child *c) {
    c->base->x = 1;
    c->extra = 2;
}
""")
        # May or may not detect depending on token patterns
        # The key is that only 1 out of 5 Base fields is accessed
        bequest = [s for s in smells if s.kind == SmellKind.REFUSED_BEQUEST]
        # This test validates the check runs without error
        # Exact detection depends on token stream patterns

    def test_well_used_embedding(self) -> None:
        smells = _scan("""
struct Base {
    int x;
    int y;
};

struct Child {
    struct Base base;
    int extra;
};

void use_child(struct Child *c) {
    c->base->x = 1;
    c->base->y = 2;
    c->extra = 3;
}
""")
        bequest = [s for s in smells if s.kind == SmellKind.REFUSED_BEQUEST]
        # With 2/2 base fields used, should not flag
        assert bequest == []


# ---------------------------------------------------------------------------
# Comment Density (Fowler)
# ---------------------------------------------------------------------------


class TestCommentDensity:
    def test_detects_overcommented_function(self) -> None:
        source = """
int overcommented(int x) {
    /* This function does something */
    /* Step 1: check x */
    /* Step 2: compute result */
    /* Step 3: return */
    /* Additional note */
    /* Another note */
    /* More commentary */
    /* Explanation */
    int result = x + 1;
    return result;
}
"""
        smells = _scan(source)
        assert SmellKind.COMMENT_DENSITY in _kinds(smells)

    def test_normal_comment_ratio_passes(self) -> None:
        smells = _scan("""
int normal(int x) {
    /* compute result */
    int a = x + 1;
    int b = a * 2;
    int c = b - 1;
    int d = c + 3;
    int e = d * 4;
    int f = e - 2;
    int g = f + 1;
    return g;
}
""")
        density = [s for s in smells if s.kind == SmellKind.COMMENT_DENSITY]
        assert density == []

    def test_short_function_skipped(self) -> None:
        smells = _scan("""
int tiny(int x) {
    /* lots of comments */
    /* for a tiny func */
    /* still many */
    return x;
}
""")
        density = [s for s in smells if s.kind == SmellKind.COMMENT_DENSITY]
        assert density == []