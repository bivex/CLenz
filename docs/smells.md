# C Code Smell Scanner

CLenz scans C source files for common code smells using token-based analysis. No full AST required — it works directly on the lexer output, so it's fast and tolerant of broken code.

## Usage

```bash
clenz smell-file path/to/file.c
clenz smell-dir path/to/project/
```

Output is JSON to stdout. Exit code is `1` if any errors are found, `0` otherwise.

## Detected Smells

### ERROR — must fix

| Kind | Rule | Example |
|------|------|---------|
| `unsafe_function` | `gets`, `strcpy`, `sprintf`, `strcat`, `vsprintf` | `gets(buf)` → use `fgets` |
| `unchecked_malloc` | `malloc`/`calloc`/`realloc` without null check | `p = malloc(n);` with no `if (!p)` |

### WARNING — should fix

| Kind | Rule | Default threshold |
|------|------|-------------------|
| `global_variable` | Variables declared outside any function body | — |
| `long_function` | Function body exceeds line limit | 60 lines |
| `uninitialized_var` | `int x;` without initializer | — |
| `unchecked_return` | `fopen`/`fread`/`fwrite` result not checked | — |
| `memory_leak_risk` | `malloc` without matching `free` on visible paths | — |
| `large_file` | File exceeds line limit | 500 lines |

### INFO — consider fixing

| Kind | Rule |
|------|------|
| `magic_number` | Numeric literals other than `0`, `1`, `2`, `-1`, `NULL` |
| `missing_const` | `char *param` that could be `const char *param` |
| `short_name` | Variables named with 1–2 characters (except `i`, `j`, `k`, `x`, `y`, `z`, `n`, `m`, `c`, `p`, `r`) |

## Output Format

### smell-file

```json
{
  "source_location": "/path/to/file.c",
  "line_count": 120,
  "function_count": 4,
  "smell_count": 3,
  "errors": 0,
  "warnings": 2,
  "info": 1,
  "clean": false,
  "smells": [
    {
      "kind": "magic_number",
      "severity": "info",
      "message": "magic number '100' — consider defining a named constant",
      "line": 15,
      "column": 19
    }
  ]
}
```

### smell-dir

```json
{
  "file_count": 5,
  "total_errors": 1,
  "files": [
    { "...same as smell-file output per file..." }
  ]
}
```

## How It Works

The scanner uses the generated ANTLR `CLexer` to tokenize the source, then runs rule checks against the token stream:

1. **Tokenize** — run CLexer, collect all tokens (including hidden channel for some rules)
2. **Rule checks** — each rule is an independent function that walks the token list
3. **Aggregate** — collect all `CodeSmell` instances, sort by line number

No parse tree is built. This makes the scanner fast and tolerant — it works on incomplete or invalid C code.

## Architecture

```
domain/smells.py           — CodeSmell, SmellKind, SmellSeverity, SmellReport
domain/ports.py            — CSmellScanner port
infrastructure/linting/    — AntlrCSmellScanner (token-based implementation)
presentation/cli/main.py   — smell-file, smell-dir subcommands
```

## Adding New Rules

1. Add a `SmellKind` enum value in `domain/smells.py`
2. Write a `_check_<rule_name>` function in `infrastructure/linting/smell_scanner.py`
3. Call it from `AntlrCSmellScanner.scan()`

Each check function takes a `list[_Token]` and optional `lexer_type`, returns `list[CodeSmell]`.

## Limitations

- **No cross-file analysis** — only sees one file at a time
- **No type inference** — can't distinguish `int *p` from `struct foo *p`
- **No preprocessor expansion** — `#define` values aren't resolved
- **Heuristic-based** — some false positives and false negatives are expected
- **Memory leak detection** is conservative — only flags allocations with no visible `free` at all
