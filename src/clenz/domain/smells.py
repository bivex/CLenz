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
    DEEP_NESTING = "deep_nesting"
    EMPTY_CONTROL_FLOW = "empty_control_flow"
    TOO_MANY_PARAMETERS = "too_many_parameters"
    RETURN_COUNT = "return_count"
    CYCLOMATIC_COMPLEXITY = "cyclomatic_complexity"
    TODO_COMMENT = "todo_comment"
    SWITCH_STATEMENTS = "switch_statements"
    MESSAGE_CHAINS = "message_chains"
    DATA_CLUMPS = "data_clumps"
    FEATURE_ENVY = "feature_envy"
    PRIMITIVE_OBSESSION = "primitive_obsession"
    MIDDLE_MAN = "middle_man"
    SPECULATIVE_GENERALITY = "speculative_generality"
    DIVERGENT_CHANGE = "divergent_change"
    SHOTGUN_SURGERY = "shotgun_surgery"
    TEMPORARY_FIELD = "temporary_field"
    REFUSED_BEQUEST = "refused_bequest"
    COMMENT_DENSITY = "comment_density"


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
