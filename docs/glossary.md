# Glossary and Ubiquitous Language

## Terms

`Parsing Job`
: One execution that processes one or more source units and produces aggregated parse outcomes.

`Source Unit`
: One Swift source file treated as an addressable input with stable identity, location, and content.

`Parse Outcome`
: The immutable result of parsing one source unit, including status, diagnostics, structural elements, and statistics.

`Parse Status`
: The outcome classification for one source unit: succeeded, succeeded with diagnostics, or technical failure.

`Structural Model`
: The normalized representation of source structure that downstream automation can consume.

`Structural Element`
: One extracted item in the structural model, such as an import, type alias, class, struct, enum, protocol, extension, function, variable, or constant.

`Syntax Diagnostic`
: A parser-reported issue with location, severity, and message.

`Grammar Version`
: The version label of the grammar contract used to parse a source unit.

`Report Schema Version`
: The version label of the parse-report contract exposed to consumers.

`Control Flow Diagram`
: The immutable domain model that represents structured control flow for one source file.

`Function Control Flow`
: The control-flow representation for one function or method inside a `ControlFlowDiagram`.

`Control Flow Step`
: One structured statement-like unit in the control-flow model.

`Nassi Diagram`
: The HTML visualization of a `ControlFlowDiagram` using Nassi-Shneiderman-style layout.

`Nassi Diagram Document`
: The generated HTML artifact and metadata for one source file.

`Nassi Diagram Bundle`
: A directory-level result containing multiple diagram documents plus an index page.

`Port`
: An inward-facing interface owned by the domain or application layer.

`Adapter`
: An outward-facing implementation of a port that talks to a concrete technology.

`Source Repository`
: The boundary that loads one file or enumerates Swift files from a root path.

`Swift Syntax Parser`
: The boundary that turns a `SourceUnit` into a `ParseOutcome`.

`Swift Control Flow Extractor`
: The boundary that turns a `SourceUnit` into a `ControlFlowDiagram`.

`Nassi Diagram Renderer`
: The boundary that turns a `ControlFlowDiagram` into HTML.

`Boundary Validation`
: Validation performed when data enters or leaves the system.

## Naming Rules

* Use `ParsingJob`, not `TaskManager`.
* Use `SourceUnit`, not `FileData`.
* Use `ParseOutcome`, not `ResultBlob`.
* Use `StructuralElement`, not `NodeInfo`.
* Use `ControlFlowDiagram`, not `FlowTree`.
* Use `NassiDiagramService`, not `HtmlGenerator`.
* Use `SwiftSyntaxParser`, not `ParserHelper`.
* Use `SwiftControlFlowExtractor`, not `BranchScanner`.
* Use `SourceRepository`, not `FileUtils`.
