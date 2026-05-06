import json
import re
import subprocess
import sys
from pathlib import Path

from clenz.application.control_flow import (
    BuildNassiDiagramCommand,
    BuildNassiDirectoryCommand,
    NassiDiagramService,
)
from clenz.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ForFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    WhileFlowStep,
    DoWhileFlowStep,
)
from clenz.domain.model import SourceUnit, SourceUnitId
from clenz.infrastructure.antlr import control_flow_extractor as control_flow_module
from clenz.infrastructure.antlr.control_flow_extractor import AntlrCControlFlowExtractor
from clenz.infrastructure.filesystem.source_repository import FileSystemSourceRepository
from clenz.infrastructure.rendering.nassi_html_renderer import HtmlNassiDiagramRenderer


ROOT = Path(__file__).resolve().parent.parent


def _ensure_generated_parser() -> None:
    generated_parser = (
        ROOT / "src" / "clenz" / "infrastructure" / "antlr" / "generated" / "c" / "CParser.py"
    )
    if generated_parser.exists():
        return
    subprocess.run(
        [sys.executable, "scripts/generate_c_parser.py"],
        cwd=ROOT,
        check=True,
    )


def _build_service() -> NassiDiagramService:
    _ensure_generated_parser()
    return NassiDiagramService(
        source_repository=FileSystemSourceRepository(),
        extractor=AntlrCControlFlowExtractor(),
        renderer=HtmlNassiDiagramRenderer(),
    )


def test_nassi_service_builds_html_document() -> None:
    service = _build_service()
    document = service.build_file_diagram(
        BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.c"))
    )

    assert document.function_count == 2
    assert "score" in document.function_names
    assert "mathbox_normalize" in document.function_names
    assert "switch" in document.html


def test_nassi_service_builds_directory_bundle() -> None:
    service = _build_service()
    bundle = service.build_directory_diagrams(
        BuildNassiDirectoryCommand(root_path=str(ROOT / "tests" / "fixtures"))
    )

    assert bundle.document_count >= 2
    assert bundle.root_path == str((ROOT / "tests" / "fixtures").resolve())
    assert any(document.source_location.endswith("control_flow.c") for document in bundle.documents)


def test_nassi_service_handles_struct_container(tmp_path: Path) -> None:
    service = _build_service()
    source_path = tmp_path / "struct_fixture.c"
    source_path.write_text(
        """
struct Point {
    int x;
    int y;
};

int point_sum(struct Point *p) {
    return p->x + p->y;
}
""".strip(),
        encoding="utf-8",
    )

    document = service.build_file_diagram(BuildNassiDiagramCommand(path=str(source_path)))

    assert document.function_count == 1
    assert "point_sum" in document.function_names


def test_control_flow_extractor_uses_function_body_fast_path(monkeypatch) -> None:
    _ensure_generated_parser()
    extractor = AntlrCControlFlowExtractor()

    def _unexpected_full_parse(*args, **kwargs):
        raise AssertionError("unexpected full-file parse fallback")

    monkeypatch.setattr(control_flow_module, "parse_source_text", _unexpected_full_parse)

    source = SourceUnit(
        identifier=SourceUnitId("fast-path"),
        location="fast-path.c",
        content="""
int check(int value) {
    if (value > 0) {
        return value;
    }
    return 0;
}
""".strip(),
    )

    diagram = extractor.extract(source)

    assert len(diagram.functions) == 1
    assert diagram.functions[0].qualified_name == "check"
    assert len(diagram.functions[0].steps) == 2


def test_control_flow_extractor_shortcuts_action_only_bodies(monkeypatch) -> None:
    _ensure_generated_parser()
    extractor = AntlrCControlFlowExtractor()

    def _unexpected_full_parse(*args, **kwargs):
        raise AssertionError("unexpected full-file parse fallback")

    def _unexpected_code_block_parse(*args, **kwargs):
        raise AssertionError("unexpected code-block parse for action-only function")

    monkeypatch.setattr(control_flow_module, "parse_source_text", _unexpected_full_parse)
    monkeypatch.setattr(control_flow_module, "parse_code_block_text", _unexpected_code_block_parse)

    source = SourceUnit(
        identifier=SourceUnitId("action-only"),
        location="action-only.c",
        content="""
int normalize(int input) {
    int clamped = input < 0 ? 0 : input;
    return clamped;
}
""".strip(),
    )

    diagram = extractor.extract(source)

    assert len(diagram.functions) == 1
    assert diagram.functions[0].qualified_name == "normalize"
    assert len(diagram.functions[0].steps) == 2


