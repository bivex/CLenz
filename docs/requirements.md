# Requirements

## Functional Requirements

### Parse Report Capabilities

1. The system must parse a single `.swift` file.
2. The system must parse a directory recursively and ignore non-Swift files.
3. The system must return a versioned parse report for each source unit.
4. The system must aggregate file-level outcomes into one parsing job result.
5. The system must capture syntax diagnostics with message, severity, line, and column.
6. The system must continue parsing other files when one file fails.
7. The system must extract a stable structural model containing at least imports, type aliases, types, functions, variables, constants, and extensions.
8. The system must expose grammar version and report schema version as part of the result contract.
9. The system must distinguish successful parsing, parsing with diagnostics, and technical failure.
10. The CLI must return machine-readable JSON for parse workflows.

### Control Flow and Diagram Capabilities

11. The system must extract structured control flow for each function or method in a Swift source file.
12. The control-flow model must support `if/else`, `guard`, `while`, `for-in`, `repeat-while`, `switch`, `do/catch`, and `defer`.
13. The extractor must expand supported trailing closures when doing so improves the structural control-flow model.
14. The system must build an HTML Nassi-Shneiderman diagram for a single Swift file.
15. The system must build a directory bundle of Nassi diagrams and an index page that links to each generated document.
16. Diagram metadata must expose source location, function count, and function names.
17. Diagram rendering must preserve function signatures and qualified names.
18. Nested conditional rendering must remain readable up to the supported depth range and expose depth cues in the HTML output.
19. Diagram layout must support responsive wrapping and must avoid cumulative nested-width growth that makes deeply nested branches unreadable.
20. The CLI must return machine-readable JSON metadata for diagram generation workflows.

### Architectural and Contract Requirements

21. External dependencies must stay behind explicit ports.
22. Delivery concerns such as filesystem output paths, CLI arguments, and JSON formatting must remain outside the domain layer.
23. Parser limitations must be visible to consumers rather than silently presented as compiler-level certainty.
24. The system must keep generated parser code isolated from the core domain and application logic.

## Non-Functional Requirements

### Maintainability

* keep domain and application layers independent from ANTLR, filesystem, HTML rendering, and CLI code
* keep modules small and single-purpose
* use explicit contracts and constructor injection
* keep parse-report and diagram workflows understandable as separate application services

### Testability

* cover domain rules with unit tests
* cover parser and extractor behavior with boundary tests
* test renderer output at the HTML and CSS contract level when layout regressions are likely
* keep use cases runnable with test doubles

### Operability

* emit structured lifecycle logs for parse workflows
* make errors explicit and machine-readable
* support deterministic CLI execution in CI
* keep output paths predictable for generated diagram files and bundles

### Resilience

* isolate file failures from the rest of a parse job
* distinguish business validation failures from technical failures
* avoid partial job completion states that look successful
* keep control-flow extraction and rendering failures explicit instead of silently dropping content

### Rendering Quality

* generated diagrams must remain legible on common desktop widths
* nested branches must wrap within the function canvas instead of forcing every nested node to widen the whole diagram
* long labels and signatures must wrap instead of overflowing their containers

### Security

* do not execute parsed source
* avoid hidden network calls during normal parsing or diagram generation
* treat the filesystem as an input/output boundary, not a trust boundary

### Extensibility

* allow new adapters without changing stable domain code
* allow richer structural extraction behind the same use-case contract
* allow new renderers to consume `ControlFlowDiagram` without changing extraction logic
* keep schema and grammar versions explicit for backward-compatible evolution

## Constraints and Honesty

The current parser is based on the public `antlr/grammars-v4` Swift 5 grammar and inherits its limits. The system is expected to be honest about ambiguity, unsupported syntax, or grammar drift. When the tool cannot provide compiler-grade certainty, the contract should surface that limitation rather than hide it.

## Quality Attributes

The system prioritizes clarity, correctness, and evolvability over premature optimization. Performance optimization is allowed only after measurement and must preserve architectural boundaries, contract clarity, and diagram readability.
