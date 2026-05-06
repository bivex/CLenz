"""Domain events."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from swifta.domain.model import ParseStatus


@dataclass(frozen=True, slots=True)
class DomainEvent:
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class ParsingJobStarted(DomainEvent):
    job_id: str
    source_count: int


@dataclass(frozen=True, slots=True)
class SourceUnitParsed(DomainEvent):
    job_id: str
    source_location: str
    status: ParseStatus


@dataclass(frozen=True, slots=True)
class SourceUnitParsingFailed(DomainEvent):
    job_id: str
    source_location: str
    error_message: str


@dataclass(frozen=True, slots=True)
class ParsingJobCompleted(DomainEvent):
    job_id: str
    source_count: int
    succeeded_count: int
    succeeded_with_diagnostics_count: int
    technical_failure_count: int