def test_control_flow_extractor_summarizes_large_if_without_statement_parse(monkeypatch) -> None:
    _ensure_generated_parser()
    extractor = AntlrCControlFlowExtractor()

    def _unexpected_statement_parse(*args, **kwargs):
        raise AssertionError("unexpected statement parse for oversized if")

    monkeypatch.setattr(control_flow_module, "parse_statement_text", _unexpected_statement_parse)

    repeated_then = "\n".join(
        f'            int primaryLine{i} = value + {i};'
        for i in range(40)
    )
    repeated_else = "\n".join(
        f'            int fallbackLine{i} = {i};'
        for i in range(40)
    )
    source = SourceUnit(
        identifier=SourceUnitId("large-if"),
        location="large-if.c",
        content=f"""
void render(int value) {{
    if (value > 0) {{
{repeated_then}
        return;
    }} else {{
{repeated_else}
        return;
    }}
}}
""".strip(),
    )

    diagram = extractor.extract(source)

    assert len(diagram.functions) == 1
    assert len(diagram.functions[0].steps) == 1
    step = diagram.functions[0].steps[0]
    assert isinstance(step, IfFlowStep)
    assert step.then_steps
    assert step.else_steps


def test_nassi_cli_writes_html_file(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_path = tmp_path / "control_flow.html"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clenz.presentation.cli.main",
            "nassi-file",
            str(ROOT / "tests" / "fixtures" / "control_flow.c"),
            "--out",
            str(output_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["function_count"] == 2
    assert payload["output_path"] == str(output_path.resolve())
    assert output_path.exists()
    assert "Nassi-Shneiderman Control Flow" in output_path.read_text(encoding="utf-8")


def test_nassi_dir_cli_writes_html_bundle(tmp_path: Path) -> None:
    _ensure_generated_parser()
    output_dir = tmp_path / "nassi-bundle"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clenz.presentation.cli.main",
            "nassi-dir",
            str(ROOT / "tests" / "fixtures"),
            "--out",
            str(output_dir),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["document_count"] >= 2
    assert payload["output_dir"] == str(output_dir.resolve())
    assert payload["index_path"] == str((output_dir / "index.html").resolve())
    assert len(payload["documents"]) >= 2
    assert (output_dir / "index.html").exists()
    assert (output_dir / "control_flow.nassi.html").exists()
    assert "CLenz NSD Index" in (output_dir / "index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# C control flow tests
# ---------------------------------------------------------------------------


def _extract_steps(c_code: str):
    _ensure_generated_parser()
    extractor = AntlrCControlFlowExtractor()
    source = SourceUnit(
        identifier=SourceUnitId("c-snippet"),
        location="snippet.c",
        content=c_code.strip(),
    )
    diagram = extractor.extract(source)
    assert len(diagram.functions) >= 1, "expected at least one function"
    return diagram.functions[0].steps


class TestCControlFlow:
    """C-specific control flow constructs."""

    def test_if_else(self) -> None:
        steps = _extract_steps("""
int check(int x) {
    if (x > 0) {
        return x;
    } else {
        return 0;
    }
}
""")
        assert any(isinstance(s, IfFlowStep) for s in steps)

    def test_for_loop(self) -> None:
        steps = _extract_steps("""
int sum(int n) {
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += i;
    }
    return total;
}
""")
        assert any(isinstance(s, ForFlowStep) for s in steps)

    def test_while_loop(self) -> None:
        steps = _extract_steps("""
int countdown(int n) {
    while (n > 0) {
        n--;
    }
    return n;
}
""")
        assert any(isinstance(s, WhileFlowStep) for s in steps)

    def test_do_while_loop(self) -> None:
        steps = _extract_steps("""
int repeat_check(int n) {
    do {
        n--;
    } while (n > 10);
    return n;
}
""")
        assert any(isinstance(s, DoWhileFlowStep) for s in steps)


# ---------------------------------------------------------------------------
# If depth rendering tests
# ---------------------------------------------------------------------------


class TestIfDepthRendering:
    """If-cap rendering with depth-coded badges and colors."""

    def test_depth_badge_zero_is_empty(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(0) == ""

    def test_depth_badges_1_to_10_use_circled_digits(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(1) == " ①"
        assert renderer._depth_badge(5) == " ⑤"
        assert renderer._depth_badge(10) == " ⑩"

    def test_depth_badges_11_to_20_use_second_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(11) == " ⑪"
        assert renderer._depth_badge(15) == " ⑮"
        assert renderer._depth_badge(20) == " ⑳"

    def test_depth_badges_21_to_35_use_third_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(21) == " ㉑"
        assert renderer._depth_badge(30) == " ㉚"
        assert renderer._depth_badge(35) == " ㉟"

    def test_depth_badges_36_to_50_use_fourth_range(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        assert renderer._depth_badge(36) == " ㊱"
        assert renderer._depth_badge(40) == " ㊵"
        assert renderer._depth_badge(50) == " ㊿"

    def test_depth_css_generates_51_levels(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert ".ns-if-depth-0-triangle" in css
        assert ".ns-if-depth-50-triangle" in css

    def test_depth_css_cycles_colors(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert "var(--blue-dim)" in css
        assert "var(--green-dim)" in css
        assert "var(--purple-dim)" in css
        assert "var(--teal-dim)" in css
        assert "var(--amber-dim)" in css

    def test_depth_css_includes_body_gradients(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        css = renderer._depth_css()
        assert ".ns-if-depth-0-triangle" in css
        assert ".ns-if-depth-0-diagonal" in css

    def test_render_if_cap_at_depth_zero(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=0)
        assert 'class="ns-if-cap ns-if-depth-0"' in html
        assert '<svg class="ns-if-svg"' in html
        assert "x &gt; 0" in html
        assert 'width="400"' in html
        assert 'height="72"' in html

    def test_render_if_cap_at_depth_five(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=5)
        assert 'class="ns-if-cap ns-if-depth-5"' in html
        assert "⑤" in html

    def test_render_if_cap_at_depth_twenty_clips_badge(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=20)
        assert 'class="ns-if-cap ns-if-depth-20"' in html
        assert "⑳" in html

    def test_render_if_cap_at_depth_thirty_five(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=35)
        assert 'class="ns-if-cap ns-if-depth-35"' in html
        assert "㉟" in html

    def test_render_if_cap_at_depth_thirty_six_jumps_unicode(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=36)
        assert 'class="ns-if-cap ns-if-depth-36"' in html
        assert "㊱" in html

    def test_render_if_cap_at_depth_fifty(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=50)
        assert 'class="ns-if-cap ns-if-depth-50"' in html
        assert "㊿" in html

    def test_render_if_cap_clips_at_max_depth(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap("x > 0", depth=100)
        assert 'class="ns-if-cap ns-if-depth-50"' in html
        assert "㊿" in html

    def test_render_if_cap_expands_svg_for_long_conditions(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_if_cap(
            "request.user.profile.permissions.canAccessScopedResource && "
            "request.executionContext.region.isAllowedForThisOperation",
            depth=2,
        )
        match = re.search(r'viewBox="0 0 (\d+) (\d+)"', html)
        assert match is not None
        width = int(match.group(1))
        height = int(match.group(2))
        assert width > 400
        assert height >= 72

    def test_nested_ifs_in_html_output(self) -> None:
        service = _build_service()
        document = service.build_file_diagram(
            BuildNassiDiagramCommand(path=str(ROOT / "tests" / "fixtures" / "control_flow.c"))
        )
        html = document.html
        assert "ns-if-depth-" in html

    def test_nested_if_layout_css_can_expand_horizontally_for_deep_branches(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        diagram = ControlFlowDiagram(
            source_location="nested.c",
            functions=(
                FunctionControlFlow(
                    name="process_data",
                    signature="int process_data(int *data, int len)",
                    container=None,
                    steps=(
                        IfFlowStep(
                            condition="data != NULL",
                            then_steps=(
                                IfFlowStep(
                                    condition="len > 0",
                                    then_steps=(ActionFlowStep("handle_valid(data, len)"),),
                                    else_steps=(ActionFlowStep("return -1"),),
                                ),
                            ),
                            else_steps=(
                                IfFlowStep(
                                    condition="can_recover()",
                                    then_steps=(ActionFlowStep("recover()"),),
                                    else_steps=(ActionFlowStep("return -2"),),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )

        css = renderer.render(diagram).split("<style>", 1)[1].split("</style>", 1)[0]

        assert re.search(
            r"\.viewer \{[^}]*width: max-content;[^}]*min-width: min\(1200px, calc\(100vw - 48px\)\);",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.function-body > \.ns-sequence \{[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.ns-sequence \{[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert re.search(
            r"\.ns-branches \{[^}]*grid-template-columns: repeat\(2, max-content\);[^}]*width: max-content;[^}]*min-width: 100%;",
            css,
            re.DOTALL,
        )
        assert "580px" not in css

    def test_if_branches_use_green_and_red_highlight_classes(self) -> None:
        renderer = HtmlNassiDiagramRenderer()
        html = renderer._render_step(
            IfFlowStep(
                condition="flag",
                then_steps=(ActionFlowStep("return success"),),
                else_steps=(ActionFlowStep("return failure"),),
            ),
            depth=0,
        )

        assert 'class="ns-branch ns-branch-yes"' in html
        assert 'class="ns-branch ns-branch-no"' in html
        assert "rgba(158, 206, 106" in renderer.render(
            ControlFlowDiagram(
                source_location="branch-colors.c",
                functions=(
                    FunctionControlFlow(
                        name="f",
                        signature="int f(void)",
                        container=None,
                        steps=(
                            IfFlowStep(
                                condition="flag",
                                then_steps=(ActionFlowStep("return success"),),
                                else_steps=(ActionFlowStep("return failure"),),
                            ),
                        ),
                    ),
                ),
            )
        )
        assert "rgba(247, 118, 142" in renderer.render(
            ControlFlowDiagram(
                source_location="branch-colors.c",
                functions=(
                    FunctionControlFlow(
                        name="f",
                        signature="int f(void)",
                        container=None,
                        steps=(
                            IfFlowStep(
                                condition="flag",
                                then_steps=(ActionFlowStep("return success"),),
                                else_steps=(ActionFlowStep("return failure"),),
                            ),
                        ),
                    ),
                ),
            )
        )
