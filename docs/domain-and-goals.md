# Domain and Business Goals

## Problem Statement

Teams need a reliable way to inspect Swift code outside the Swift compiler for two related jobs:

* produce a stable, machine-consumable structural report that other tools can automate against
* produce a human-readable control-flow view that helps engineers inspect branching logic quickly

Swifta exists to turn raw Swift source into those two outputs without coupling the core model to CLI details, filesystem traversal, or ANTLR-specific concerns.

## Business Goals

1. Parse Swift code in a repeatable and automatable way.
2. Expose a stable structural model that downstream tools can trust even as delivery channels evolve.
3. Extract structured control flow from function bodies so higher-level visualizations can be built on top of it.
4. Generate Nassi-Shneiderman HTML diagrams that are useful for inspection, onboarding, and documentation.
5. Keep grammar limitations, schema versioning, and runtime failures explicit instead of hiding uncertainty.
6. Preserve a monolith shape that is easy to understand, test, and extend before any service split is justified.

## Current Product Capabilities

### Parsing and Reporting

The system currently supports:

* parsing one `.swift` file
* parsing a directory recursively
* extracting imports, type declarations, functions, variables, and extensions
* returning syntax diagnostics as part of the contract
* exposing grammar and report versions in the output

### Structured Control Flow and Diagrams

The system currently supports:

* extracting structured steps for functions and methods
* representing `if/else`, `guard`, `while`, `for-in`, `repeat-while`, `switch`, `do/catch`, and `defer`
* expanding common trailing closures into inline control-flow steps
* rendering one HTML Nassi-Shneiderman diagram per source file
* rendering directory bundles with an index page

## Stakeholders

* business or product owners who need source intelligence that can evolve into future analysis products
* parser engineers who maintain grammar integration and source-model correctness
* tool integrators who consume parse reports or generated diagrams
* engineers and reviewers who use diagrams to understand unfamiliar control flow
* CI and operations maintainers who need deterministic, automatable CLI behavior

## In Scope

* lexical and syntactic parsing of Swift source files
* extraction of a stable structural model
* extraction of structured control flow from function bodies
* project-level orchestration across many files
* HTML diagram generation and bundle indexing
* diagnostics, versioning, and operational metadata
* explicit architectural seams for future extensions

## Out of Scope for the Current Version

* full semantic analysis
* type inference or name resolution
* build graph resolution and module compilation context
* mutation of source code or code generation back into Swift
* distributed deployment concerns
* long-lived persistence beyond process-local execution

## Domain Model

### Parsing Aggregate

`ParsingJob` is the main aggregate for parse-report workflows. It represents one execution over one or more `SourceUnit` values.

Its invariants are:

* a job must contain at least one source unit
* source unit identifiers must be unique within the job
* outcomes may only be recorded for source units that belong to the job
* a job can only complete after every source unit has an outcome
* outcomes cannot be appended after completion

### Source Asset

`SourceUnit` represents one Swift file with:

* a stable `SourceUnitId`
* a source `location`
* raw `content`

This is the shared input object for both parse-report and control-flow extraction use cases.

### Parse Outcome Model

The parse-report side of the domain uses:

* `GrammarVersion`
* `SyntaxDiagnostic`
* `StructuralElement`
* `ParseStatistics`
* `ParseOutcome`

`ParseOutcome` is explicit about the difference between:

* `SUCCEEDED`
* `SUCCEEDED_WITH_DIAGNOSTICS`
* `TECHNICAL_FAILURE`

That distinction matters because syntax diagnostics are a valid parser result, while technical failures are execution failures of the parsing pipeline itself.

### Control Flow Model

The diagram side of the domain is centered around immutable control-flow records:

* `ControlFlowDiagram`: one diagram per source file
* `FunctionControlFlow`: one function or method inside that file
* `ControlFlowStep`: base type for structured steps

Concrete step variants currently include:

* `ActionFlowStep`
* `IfFlowStep`
* `GuardFlowStep`
* `WhileFlowStep`
* `ForInFlowStep`
* `RepeatWhileFlowStep`
* `SwitchFlowStep`
* `DoCatchFlowStep`
* `DeferFlowStep`

This model is intentionally renderer-agnostic. The HTML Nassi renderer is only one consumer of it.

### Domain Events

The parse-report workflow emits lifecycle events:

* `ParsingJobStarted`
* `SourceUnitParsed`
* `SourceUnitParsingFailed`
* `ParsingJobCompleted`

Current reactions are intentionally small:

* structured lifecycle logging
* application-level status reporting
* keeping seams open for future metrics, tracing, persistence, or notifications

The diagram workflow currently does not emit a separate domain-event stream; it stays synchronous and request-scoped.

## Bounded Contexts

### Source Acquisition

Responsible for finding or loading `SourceUnit` values from a concrete source such as the filesystem.

### Syntax Parsing

Responsible for turning source text into parser output, diagnostics, and structural elements.

### Parse Orchestration

Responsible for `ParsingJob` lifecycle, outcome aggregation, and event publication.

### Control Flow Extraction

Responsible for converting function bodies into the stable `ControlFlowDiagram` model.

### Diagram Rendering

Responsible for converting control-flow models into human-readable artifacts such as HTML Nassi diagrams.

### Delivery

Responsible for CLI contracts, file writing, output paths, exit codes, and future delivery channels without leaking those concerns into the domain.

## Design Implications

The domain intentionally prefers explicit, immutable records over framework-driven models because the main product value is contract stability. The project can afford a modest amount of duplicated orchestration if it keeps the two core output types clear:

* parse reports for machines
* Nassi diagrams for humans
