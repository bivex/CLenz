# System Boundaries and Interaction Contexts

## System Purpose

Swifta owns the flow from Swift source input to two output families:

* versioned parse reports for machines
* Nassi-Shneiderman HTML diagrams for humans

It is not a compiler, build system, or semantic analysis engine. It is a source-intelligence tool with explicit contracts around parsing, structural extraction, and control-flow visualization.

## Primary Actors and Neighbor Systems

### Primary Actors

* developers running the CLI locally
* CI pipelines validating or cataloging Swift source
* downstream tools that consume JSON parse output
* engineers opening generated HTML diagrams in a browser

### Neighbor Systems

* the local filesystem that stores Swift input files and generated artifacts
* the vendored ANTLR Swift grammar and generated parser runtime
* future analysis or indexing systems that may consume Swifta outputs
* browser runtimes that display generated HTML diagrams

## System Boundary

Inside the system boundary:

* source discovery and file loading
* parsing job orchestration
* parser invocation through ports
* structural extraction
* control-flow extraction
* diagnostics normalization
* HTML diagram rendering
* diagram bundle/index generation
* CLI response assembly and exit-code policy
* structured lifecycle logging for parse workflows

Outside the system boundary:

* IDE behavior and editor integrations
* the Swift compiler and build graph
* persistent storage systems
* metrics backends and tracing systems
* dashboards and monitoring products
* remote APIs and distributed orchestration

## Interaction Contexts

### 1. Source Discovery Context

Input adapters discover `.swift` files from a filesystem path and supply `SourceUnit` values to the application layer.

Inputs:

* file path
* directory path

Outputs:

* one `SourceUnit`
* or a sequence of `SourceUnit` values

### 2. Parse Report Context

The application layer asks the `SwiftSyntaxParser` port to parse a `SourceUnit` and maps the result into a stable report DTO.

Inputs:

* `ParseFileCommand`
* `ParseDirectoryCommand`

Outputs:

* `ParsingJobReportDTO`
* machine-readable JSON through the CLI

### 3. Control Flow Extraction Context

The application layer asks the `SwiftControlFlowExtractor` port to build a `ControlFlowDiagram` from a `SourceUnit`.

Inputs:

* raw Swift function bodies

Outputs:

* immutable control-flow records for each function in the file

### 4. Diagram Rendering Context

The application layer asks the `NassiDiagramRenderer` port to convert a `ControlFlowDiagram` into HTML.

Inputs:

* `BuildNassiDiagramCommand`
* `BuildNassiDirectoryCommand`

Outputs:

* per-file HTML documents
* directory bundles with an index page
* JSON metadata about generated artifacts

### 5. Observability Context

The parse-report workflow emits domain events that infrastructure currently turns into structured logs. This is a boundary seam for future metrics and tracing, not a full monitoring subsystem.

## Data Ownership

Swifta owns:

* the domain model
* the application DTO contracts
* the generated HTML document structure
* output path conventions for CLI-generated artifacts

Swifta does not own:

* the authoritative meaning of Swift semantics
* the lifecycle of source files outside the current execution
* browser rendering engines
* long-term storage of reports or diagrams

## Dependency Direction

Dependencies are one-directional:

* presentation -> application
* infrastructure -> application/domain ports
* application -> domain
* domain -> nothing outside itself

This direction applies equally to parse reporting and diagram generation. Both workflows are allowed to share ports such as `SourceRepository`, but neither workflow should make the domain depend on CLI or HTML concerns.
