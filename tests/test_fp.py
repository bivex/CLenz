import pytest
from clenz.domain.model import SourceUnit, SourceUnitId
from clenz.domain.smells import CodeSmell, SmellKind
from clenz.infrastructure.linting.smell_scanner import AntlrCSmellScanner

def _scan(source_text: str) -> list[CodeSmell]:
    source = SourceUnit(identifier=SourceUnitId("test.c"), location="test.c", content=source_text.strip())
    scanner = AntlrCSmellScanner()
    report = scanner.scan(source)
    return report.smells

def test_uninit_var_in_struct():
    smells = _scan("struct Point { int x; int y; };")
    uninit = [s for s in smells if s.kind == SmellKind.UNINITIALIZED_VAR]
    assert not uninit, uninit

def test_global_const():
    smells = _scan("const int MAX = 100;")
    gv = [s for s in smells if s.kind == SmellKind.GLOBAL_VARIABLE]
    assert not gv, gv

