# CLenz

A CLI tool for static analysis of C source code — parsing, structural extraction, Nassi-Shneiderman diagrams, and code smell detection — built on ANTLR4 with a DDD-inspired hexagonal architecture.

## Features

- **C11 parsing** — structural model extraction (includes, typedefs, functions, enums, structs, unions, globals, macros) with syntax diagnostics
- **Control flow extraction** — if/else, while, for, do-while, switch/case with arbitrary nesting
- **Nassi-Shneiderman diagrams** — HTML diagrams per file or per directory, dark theme, depth-coded nesting up to 50 levels, responsive layout
- **Code smell scanning** — 29 detectors covering safety, complexity, naming, Fowler refactoring smells, and more

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone <repo-url> clenz && cd clenz
uv sync --extra dev
uv run python scripts/generate_c_parser.py
```

After installation the `clenz` command is available via `uv run clenz`.

## Usage

### Parse a single file

```bash
uv run clenz parse-file path/to/File.c
```

Returns a JSON report with structural elements, diagnostics, and parse statistics.

### Parse a directory

```bash
uv run clenz parse-dir path/to/project
```

Scans all `.c` files and returns a combined JSON report.

### Nassi-Shneiderman diagram — single file

```bash
uv run clenz nassi-file path/to/Algorithms.c --out output/algorithms.nassi.html
```

### Nassi-Shneiderman diagrams — directory

```bash
uv run clenz nassi-dir path/to/project --out output/nassi-bundle
```

Generates an HTML diagram per file plus an `index.html` with a summary table.

### Scan code smells — single file

```bash
uv run clenz smell-file path/to/File.c
```

### Scan code smells — directory

```bash
uv run clenz smell-dir path/to/project
```

### Verbose logging

Add `--verbose` to any command for lifecycle logging.

## Output format

All commands output JSON to stdout. Exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success (no errors) |
| 1 | Success with errors (smell scan found errors, or parse had technical failures) |
| 2 | Application error (`ClenzError`) |

## Code smell detectors

29 detectors across three severity levels, tuned for C-specific risks (no exceptions, no RAII, no type safety):

### Error — safety / UB / crashes

| Detector | Description |
|----------|-------------|
| `unchecked_malloc` | `malloc`/`calloc`/`realloc` result used without NULL check |
| `unsafe_function` | Use of `gets`, `strcpy`, `sprintf`, `strcat`, `scanf("%s", ...)` |
| `memory_leak_risk` | Pointer overwritten after allocation without `free` |
| `uninitialized_var` | Local variables used before assignment |
| `unchecked_return` | Function call with a non-void return type where the result is discarded |

### Warning — logic errors / hard-to-debug issues / OOP smells

| Detector | Description |
|----------|-------------|
| `deep_nesting` | Control flow nesting deeper than 5 levels |
| `cyclomatic_complexity` | Function cyclomatic complexity exceeds 15 |
| `global_variable` | File-scope mutable variables |
| `missing_const` | Pointer parameters that could be `const`-qualified |
| `return_count` | More than 4 `return` statements — risk of resource leaks on early returns |
| `long_function` | Functions exceeding 50 lines |
| `magic_number` | Numeric literals other than 0, 1, 2 in non-constant expressions |
| `too_many_parameters` | Functions with more than 5 parameters |
| `large_file` | Source files exceeding 500 lines |
| `switch_statements` | `switch` with more than 10 cases |
| `empty_control_flow` | Empty if/else/for/while bodies |
| `mixed_abstraction` | High-level logic mixed with low-level operations in the same function |
| `feature_envy` | Function that calls another module more than itself |
| `data_clumps` | Same group of 3+ parameter types repeated across functions |
| `message_chains` | Chains of 4+ sequential function calls |
| `middle_man` | Function that just delegates to another function |
| `divergent_change` | Unrelated concerns in the same function |
| `shotgun_surgery` | Same concept scattered across many small functions |
| `temporary_field` | Variables used only inside a narrow scope branch |
| `refused_bequest` | Base abstraction ignored by derived logic |
| `speculative_generality` | Unused parameters, dead branches, or overly abstract code |

### Info — style / readability

| Detector | Description |
|----------|-------------|
| `short_name` | Identifiers under 3 characters (excluding loop variables) |
| `primitive_obsession` | Excessive use of raw ints/chars for domain concepts |
| `todo_comment` | `TODO`, `FIXME`, `HACK`, `XXX` markers in comments |
| `comment_density` | Comment-to-code ratio exceeds 40% |

## Nassi-Shneiderman diagram features

- Classic NS triangles for if-blocks with Yes/No labels
- Side-by-side columns for switch/case
- 50 depth levels with cycling color palettes (blue, green, purple, teal, amber) and Unicode circled badges
- Tokyo Night dark theme with JetBrains Mono font
- Responsive layout, text wrapping, SVG rendering

![Basic NS diagram](docs/screenshots/nassi_diagram.png)

![Nested depth diagram](docs/screenshots/nested_depth.png)

## Architecture

```
src/clenz/
  domain/          # model, ports, domain events, smell types, control flow types
  application/     # use cases, DTOs, Nassi diagram service
  infrastructure/  # ANTLR adapter, filesystem repo, smell scanner, HTML renderer
  presentation/    # CLI entry point (argparse)
```

Design docs: [domain-and-goals.md](docs/domain-and-goals.md), [requirements.md](docs/requirements.md), [architecture.md](docs/architecture.md), [system-context.md](docs/system-context.md), [glossary.md](docs/glossary.md).

## Development

```bash
uv sync --extra dev
uv run python scripts/generate_c_parser.py
uv run pytest
uv run ruff check src tests
```

## Constraints

The ANTLR grammar targets C11 (from `antlr/grammars-v4/c`). GCC extensions and platform-specific dialects are not covered. Limitations are documented in requirements and ADRs.

## License

MIT
