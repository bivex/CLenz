"""ANTLR error listener adapters."""

from __future__ import annotations

from antlr4.error.ErrorListener import ErrorListener

from swifta.domain.model import DiagnosticSeverity, SyntaxDiagnostic


class CollectingErrorListener(ErrorListener):
    def __init__(self) -> None:
        super().__init__()
        self.diagnostics: list[SyntaxDiagnostic] = []

    def syntaxError(
        self,
        recognizer,
        offending_symbol,
        line: int,
        column: int,
        message: str,
        error,
    ) -> None:
        self.diagnostics.append(
            SyntaxDiagnostic(
                severity=DiagnosticSeverity.ERROR,
                message=message,
                line=line,
                column=column,
            )
        )

