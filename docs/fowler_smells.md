# Fowler Refactoring Code Smells — Adapted for C

Martin Fowler's *Refactoring* (Chapter 3, "Code Smells") defines 22 code smells. This document maps them to C-specific detection strategies for CLEnz, noting which are already detected and which should be added.

## Already Detected by CLEnz

| Fowler Smell | CLEnz Detector | Notes |
|---|---|---|
| Long Method | `long_function` | Threshold: 60 lines |
| Large Class | — | N/A for C (no classes) |
| Long Parameter List | `too_many_parameters` | Threshold: 5 params |
| Deeply Nested Code | `deep_nesting` | Already tracked |
| Comments | `todo_comment` | Partial — only detects TODO/FIXME, not comment-overuse |
| Duplicated Code | `cyclomatic_complexity` | Indirect — high complexity often means copy-paste |

## Smells to Implement

### 1. Switch Statements

**Fowler:** Repeated `switch`/`case` on the same type code across multiple functions suggests polymorphism is needed.

**C-specific detection:**
- Find `switch` statements with >8 `case` labels
- Find the same variable/expression used in `switch` across >=3 functions in the same file
- In C, look for `switch (type)` or `switch (kind)` or `switch (msg->id)` patterns — these are classic type-code switches

**Token strategy:**
- Count `SWITCH` tokens, then count `CASE` tokens until `RBRACE` at matching nesting depth
- Extract the switch expression by grabbing tokens between `LPAREN` after `SWITCH` and matching `RPAREN`
- Track which expressions appear in multiple switches

**Severity:** WARNING

---

### 2. Message Chains

**Fowler:** `a->b()->c()->d()` — a chain of method/field accesses that violates Law of Demeter.

**C-specific detection:**
- Chains of `->` and `.` accesses: `ptr->next->next->data`, `obj->parent->config->value`
- Threshold: chain length >=4 (i.e., >=3 `->` or `.` in sequence)
- Common in C with linked lists and nested structs: `head->next->next->value`

**Token strategy:**
- Walk token stream looking for `->` sequences
- Count consecutive `->` / `.` without intermediate `;` or `=`
- A chain is: IDENT (`->` | `.`) IDENT (`->` | `.`) IDENT ... with optional `( )` pairs (function calls)

**Severity:** INFO

---

### 3. Data Clumps

**Fowler:** The same group of parameters appears together in multiple functions.

**C-specific detection:**
- Same 2+ parameter types appearing together in >=3 function signatures
- Common C patterns: `(width, height)`, `(x, y, z)`, `(buf, len)`, `(fd, buf, count)`
- Also check struct fields: if a group of fields appears in multiple structs, that's a clump

**Token strategy:**
- Parse function signatures: after `IDENT LPAREN`, collect type-name pairs until `RPAREN`
- Group signatures by parameter type pairs (sorted by type name)
- Flag groups appearing >=3 times

**Severity:** INFO

---

### 4. Feature Envy

**Fowler:** A function that spends more time accessing data from another struct than its own parameters.

**C-specific detection:**
- A function that primarily accesses fields of one specific `struct` pointer parameter (not the "main" one)
- Pattern: function receives `struct A *a, struct B *b` but mostly calls `b->field`
- In C, this means the function probably belongs to the module that owns struct B

**Token strategy:**
- For each function, track which pointer parameters are accessed via `->`
- Count `param_name->` accesses per parameter
- If one parameter's `->` count is >=60% of all `->` accesses, flag it

**Severity:** INFO

---

### 5. Primitive Obsession

**Fowler:** Overuse of primitive types instead of small structs for domain concepts.

**C-specific detection:**
- Functions with >=3 parameters of the same primitive type (`int`, `char *`, `float`, etc.)
- Common C anti-pattern: `void draw(int x1, int y1, int x2, int y2, int color)` — should use `struct Point`
- Also: `typedef` for primitive types that never get used (raw `int` used as handles/ids everywhere)

**Token strategy:**
- In function parameter lists, count how many params share the same type
- If >=3 params have type `int`, `float`, `double`, `char *`, or `char` → flag
- Exclude `void *` (common generic pattern in C)

**Severity:** INFO

---

### 6. Middle Man

**Fowler:** A struct/module where most functions just delegate to another struct's functions.

**C-specific detection:**
- A `.c` file where most functions just call through to another module's functions
- Pattern: wrapper functions that only call one other function with the same args
- Common in C with "adapter" or "wrapper" patterns that add no value

**Token strategy:**
- For each function, check if the body is a single function call
- Track which module/struct is being delegated to
- If >=50% of functions in a file are single-call delegations to the same target → flag
- This is harder token-based; requires cross-file awareness of what's "delegating"

**Severity:** INFO

---

### 7. Speculative Generality

**Fowler:** Unused parameters, dead code, abstract interfaces with one implementation.

**C-specific detection:**
- Function parameters declared but never referenced in the function body
- `#ifdef` blocks that are never triggered (dead conditional compilation)
- Unused `static` functions (declared but never called in the file)
- Function pointers in structs that are always set to the same implementation

