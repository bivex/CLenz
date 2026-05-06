"""Ports owned by the inner layers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Sequence

from clenz.domain.control_flow import ControlFlowDiagram
from clenz.domain.events import DomainEvent
from clenz.domain.model import GrammarVersion, ParseOutcome, ParsingJob, SourceUnit


class SourceRepository(ABC):
    @abstractmethod
    def load_file(self, path: str) -> SourceUnit:
        raise NotImplementedError

    @abstractmethod
    def list_c_sources(self, root_path: str) -> Sequence[SourceUnit]:
        raise NotImplementedError


class ParsingJobRepository(ABC):
    @abstractmethod
    def save(self, job: ParsingJob) -> None:
        raise NotImplementedError


class CSyntaxParser(ABC):
    @property
    @abstractmethod
    def grammar_version(self) -> GrammarVersion:
        raise NotImplementedError

    @abstractmethod
    def parse(self, source_unit: SourceUnit) -> ParseOutcome:
        raise NotImplementedError


class CControlFlowExtractor(ABC):
    @abstractmethod
    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        raise NotImplementedError


class NassiDiagramRenderer(ABC):
    @abstractmethod
    def render(self, diagram: ControlFlowDiagram) -> str:
        raise NotImplementedError


class DomainEventPublisher(ABC):
    @abstractmethod
    def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError


class Clock(ABC):
    @abstractmethod
    def now(self) -> datetime:
        raise NotImplementedError
