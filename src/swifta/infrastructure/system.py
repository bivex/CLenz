"""Generic infrastructure adapters."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from enum import Enum

from swifta.domain.events import DomainEvent
from swifta.domain.model import ParsingJob
from swifta.domain.ports import Clock, DomainEventPublisher, ParsingJobRepository


class SystemClock(Clock):
    def now(self) -> datetime:
        return datetime.now(tz=UTC)


class InMemoryParsingJobRepository(ParsingJobRepository):
    def __init__(self) -> None:
        self._jobs: dict[str, ParsingJob] = {}

    def save(self, job: ParsingJob) -> None:
        self._jobs[job.job_id] = job


class StructuredLoggingEventPublisher(DomainEventPublisher):
    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("swifta.events")

    def publish(self, event: DomainEvent) -> None:
        payload = _serialize(event)
        self._logger.info("%s", json.dumps(payload, sort_keys=True))


def configure_logging(verbose: bool = False) -> None:
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level)


def _serialize(value: object) -> object:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value):
        return {key: _serialize(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    return value