**Token strategy:**
- Collect parameter names from function signature
- Check if each name appears in the function body tokens (between `{` and matching `}`)
- For unused `static` functions: collect all `static` function names, then check if each appears as an identifier elsewhere in the file

**Severity:** WARNING

---

### 8. Divergent Change

**Fowler:** One module/struct changed for different reasons — methods access unrelated field groups.

**C-specific detection:**
- A struct where different functions access completely disjoint field subsets
- Pattern: `struct Order` where customer-related functions never touch item-related fields and vice versa
- In C, functions operating on struct pointers: track which fields each function accesses

**Token strategy:**
- For each function receiving a `struct_name *` parameter, collect all `param->field_name` accesses
- Group functions by which fields they access
- If there exist two functions with zero field overlap (one accesses fields A,B; other accesses fields C,D) → flag

**Severity:** WARNING

---

### 9. Shotgun Surgery

**Fowler:** A change requires touching many different modules/files.

**C-specific detection:**
- A struct type used as a parameter across many different `.c` files
- Pattern: `struct Config` passed to functions in 5+ different files — any change to Config cascades everywhere
- Cross-file analysis: count how many files reference the same struct type in function signatures

**Token strategy:**
- Requires `smell-dir` mode (cross-file)
- Collect all struct types appearing in function parameter lists across all files
- If a struct type appears in >=5 functions spanning >=3 different files → flag

**Severity:** WARNING

---

### 10. Temporary Field

**Fowler:** Struct fields only used in specific contexts — most of the time they're unused.

**C-specific detection:**
- Struct fields that are accessed by <=1 function out of many that receive the struct pointer
- Pattern: `struct Report { char *title, *content, *temp_data, *debug_info }` where `temp_data` is only used in one function
- In C headers: fields declared in structs but rarely accessed

**Token strategy:**
- Collect all struct field names from `struct` definitions in the file
- For each function, check which fields are accessed via `->`
- If a field is accessed in <=1 function out of >=4 functions that receive the struct → flag

**Severity:** INFO

---

### 11. Refused Bequest

**Fowler:** A "child" that only uses a small fraction of what it inherits.

**C-specific detection:**
- In C, "inheritance" is struct embedding via composition: `struct Child { struct Base base; int extra; }`
- A struct that embeds another struct but only uses a few fields of the embedded one
- Also: function pointer tables (vtable-like patterns) where most entries are unused or point to stubs

**Token strategy:**
- Find struct definitions containing another struct as a field (non-pointer)
- For each "child" struct, count how many of the embedded struct's fields are accessed via `child.base.field` patterns
- If <30% of embedded struct's fields are used → flag

**Severity:** INFO

---

### 12. Comments (Enhanced)

**Fowler:** Comments present because the code is unclear — the code should explain itself.

**C-specific detection (enhanced from current `todo_comment`):**
- Functions with comment-to-code ratio >40% (lines of comments vs lines of code)
- Block comments (`/* ... */`) that are longer than the function they describe
- Every parameter documented with a comment but the names are already self-explanatory
- `// TODO` and `// FIXME` already detected — extend to `// HACK`, `// XXX`, `// BUG`

**Token strategy:**
- For each function region, count lines that are comments vs lines that are code
- Track `BLOCK_COMMENT` and `LINE_COMMENT` tokens
- If comment_lines / total_lines > 0.4 and function is >=10 lines → flag

**Severity:** INFO

---

## Not Applicable to C

| Fowler Smell | Reason |
|---|---|
| Large Class | C has no classes |
| Lazy Element | No trivial wrappers in typical C; functions always do something |
| Data Class | C structs have no methods to be "data-only" — that's normal |
| Incomplete Library Class | C has no class extension mechanism |
| Alternative Classes with Different Interfaces | Requires OOP interfaces |

## Implementation Priority

1. **Switch Statements** — high impact, easy token detection
2. **Primitive Obsession** — straightforward param type counting
3. **Speculative Generality** (unused params) — easy to detect, real bugs
4. **Data Clumps** — common in C APIs
5. **Comments (enhanced)** — extend existing `todo_comment`
6. **Message Chains** — `->` chain counting
7. **Feature Envy** — requires tracking per-param access counts
8. **Divergent Change** — requires field-access tracking per function
9. **Temporary Field** — requires struct field usage analysis
10. **Shotgun Surgery** — requires cross-file analysis
11. **Refused Bequest** — struct embedding patterns
12. **Middle Man** — hardest to detect without full AST

## Implementation Notes

Each new smell follows the CLEnz pattern:

1. Add `SmellKind` enum value in `domain/smells.py`
2. Write `_check_<name>` function in `infrastructure/linting/smell_scanner.py`
3. Call from `AntlrCSmellScanner.scan()`
4. Add tests in `tests/`

All checks are token-based (ANTLR `CLexer` output). No parse tree required.
