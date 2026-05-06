"""Core domain model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from swifta.domain.errors import (
    DuplicateSourceUnitError,
    EmptyParsingJobError,
    ParsingJobAlreadyCompletedError,
    ParsingJobNotCompleteError,
    UnknownSourceUnitError,
)


class DiagnosticSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"


class ParseStatus(StrEnum):
    SUCCEEDED = "succeeded"
    SUCCEEDED_WITH_DIAGNOSTICS = "succeeded_with_diagnostics"
    TECHNICAL_FAILURE = "technical_failure"


class StructuralElementKind(StrEnum):
    IMPORT = "import"
    TYPE_ALIAS = "type_alias"
    CONSTANT = "constant"
    VARIABLE = "variable"
    FUNCTION = "function"
    ENUM = "enum"
    STRUCT = "struct"
    CLASS = "class"
    PROTOCOL = "protocol"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class SourceUnitId:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("source unit id must not be blank")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class GrammarVersion:
    value: str

    def __post_init__(self) -> None:
        if not self.value.strip():
            raise ValueError("grammar version must not be blank")


@dataclass(frozen=True, slots=True)
class SourceUnit:
    identifier: SourceUnitId
    location: str
    content: str

    def __post_init__(self) -> None:
        if not self.location.strip():
            raise ValueError("source unit location must not be blank")


@dataclass(frozen=True, slots=True)
class SyntaxDiagnostic:
    severity: DiagnosticSeverity
    message: str
    line: int
    column: int


@dataclass(frozen=True, slots=True)
class StructuralElement:
    kind: StructuralElementKind
    name: str
    line: int
    column: int
    container: str | None = None
    signature: str | None = None


@dataclass(frozen=True, slots=True)
class ParseStatistics:
    token_count: int
    structural_element_count: int
    diagnostic_count: int
    elapsed_ms: float


@dataclass(frozen=True, slots=True)
class ParseOutcome:
    source_unit_id: SourceUnitId
    source_location: str
    grammar_version: GrammarVersion
    status: ParseStatus
    diagnostics: tuple[SyntaxDiagnostic, ...]
    structural_elements: tuple[StructuralElement, ...]
    statistics: ParseStatistics
    failure_message: str | None = None

    @staticmethod
    def success(
        *,
        source_unit: SourceUnit,
        grammar_version: GrammarVersion,
        diagnostics: tuple[SyntaxDiagnostic, ...],
        structural_elements: tuple[StructuralElement, ...],
        statistics: ParseStatistics,
    ) -> "ParseOutcome":
        status = (
            ParseStatus.SUCCEEDED_WITH_DIAGNOSTICS
            if diagnostics
            else ParseStatus.SUCCEEDED
        )
        return ParseOutcome(
            source_unit_id=source_unit.identifier,
            source_location=source_unit.location,
            grammar_version=grammar_version,
            status=status,
            diagnostics=diagnostics,
            structural_elements=structural_elements,
            statistics=statistics,
            failure_message=None,
        )

    @staticmethod
    def technical_failure(
        *,
        source_unit: SourceUnit,
        grammar_version: GrammarVersion,
        message: str,
        elapsed_ms: float = 0.0,
    ) -> "ParseOutcome":
        diagnostics = (
            SyntaxDiagnostic(
                severity=DiagnosticSeverity.ERROR,
                message=message,
                line=0,
                column=0,
            ),
        )
        return ParseOutcome(
            source_unit_id=source_unit.identifier,
            source_location=source_unit.location,
            grammar_version=grammar_version,
            status=ParseStatus.TECHNICAL_FAILURE,
            diagnostics=diagnostics,
            structural_elements=(),
            statistics=ParseStatistics(
                token_count=0,
                structural_element_count=0,
                diagnostic_count=1,
                elapsed_ms=elapsed_ms,
            ),
            failure_message=message,
        )


@dataclass(slots=True)
class ParsingJob:
    job_id: str
    created_at: datetime
    source_units: tuple[SourceUnit, ...]
    outcomes: dict[SourceUnitId, ParseOutcome] = field(default_factory=dict)
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.source_units:
            raise EmptyParsingJobError("a parsing job must contain at least one source unit")

        identifiers = [source_unit.identifier for source_unit in self.source_units]
        if len(set(identifiers)) != len(identifiers):
            raise DuplicateSourceUnitError("source unit identifiers must be unique inside a job")

    def record_outcome(self, outcome: ParseOutcome) -> None:
        if self.completed_at is not None:
            raise ParsingJobAlreadyCompletedError("cannot record outcomes after job completion")

        known_ids = {source_unit.identifier for source_unit in self.source_units}
        if outcome.source_unit_id not in known_ids:
            raise UnknownSourceUnitError(
                f"source unit {outcome.source_unit_id} does not belong to job {self.job_id}"
            )

        self.outcomes[outcome.source_unit_id] = outcome

    def complete(self, completed_at: datetime) -> None:
        if len(self.outcomes) != len(self.source_units):
            raise ParsingJobNotCompleteError(
                "cannot complete parsing job before every source unit has an outcome"
            )
        self.completed_at = completed_at

    @property
    def source_count(self) -> int:
        return len(self.source_units)

    @property
    def succeeded_count(self) -> int:
        return sum(1 for outcome in self.outcomes.values() if outcome.status == ParseStatus.SUCCEEDED)

    @property
    def succeeded_with_diagnostics_count(self) -> int:
        return sum(
            1
            for outcome in self.outcomes.values()
            if outcome.status == ParseStatus.SUCCEEDED_WITH_DIAGNOSTICS
        )

    @property
    def technical_failure_count(self) -> int:
        return sum(
            1
            for outcome in self.outcomes.values()
            if outcome.status == ParseStatus.TECHNICAL_FAILURE
        )

    @property
    def ordered_outcomes(self) -> tuple[ParseOutcome, ...]:
        return tuple(self.outcomes[source_unit.identifier] for source_unit in self.source_units)

