"""Render structured control flow as Nassi-Shneiderman HTML."""

from __future__ import annotations

from html import escape
from math import ceil
import re

from swifta.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    DeferFlowStep,
    DoCatchFlowStep,
    ForInFlowStep,
    GuardFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WhileFlowStep,
)
from swifta.domain.ports import NassiDiagramRenderer


class HtmlNassiDiagramRenderer(NassiDiagramRenderer):
    def _depth_badge(self, i: int) -> str:
        if i == 0:
            return ""
        if i <= 20:
            return f" {chr(0x2460 + i - 1)}"
        if i <= 35:
            return f" {chr(0x3251 + i - 21)}"
        return f" {chr(0x32B1 + i - 36)}"

    def _depth_css(self) -> str:
        colors = ["blue", "green", "purple", "teal", "amber"]
        rules = []
        for i in range(51):
            c = colors[i % 5]
            rules.append(f"      .ns-if-depth-{i}-triangle {{ fill: var(--{c}-dim); stroke: var(--{c}); }}")
            rules.append(f"      .ns-if-depth-{i}-diagonal {{ stroke: var(--{c}); }}")
        return "\n".join(rules)

    def render(self, diagram: ControlFlowDiagram) -> str:
        sections = "".join(self._render_function(function) for function in diagram.functions)
        if not sections:
            sections = '<section class="function-panel"><p class="empty-file">No functions found.</p></section>'

        return f"""<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Nassi-Shneiderman Control Flow</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
      :root {{
        /* Palette — editor-first dark */
        --bg:          #0a0f18;
        --bg-accent:   #10182a;
        --surface:     #111827;
        --surface-2:   #172131;
        --surface-3:   #1c2940;
        --surface-4:   #233452;
        --border:      #2b3b59;
        --border-strong: #3f5378;
        --border-soft: #182338;
        --text:        #cfd8f6;
        --text-bright: #f4f7ff;
        --muted:       #8e9bbb;
        --shadow:      0 24px 72px rgba(3, 8, 18, 0.56);

        /* Accent colours */
        --blue:        #82aaff;
        --blue-dim:    #243b69;
        --green:       #a6da95;
        --green-dim:   #163628;
        --red:         #ff93a9;
        --red-dim:     #371925;
        --orange:      #ffb86b;
        --orange-dim:  #37230f;
        --teal:        #56d4dd;
        --teal-dim:    #11343b;
        --purple:      #c4a7ff;
        --purple-dim:  #2a1d41;
        --amber:       #f1ca7a;
        --amber-dim:   #39290f;

        /* Block fills */
        --loop-fill:   #132033;
        --switch-fill: #102529;
        --guard-fill:  #23190c;
        --do-fill:     #1a1624;
        --defer-fill:  #241d0d;
        --yes-fill:    #102217;
        --no-fill:     #251019;
        --action-fill: var(--surface-2);
        --note-fill:   #101720;

        /* Code font */
        --mono: "JetBrains Mono", "Fira Code", "Cascadia Code", "SF Mono", "Menlo", monospace;
        --ui:   "IBM Plex Sans", -apple-system, "Segoe UI", system-ui, sans-serif;
      }}
      * {{ box-sizing: border-box; margin: 0; padding: 0; }}
      body {{
        font-family: var(--ui);
        font-size: 14px;
        color: var(--text);
        background:
          radial-gradient(circle at top, rgba(130, 170, 255, 0.12), transparent 28%),
          linear-gradient(180deg, var(--bg) 0%, #0c121d 100%);
        padding: 24px;
        min-height: 100vh;
        overflow-x: auto;
        color-scheme: dark;
        -webkit-font-smoothing: antialiased;
        text-rendering: optimizeLegibility;
      }}
      /* ── Viewer shell ── */
      .viewer {{
        width: max-content;
        min-width: min(1200px, calc(100vw - 48px));
        margin: 0 auto;
        border: 1px solid var(--border-strong);
        border-radius: 14px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
          var(--surface);
        box-shadow: var(--shadow);
        overflow: hidden;
      }}
      .titlebar {{
        padding: 10px 16px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0)),
          var(--surface-3);
        border-bottom: 1px solid var(--border-strong);
        display: flex;
        align-items: center;
        gap: 10px;
      }}
      .titlebar-icon {{
        width: 14px; height: 14px;
        border-radius: 50%;
        background: var(--blue-dim);
        border: 1px solid var(--blue);
        flex-shrink: 0;
      }}
      .titlebar-text {{
        font-size: 13.5px;
        font-weight: 600;
        color: var(--text-bright);
        letter-spacing: 0.01em;
      }}
      .toolbar {{
        padding: 9px 16px;
        border-bottom: 1px solid var(--border-soft);
        background:
          linear-gradient(180deg, rgba(255,255,255,0.02), rgba(255,255,255,0)),
          var(--surface);
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        align-items: baseline;
      }}
      .toolbar-label {{
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: var(--blue);
        background: rgba(130, 170, 255, 0.14);
        border: 1px solid rgba(130, 170, 255, 0.3);
        border-radius: 999px;
        padding: 3px 8px;
        white-space: nowrap;
      }}
      .toolbar-path {{
        font-family: var(--mono);
        font-size: 12px;
        color: var(--muted);
        overflow-wrap: anywhere;
      }}
      /* ── Viewer body ── */
      .viewer-body {{
        padding: 16px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0) 180px),
          var(--bg);
      }}
      /* ── Function panel ── */
      .function-panel {{
        margin-bottom: 16px;
        border: 1px solid var(--border);
        border-radius: 10px;
        background: rgba(10, 15, 24, 0.72);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
        overflow: hidden;
      }}
      .function-panel:last-child {{ margin-bottom: 0; }}
      .function-head {{
        padding: 12px 16px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0.01)),
          var(--surface-3);
        border-bottom: 1px solid var(--border-strong);
      }}
      .function-title {{
        font-size: 15px;
        font-weight: 600;
        color: var(--text-bright);
        line-height: 1.3;
      }}
      .function-signature {{
        margin-top: 5px;
        font-family: var(--mono);
        font-size: 12px;
        line-height: 1.6;
        color: var(--muted);
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .function-body {{
        padding: 12px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.01), rgba(255,255,255,0)),
          rgba(7, 11, 18, 0.84);
      }}
      .function-body > .ns-sequence {{
        width: max-content;
        min-width: 100%;
      }}
      /* ── Node sequence ── */
      .ns-sequence {{
        display: flex;
        flex-direction: column;
        width: max-content;
        min-width: 100%;
      }}
      .ns-sequence > .ns-node + .ns-node,
      .ns-cases > .case + .case,
      .ns-catches > .ns-node + .ns-node {{
        margin-top: -1px;
      }}
      .ns-node {{
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--action-fill);
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.02);
      }}
      /* ── Block headers/footers ── */
      .ns-header,
      .ns-footer,
      .case-title {{
        padding: 7px 12px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0)),
          var(--blue-dim);
        color: var(--text-bright);
        font-family: var(--mono);
        font-size: 12px;
        font-weight: 500;
        line-height: 1.4;
        border-bottom: 1px solid var(--border-strong);
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .ns-footer {{
        border-top: 1px solid var(--border);
        border-bottom: 0;
      }}
      /* ── Action label ── */
      .ns-label,
      .empty,
      .ns-note {{
        padding: 8px 12px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.015), rgba(255,255,255,0)),
          var(--action-fill);
      }}
      .action-text {{
        display: block;
        font-family: var(--mono);
        font-size: 13px;
        line-height: 1.72;
        color: var(--text-bright);
        letter-spacing: -0.01em;
        font-variant-ligatures: none;
        tab-size: 2;
        white-space: pre-wrap;
        overflow-wrap: anywhere;
      }}
      /* ── Block type colours ── */
      .ns-guard   {{ background: var(--guard-fill); }}
      .ns-loop,
      .ns-repeat  {{ background: var(--loop-fill); }}
      .ns-switch  {{ background: var(--switch-fill); }}
      .ns-do-catch {{ background: var(--do-fill); }}
      .ns-defer   {{ background: var(--defer-fill); }}

      .ns-guard   > .ns-header {{ background: var(--orange-dim); color: var(--orange); }}
      .ns-switch  > .ns-header,
      .case-title              {{ background: var(--teal-dim);   color: var(--teal);   }}
      .ns-do-catch > .ns-header {{ background: var(--purple-dim); color: var(--purple); }}
      .ns-defer   > .ns-header {{ background: var(--amber-dim);  color: var(--amber);  }}

      /* Left accent stripes */
      .ns-node.ns-loop,
      .ns-node.ns-repeat  {{ border-left: 3px solid var(--blue); }}
      .ns-node.ns-guard   {{ border-left: 3px solid var(--orange); }}
      .ns-node.ns-switch  {{ border-left: 3px solid var(--teal); }}
      .ns-node.ns-do-catch {{ border-left: 3px solid var(--purple); }}
      .ns-node.ns-defer   {{ border-left: 3px solid var(--amber); }}

      /* Depth tinting */
      .ns-depth-1 > .ns-node {{ background-color: rgba(255,255,255,0.012); }}
      .ns-depth-2 > .ns-node {{ background-color: rgba(255,255,255,0.020); }}
      .ns-depth-3 > .ns-node {{ background-color: rgba(255,255,255,0.028); }}

      /* ── If/else branches (classic NS diagram with SVG) ── */
      .ns-if-cap {{
        border-bottom: 1px solid var(--border);
        line-height: 0;
      }}
      .ns-if-svg {{
        display: block;
        height: auto;
      }}
      .ns-if-triangle {{
        fill: var(--blue-dim);
        stroke: var(--border);
        stroke-width: 1;
      }}
      .ns-if-diagonal {{
        stroke: var(--border);
        stroke-width: 1;
      }}
      .ns-if-condition-fo {{
        overflow: hidden;
      }}
      .ns-if-condition-text {{
        font-family: var(--mono);
        font-size: 13px;
        font-weight: 500;
        color: var(--text-bright);
        text-align: center;
        word-break: break-word;
        overflow-wrap: anywhere;
        line-height: 1.3;
        padding: 4px 8px;
      }}
      .ns-if-label-yes {{
        font-family: var(--mono);
        font-size: 11px;
        font-weight: 700;
        fill: var(--green);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }}
      .ns-if-label-no {{
        font-family: var(--mono);
        font-size: 11px;
        font-weight: 700;
        fill: var(--red);
        text-transform: uppercase;
        letter-spacing: 0.06em;
      }}

      /* ── Switch/case (classic NS diagram) ── */
      .ns-switch-header {{
        padding: 9px 12px;
        background:
          linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0)),
          var(--teal-dim);
        color: var(--text-bright);
        font-family: var(--mono);
        font-size: 12px;
        font-weight: 500;
        border-bottom: 1px solid var(--border-strong);
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .ns-switch-cases {{
        display: grid;
        grid-auto-flow: column;
        grid-auto-columns: minmax(140px, max-content);
        background: var(--bg);
        width: max-content;
        min-width: 100%;
      }}
      .ns-switch-case-col {{
        border-right: 1px solid var(--border);
        min-width: 140px;
        display: flex;
        flex-direction: column;
      }}
      .ns-switch-case-col:last-child {{
        border-right: none;
      }}
      .ns-switch-case-value {{
        padding: 9px 12px;
        background: rgba(16, 24, 39, 0.86);
        color: var(--teal);
        font-family: var(--mono);
        font-size: 11px;
        font-weight: 600;
        border-bottom: 1px solid var(--border-strong);
        text-align: center;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .ns-switch-case-body {{
        padding: 0;
        background: var(--bg);
        min-height: 40px;
      }}
      .ns-switch-case-body .ns-sequence {{
        padding: 8px;
      }}

      /* Depth-coded if-cap triangles and diagonals (0-50, cycling blue→green→purple→teal→amber) */
{self._depth_css()}

      .ns-branches {{
        display: grid;
        grid-template-columns: repeat(2, max-content);
        background: var(--surface-2);
        width: max-content;
        min-width: 100%;
      }}
      .ns-branches-single {{ grid-template-columns: max-content; }}
      .ns-branch {{
        border-left: 2px solid var(--border);
        background: var(--surface-2);
      }}
      .ns-branch-yes {{
        background: rgba(158, 206, 106, 0.08);
      }}
      .ns-branch-no {{
        background: rgba(247, 118, 142, 0.08);
      }}
      .ns-branch-yes > .ns-sequence > .ns-node {{
        background: rgba(158, 206, 106, 0.12);
      }}
      .ns-branch-no > .ns-sequence > .ns-node {{
        background: rgba(247, 118, 142, 0.12);
      }}
      .ns-branch-yes .ns-label,
      .ns-branch-yes .empty,
      .ns-branch-yes .ns-note {{
        background: rgba(158, 206, 106, 0.14);
      }}
      .ns-branch-no .ns-label,
      .ns-branch-no .empty,
      .ns-branch-no .ns-note {{
        background: rgba(247, 118, 142, 0.14);
      }}
      .ns-branch-yes > .ns-branch-title {{
        background: rgba(158, 206, 106, 0.2);
        color: var(--green);
      }}
      .ns-branch-no > .ns-branch-title {{
        background: rgba(247, 118, 142, 0.18);
        color: var(--red);
      }}
      .ns-branch:first-child {{ border-left: 0; }}
      .ns-branch-title {{
        padding: 7px 12px;
        border-bottom: 1px solid var(--border);
        background: rgba(18, 26, 41, 0.92);
        color: var(--muted);
        font-size: 10.5px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
      }}
      .ns-cases {{ background: var(--surface-2); }}
      .case {{ border-top: 1px solid var(--border); }}
      .case:first-child {{ border-top: 0; }}
      .ns-catches {{ border-top: 1px solid var(--border); }}

      .empty {{
        color: var(--muted);
        font-style: italic;
        font-size: 12px;
        background: rgba(20, 28, 41, 0.92);
      }}
      .ns-note {{
        color: var(--muted);
        font-family: var(--mono);
        font-size: 11px;
        font-style: italic;
        background: var(--note-fill);
        border-top: 1px solid var(--border);
        padding: 8px 12px;
      }}
      .empty-file {{
        padding: 24px;
        color: var(--muted);
      }}

      @media (max-width: 800px) {{
        body {{ padding: 12px; }}
        .viewer {{
          width: auto;
          min-width: 0;
        }}
        .viewer-body {{ padding: 8px; }}
        .function-body {{
          padding: 6px;
          overflow-x: auto;
        }}
        .function-body > .ns-sequence,
        .ns-sequence {{
          width: 100%;
          min-width: 0;
        }}
        .ns-branches {{
          width: 100%;
          min-width: 0;
          grid-template-columns: 1fr;
        }}
        .ns-branches-single {{ grid-template-columns: 1fr; }}
        .ns-branch {{
          border-left: 0;
          border-top: 1px solid var(--border);
        }}
        .ns-branch:first-child {{ border-top: 0; }}
      }}
    </style>
  </head>
  <body>
    <div class="viewer">
      <div class="titlebar">
        <div class="titlebar-icon"></div>
        <span class="titlebar-text">Swifta · NSD Viewer</span>
      </div>
      <div class="toolbar">
        <span class="toolbar-label">Nassi-Shneiderman</span>
        <code class="toolbar-path">{escape(diagram.source_location)}</code>
      </div>
      <main class="viewer-body">{sections}</main>
    </div>
  </body>
</html>
"""

    def _render_function(self, function) -> str:
        return (
            '<section class="function-panel">'
            '<div class="function-head">'
            f'<h2 class="function-title">{escape(function.qualified_name)}</h2>'
            f'<div class="function-signature">{escape(function.signature)}</div>'
            "</div>"
            '<div class="function-body">'
            f"{self._render_sequence(function.steps, depth=0)}"
            "</div>"
            "</section>"
        )

    def _render_sequence(self, steps: tuple[ControlFlowStep, ...], *, depth: int) -> str:
        if not steps:
            return '<div class="empty">No structured steps.</div>'
        rendered = "".join(self._render_step(step, depth=depth) for step in steps)
        return f'<div class="ns-sequence ns-depth-{depth}">{rendered}</div>'

    def _render_step(self, step: ControlFlowStep, *, depth: int) -> str:
        if isinstance(step, ActionFlowStep):
            return (
                '<div class="ns-node ns-action">'
                f'<div class="ns-label" aria-label="Action {escape(step.label)}">'
                f'<code class="action-text">{escape(step.label)}</code>'
                "</div>"
                "</div>"
            )
        if isinstance(step, IfFlowStep):
            if step.else_steps:
                else_markup = (
                    '<div class="ns-branch ns-branch-no" aria-label="Else branch">'
                    f"{self._render_sequence(step.else_steps, depth=depth + 1)}"
                    "</div>"
                )
                branches_class = "ns-branches"
                trailing_note = ""
            else:
                else_markup = ""
                branches_class = "ns-branches ns-branches-single"
                trailing_note = '<div class="ns-note">No branch continues after the decision.</div>'

            return (
                '<div class="ns-node ns-if">'
                f"{self._render_if_cap(step.condition, depth=depth)}"
                f'<div class="{branches_class}">'
                '<div class="ns-branch ns-branch-yes" aria-label="Then branch">'
                f"{self._render_sequence(step.then_steps, depth=depth + 1)}"
                "</div>"
                f"{else_markup}"
                "</div>"
                f"{trailing_note}"
                "</div>"
            )
        if isinstance(step, GuardFlowStep):
            return (
                '<div class="ns-node ns-guard">'
                f"{self._render_header(f'Guard {step.condition}')}"
                '<div class="ns-branch ns-branch-no"><div class="ns-branch-title">Failure / exit</div>'
                f"{self._render_sequence(step.else_steps, depth=depth + 1)}"
                "</div>"
                "</div>"
            )
        if isinstance(step, WhileFlowStep):
            return self._render_single_body(f"While {step.condition}", step.body_steps, depth=depth)
        if isinstance(step, ForInFlowStep):
            return self._render_single_body(f"For {step.header}", step.body_steps, depth=depth)
        if isinstance(step, RepeatWhileFlowStep):
            return (
                '<div class="ns-node ns-repeat">'
                f"{self._render_header('Repeat')}"
                f"{self._render_sequence(step.body_steps, depth=depth + 1)}"
                f"{self._render_footer(f'While {step.condition}')}"
                "</div>"
            )
        if isinstance(step, SwitchFlowStep):
            return self._render_switch(step, depth=depth)
        if isinstance(step, DoCatchFlowStep):
            catches = "".join(
                self._render_single_body(
                    f"Catch {catch.pattern}",
                    catch.steps,
                    depth=depth + 1,
                    css_class="ns-do-catch",
                )
                for catch in step.catches
            )
            return (
                '<div class="ns-node ns-do-catch">'
                f"{self._render_header('Do')}"
                f"{self._render_sequence(step.body_steps, depth=depth + 1)}"
                f'<div class="ns-catches">{catches}</div>'
                "</div>"
            )
        if isinstance(step, DeferFlowStep):
            return self._render_single_body("Defer", step.body_steps, depth=depth, css_class="ns-defer")
        raise TypeError(f"unsupported step type: {type(step)!r}")

    def _render_case(self, case: SwitchCaseFlow) -> str:
        return (
            '<div class="case">'
            f"{self._render_case_title(case.label)}"
            f"{self._render_sequence(case.steps, depth=2)}"
            "</div>"
        )

    def _render_single_body(
        self,
        title: str,
        steps: tuple[ControlFlowStep, ...],
        *,
        depth: int,
        css_class: str = "ns-loop",
    ) -> str:
        return (
            f'<div class="ns-node {css_class}">'
            f"{self._render_header(title)}"
            f"{self._render_sequence(steps, depth=depth + 1)}"
            "</div>"
        )

    def _render_header(self, title: str) -> str:
        escaped = escape(title)
        return f'<div class="ns-header" aria-label="{escaped}">{escaped}</div>'

    def _if_cap_geometry(self, condition: str, badge: str) -> tuple[int, int, int, int, int]:
        text = f"{badge} {condition}".strip()
        char_count = max(len(text), 12)
        tokens = [token for token in re.split(r"\s+", text) if token]
        longest_token = max((len(token) for token in tokens), default=char_count)

        content_width = max(
            360,
            min(
                1600,
                max(longest_token * 8 + 48, ceil(char_count / 2) * 7 + 64),
            ),
        )
        svg_width = content_width + 40
        chars_per_line = max(18, int(content_width / 7.4))
        line_count = max(
            1,
            ceil(char_count / chars_per_line),
            ceil(longest_token / chars_per_line),
        )
        text_height = 24 + (line_count - 1) * 17
        split_y = 18 + text_height
        svg_height = split_y + 30
        return svg_width, svg_height, content_width, text_height, split_y

    def _render_if_cap(self, condition: str, *, depth: int = 0) -> str:
        escaped = escape(condition)
        d = min(depth, 50)
        badge = self._depth_badge(d)
        svg_width, svg_height, content_width, text_height, split_y = self._if_cap_geometry(
            condition,
            badge,
        )
        half_width = svg_width / 2
        yes_x = svg_width / 4
        no_x = svg_width * 0.75
        label_y = svg_height - 8

        return (
            f'<div class="ns-if-cap ns-if-depth-{d}" aria-label="If {escaped}">'
            f'<svg class="ns-if-svg" viewBox="0 0 {svg_width} {svg_height}" '
            f'width="{svg_width}" height="{svg_height}" preserveAspectRatio="xMidYMid meet">'
            f'<polygon points="0,0 {svg_width},0 {half_width},{split_y}" '
            f'class="ns-if-triangle ns-if-depth-{d}-triangle"/>'
            f'<foreignObject x="20" y="6" width="{content_width}" height="{text_height}" '
            'class="ns-if-condition-fo">'
            f'<div xmlns="http://www.w3.org/1999/xhtml" class="ns-if-condition-text">{badge} {escaped}</div>'
            '</foreignObject>'
            f'<line x1="0" y1="{split_y}" x2="{half_width}" y2="{svg_height}" '
            f'class="ns-if-diagonal ns-if-depth-{d}-diagonal"/>'
            f'<line x1="{svg_width}" y1="{split_y}" x2="{half_width}" y2="{svg_height}" '
            f'class="ns-if-diagonal ns-if-depth-{d}-diagonal"/>'
            f'<text x="{yes_x}" y="{label_y}" text-anchor="middle" class="ns-if-label-yes">Yes</text>'
            f'<text x="{no_x}" y="{label_y}" text-anchor="middle" class="ns-if-label-no">No</text>'
            '</svg>'
            "</div>"
        )

    def _render_switch(self, step: SwitchFlowStep, *, depth: int) -> str:
        case_count = len(step.cases)
        if case_count == 0:
            return (
                '<div class="ns-node ns-switch">'
                f"{self._render_header(f'Switch {step.expression}')}"
                '<div class="empty">No cases.</div>'
                "</div>"
            )

        # Build case columns with values on top, bodies below
        cases_html = []
        for case in step.cases:
            label = self._normalize_case_label(case.label.strip())
            cases_html.append(
                f'<div class="ns-switch-case-col" aria-label="{escape(label)}">'
                f'<div class="ns-switch-case-value">{escape(label)}</div>'
                f'<div class="ns-switch-case-body">{self._render_sequence(case.steps, depth=depth + 1)}</div>'
                "</div>"
            )

        d = min(depth, 50)
        badge = self._depth_badge(d)

        return (
            f'<div class="ns-node ns-switch ns-if-depth-{d}">'
            f'<div class="ns-switch-header">{badge} switch {escape(step.expression)}</div>'
            f'<div class="ns-switch-cases">{"".join(cases_html)}</div>'
            "</div>"
        )

    def _render_footer(self, title: str) -> str:
        escaped = escape(title)
        return f'<div class="ns-footer" aria-label="{escaped}">{escaped}</div>'

    def _render_case_title(self, label: str) -> str:
        text = self._normalize_case_label(label.strip())
        escaped = escape(text)
        return f'<div class="case-title" aria-label="{escaped}">{escaped}</div>'

    def _normalize_case_label(self, label: str) -> str:
        compact = label.removesuffix(":").strip()
        if compact.startswith("default"):
            return "default"
        if compact.startswith("case "):
            return compact
        return compact
