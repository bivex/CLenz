"""Application DTOs."""

from __future__ import annotations

from dataclasses import dataclass


REPORT_SCHEMA_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class ParseFileCommand:
    path: str


@dataclass(frozen=True, slots=True)
class ParseDirectoryCommand:
    root_path: str


@dataclass(frozen=True, slots=True)
class SyntaxDiagnosticDTO:
    severity: str
    message: str
    line: int
    column: int

    def to_dict(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "message": self.message,
            "line": self.line,
            "column": self.column,
        }


@dataclass(frozen=True, slots=True)
class StructuralElementDTO:
    kind: str
    name: str
    line: int
    column: int
    container: str | None
    signature: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "line": self.line,
            "column": self.column,
            "container": self.container,
            "signature": self.signature,
        }


@dataclass(frozen=True, slots=True)
class ParseStatisticsDTO:
    token_count: int
    structural_element_count: int
    diagnostic_count: int
    elapsed_ms: float

    def to_dict(self) -> dict[str, object]:
        return {
            "token_count": self.token_count,
            "structural_element_count": self.structural_element_count,
            "diagnostic_count": self.diagnostic_count,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass(frozen=True, slots=True)
class SourceParseReportDTO:
    source_location: str
    grammar_version: str
    status: str
    diagnostics: tuple[SyntaxDiagnosticDTO, ...]
    structural_elements: tuple[StructuralElementDTO, ...]
    statistics: ParseStatisticsDTO
    failure_message: str | None

    def to_dict(self) -> dict[str, object]:
        return {
            "source_location": self.source_location,
            "grammar_version": self.grammar_version,
            "status": self.status,
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
            "structural_elements": [element.to_dict() for element in self.structural_elements],
            "statistics": self.statistics.to_dict(),
            "failure_message": self.failure_message,
        }


@dataclass(frozen=True, slots=True)
class ParsingJobSummaryDTO:
    source_count: int
    succeeded_count: int
    succeeded_with_diagnostics_count: int
    technical_failure_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source_count": self.source_count,
            "succeeded_count": self.succeeded_count,
            "succeeded_with_diagnostics_count": self.succeeded_with_diagnostics_count,
            "technical_failure_count": self.technical_failure_count,
        }


@dataclass(frozen=True, slots=True)
class ParsingJobReportDTO:
    schema_version: str
    job_id: str
    created_at: str
    completed_at: str
    summary: ParsingJobSummaryDTO
    sources: tuple[SourceParseReportDTO, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "summary": self.summary.to_dict(),
            "sources": [source.to_dict() for source in self.sources],
        }

