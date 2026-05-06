"""Domain types for C code smell detection."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class SmellSeverity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class SmellKind(StrEnum):
    GLOBAL_VARIABLE = "global_variable"
    LONG_FUNCTION = "long_function"
    MAGIC_NUMBER = "magic_number"
    UNCHECKED_MALLOC = "unchecked_malloc"
    MEMORY_LEAK_RISK = "memory_leak_risk"
    UNSAFE_FUNCTION = "unsafe_function"
    MISSING_CONST = "missing_const"
    UNINITIALIZED_VAR = "uninitialized_var"
    UNCHECKED_RETURN = "unchecked_return"
    SHORT_NAME = "short_name"
    LARGE_FILE = "large_file"
    MIXED_ABSTRACTION = "mixed_abstraction"


@dataclass(frozen=True, slots=True)
class CodeSmell:
    kind: SmellKind
    severity: SmellSeverity
    message: str
    line: int
    column: int = 0


@dataclass(frozen=True, slots=True)
class SmellReport:
    source_location: str
    smells: tuple[CodeSmell, ...]
    line_count: int
    function_count: int

    @property
    def error_count(self) -> int:
        return sum(1 for s in self.smells if s.severity == SmellSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for s in self.smells if s.severity == SmellSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for s in self.smells if s.severity == SmellSeverity.INFO)

    @property
    def is_clean(self) -> bool:
        return len(self.smells) == 0
