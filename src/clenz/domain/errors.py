"""Domain and application-facing errors."""


class ClenzError(Exception):
    """Base type for all system errors."""


class BusinessRuleViolation(ClenzError):
    """Raised when a domain invariant is violated."""


class EmptyParsingJobError(BusinessRuleViolation):
    """Raised when a parsing job has no source units."""


class DuplicateSourceUnitError(BusinessRuleViolation):
    """Raised when the same source unit is added twice to one job."""


class UnknownSourceUnitError(BusinessRuleViolation):
    """Raised when an outcome is recorded for an unknown source unit."""


class ParsingJobAlreadyCompletedError(BusinessRuleViolation):
    """Raised when mutating a completed parsing job."""


class ParsingJobNotCompleteError(BusinessRuleViolation):
    """Raised when completing a job before every outcome is known."""


class InputValidationError(ClenzError):
    """Raised for invalid user input at the system boundary."""


class SourceAccessError(ClenzError):
    """Raised when the system cannot access or decode a source file."""


class GeneratedParserNotAvailableError(ClenzError):
    """Raised when generated ANTLR artifacts are missing.

    Run ``uv run python scripts/generate_c_parser.py`` to regenerate them.
    """

