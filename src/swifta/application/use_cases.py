"""Use cases and orchestration services."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from swifta.application.dto import (
    REPORT_SCHEMA_VERSION,
    ParseDirectoryCommand,
    ParseFileCommand,
    ParseStatisticsDTO,
    ParsingJobReportDTO,
    ParsingJobSummaryDTO,
    SourceParseReportDTO,
    StructuralElementDTO,
    SyntaxDiagnosticDTO,
)
from swifta.domain.events import (
    ParsingJobCompleted,
    ParsingJobStarted,
    SourceUnitParsed,
    SourceUnitParsingFailed,
)
from swifta.domain.model import ParseOutcome, ParseStatus, ParsingJob, SourceUnit
from swifta.domain.ports import (
    Clock,
    DomainEventPublisher,
    ParsingJobRepository,
    SourceRepository,
    SwiftSyntaxParser,
)


@dataclass(slots=True)
class ParsingJobService:
    source_repository: SourceRepository
    parser: SwiftSyntaxParser
    event_publisher: DomainEventPublisher
    clock: Clock
    job_repository: ParsingJobRepository

    def parse_file(self, command: ParseFileCommand) -> ParsingJobReportDTO:
        source_unit = self.source_repository.load_file(command.path)
        return self._run_job((source_unit,))

    def parse_directory(self, command: ParseDirectoryCommand) -> ParsingJobReportDTO:
        source_units = tuple(self.source_repository.list_swift_sources(command.root_path))
        return self._run_job(source_units)

    def _run_job(self, source_units: tuple[SourceUnit, ...]) -> ParsingJobReportDTO:
        created_at = self.clock.now()
        job = ParsingJob(
            job_id=f"parse-{uuid4()}",
            created_at=created_at,
            source_units=source_units,
        )
        self.event_publisher.publish(
            ParsingJobStarted(
                occurred_at=created_at,
                job_id=job.job_id,
                source_count=job.source_count,
            )
        )

        for source_unit in source_units:
            outcome = self.parser.parse(source_unit)
            job.record_outcome(outcome)
            self._publish_source_event(job.job_id, outcome)

        completed_at = self.clock.now()
        job.complete(completed_at)
        self.job_repository.save(job)
        self.event_publisher.publish(
            ParsingJobCompleted(
                occurred_at=completed_at,
                job_id=job.job_id,
                source_count=job.source_count,
                succeeded_count=job.succeeded_count,
                succeeded_with_diagnostics_count=job.succeeded_with_diagnostics_count,
                technical_failure_count=job.technical_failure_count,
            )
        )
        return _map_job_to_report(job)

    def _publish_source_event(self, job_id: str, outcome: ParseOutcome) -> None:
        occurred_at = self.clock.now()
        if outcome.status == ParseStatus.TECHNICAL_FAILURE:
            self.event_publisher.publish(
                SourceUnitParsingFailed(
                    occurred_at=occurred_at,
                    job_id=job_id,
                    source_location=outcome.source_location,
                    error_message=outcome.failure_message or "technical failure",
                )
            )
            return

        self.event_publisher.publish(
            SourceUnitParsed(
                occurred_at=occurred_at,
                job_id=job_id,
                source_location=outcome.source_location,
                status=outcome.status,
            )
        )


def _map_job_to_report(job: ParsingJob) -> ParsingJobReportDTO:
    sources = tuple(_map_source_outcome(outcome) for outcome in job.ordered_outcomes)
    return ParsingJobReportDTO(
        schema_version=REPORT_SCHEMA_VERSION,
        job_id=job.job_id,
        created_at=job.created_at.isoformat(),
        completed_at=job.completed_at.isoformat() if job.completed_at else "",
        summary=ParsingJobSummaryDTO(
            source_count=job.source_count,
            succeeded_count=job.succeeded_count,
            succeeded_with_diagnostics_count=job.succeeded_with_diagnostics_count,
            technical_failure_count=job.technical_failure_count,
        ),
        sources=sources,
    )


def _map_source_outcome(outcome: ParseOutcome) -> SourceParseReportDTO:
    return SourceParseReportDTO(
        source_location=outcome.source_location,
        grammar_version=outcome.grammar_version.value,
        status=outcome.status.value,
        diagnostics=tuple(
            SyntaxDiagnosticDTO(
                severity=diagnostic.severity.value,
                message=diagnostic.message,
                line=diagnostic.line,
                column=diagnostic.column,
            )
            for diagnostic in outcome.diagnostics
        ),
        structural_elements=tuple(
            StructuralElementDTO(
                kind=element.kind.value,
                name=element.name,
                line=element.line,
                column=element.column,
                container=element.container,
                signature=element.signature,
            )
            for element in outcome.structural_elements
        ),
        statistics=ParseStatisticsDTO(
            token_count=outcome.statistics.token_count,
            structural_element_count=outcome.statistics.structural_element_count,
            diagnostic_count=outcome.statistics.diagnostic_count,
            elapsed_ms=outcome.statistics.elapsed_ms,
        ),
        failure_message=outcome.failure_message,
    )

