"""Extract structured control flow from C source through ANTLR."""

from __future__ import annotations

import re
from dataclasses import dataclass

from antlr4 import CommonTokenStream, InputStream
from antlr4.Token import Token

from clenz.domain.control_flow import (
    ActionFlowStep,
    ControlFlowDiagram,
    ControlFlowStep,
    DoWhileFlowStep,
    ForFlowStep,
    FunctionControlFlow,
    IfFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WhileFlowStep,
)
from clenz.domain.model import SourceUnit
from clenz.domain.ports import CControlFlowExtractor
from clenz.infrastructure.antlr.runtime import (
    load_generated_types,
    parse_code_block_text,
    parse_statement_text,
    parse_source_text,
)


@dataclass(frozen=True, slots=True)
class _ExtractorContext:
    token_stream: object

    def text(self, ctx) -> str:
        if ctx is None:
            return ""
        return self.token_stream.getText(
            start=ctx.start.tokenIndex,
            stop=ctx.stop.tokenIndex,
        )

    def compact(self, ctx) -> str:
        return re.sub(r"\s+", " ", self.text(ctx)).strip()


@dataclass(frozen=True, slots=True)
class _ContainerScope:
    name: str
    body_depth: int


@dataclass(frozen=True, slots=True)
class _PendingContainer:
    name: str


@dataclass(frozen=True, slots=True)
class _FunctionSlice:
    name: str
    signature: str
    container: str | None
    body_text: str


_MAX_STRUCTURED_PARSE_CHARS = 1400
_MAX_STRUCTURED_PARSE_TOKENS = 220
_MAX_STRUCTURED_PARSE_LINES = 24


class AntlrCControlFlowExtractor(CControlFlowExtractor):
    def __init__(self) -> None:
        self._generated = load_generated_types()
        self._lexer_type = self._generated.lexer_type

    def extract(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        try:
            function_slices = _scan_function_slices(source_unit.content, self._generated)
            functions = tuple(self._extract_function_slice(function_slice) for function_slice in function_slices)
            return ControlFlowDiagram(
                source_location=source_unit.location,
                functions=functions,
            )
        except Exception:
            return self._extract_via_full_parse(source_unit)

    def _extract_function_slice(self, function_slice: _FunctionSlice) -> FunctionControlFlow:
        quick_steps = _extract_lightweight_steps(
            function_slice.body_text,
            self._generated,
            self._generated.visitor_type,
            self._lexer_type,
        )
        if quick_steps is not None:
            return FunctionControlFlow(
                name=function_slice.name,
                signature=function_slice.signature,
                container=function_slice.container,
                steps=quick_steps,
            )

        parse_result = parse_code_block_text(function_slice.body_text, self._generated)
        visitor = _build_control_flow_visitor(
            self._generated.visitor_type,
            _ExtractorContext(token_stream=parse_result.token_stream),
        )()
        return FunctionControlFlow(
            name=function_slice.name,
            signature=function_slice.signature,
            container=function_slice.container,
            steps=visitor._extract_compound_statement(parse_result.tree),
        )

    def _extract_via_full_parse(self, source_unit: SourceUnit) -> ControlFlowDiagram:
        parse_result = parse_source_text(source_unit.content, self._generated)
        visitor = _build_control_flow_visitor(
            self._generated.visitor_type,
            _ExtractorContext(token_stream=parse_result.token_stream),
        )()
        visitor.visit(parse_result.tree)
        return ControlFlowDiagram(
            source_location=source_unit.location,
            functions=tuple(visitor.functions),
        )


# ---------------------------------------------------------------------------
# Token-based fast scanner for function bodies
# ---------------------------------------------------------------------------


def _scan_function_slices(
    source_text: str,
    generated: object,
) -> tuple[_FunctionSlice, ...]:
    lexer = generated.lexer_type(InputStream(source_text))
    token_stream = CommonTokenStream(lexer)
    token_stream.fill()
    tokens = tuple(
        token
        for token in token_stream.tokens
        if token.type != Token.EOF and token.channel == Token.DEFAULT_CHANNEL
    )
    lexer_type = generated.lexer_type

    functions: list[_FunctionSlice] = []
    container_stack: list[_ContainerScope] = []
    pending_container: _PendingContainer | None = None
    brace_depth = 0
    index = 0

    while index < len(tokens):
        token = tokens[index]

        if token.type == lexer_type.LeftBrace:
            brace_depth += 1
            if pending_container is not None:
                container_stack.append(
                    _ContainerScope(name=pending_container.name, body_depth=brace_depth)
                )
                pending_container = None
            index += 1
            continue

        if token.type == lexer_type.RightBrace:
            if container_stack and container_stack[-1].body_depth == brace_depth:
                container_stack.pop()
            brace_depth = max(brace_depth - 1, 0)
            index += 1
            continue

        if token.type in {
            lexer_type.Struct,
            lexer_type.Union,
            lexer_type.Enum,
        }:
            pending_container = _PendingContainer(
                name=_extract_container_name(tokens, index + 1, lexer_type)
            )
            index += 1
            continue

        function_slice, next_index = _try_scan_function_slice(
            source_text,
            tokens,
            index,
            container_stack,
            brace_depth,
            lexer_type,
        )
        if function_slice is not None:
            functions.append(function_slice)
            index = next_index
            continue

        index += 1

    return tuple(functions)


def _extract_container_name(tokens: tuple[object, ...], start_index: int, lexer_type: object) -> str:
    if start_index >= len(tokens):
        return "anonymous"

    token = tokens[start_index]
    if token.type != lexer_type.Identifier:
        return "anonymous"

    return token.text


def _try_scan_function_slice(
    source_text: str,
    tokens: tuple[object, ...],
    start_index: int,
    container_stack: list[_ContainerScope],
    brace_depth: int,
    lexer_type: object,
) -> tuple[_FunctionSlice | None, int]:
    """Try to detect a function definition starting at *start_index*.

    In C a function definition has the pattern:
        return_type declarator '(' params ')' compound_statement
    We scan forward looking for '(' ... ')' followed by '{'.
    """
    # Walk tokens looking for the opening paren of the parameter list.
    index = start_index
    name = None
    paren_start = None

    while index < len(tokens):
        token = tokens[index]
        if token.type == lexer_type.LeftParen:
            paren_start = index
            # The function name is the Identifier just before this paren.
            if index > start_index:
                candidate = tokens[index - 1]
                if candidate.type == lexer_type.Identifier:
                    name = candidate.text
            break
        if token.type == lexer_type.LeftBrace and index == start_index:
            # This is a brace we are already inside -- not a function start.
            return None, start_index + 1
        if token.type == lexer_type.Semi:
            # Reached end of a declaration without a body -- not a function.
            return None, index + 1
        if token.type == lexer_type.RightBrace:
            return None, index + 1
        index += 1

    if name is None or paren_start is None:
        return None, start_index + 1

    body_open_index = _find_function_body_open(tokens, paren_start, lexer_type)
    if body_open_index is None:
        return None, start_index + 1

    body_close_index = _find_matching_brace(tokens, body_open_index, lexer_type)
    if body_close_index is None:
        return None, start_index + 1

    signature_text = source_text[tokens[start_index].start : tokens[body_open_index].start]
    body_text = source_text[
        tokens[body_open_index].start : tokens[body_close_index].stop + 1
    ]
    container = ".".join(scope.name for scope in container_stack) or None

    return (
        _FunctionSlice(
            name=name,
            signature=_compact_source_text(signature_text),
            container=container,
            body_text=body_text,
        ),
        body_close_index + 1,
    )


def _find_function_body_open(
    tokens: tuple[object, ...],
    start_index: int,
    lexer_type: object,
) -> int | None:
    """Find the opening '{' of the function body after the '(' of params."""
    paren_depth = 0
    index = start_index

    while index < len(tokens):
        token = tokens[index]

        if token.type == lexer_type.LeftParen:
            paren_depth += 1
        elif token.type == lexer_type.RightParen:
            paren_depth = max(paren_depth - 1, 0)
        elif token.type == lexer_type.LeftBrace and paren_depth == 0:
            return index
        elif token.type == lexer_type.RightBrace and paren_depth == 0:
            return None

        index += 1

    return None


def _find_matching_brace(
    tokens: tuple[object, ...],
    open_index: int,
    lexer_type: object,
) -> int | None:
    depth = 1
    index = open_index + 1
    while index < len(tokens):
        token = tokens[index]
        if token.type == lexer_type.LeftBrace:
            depth += 1
        elif token.type == lexer_type.RightBrace:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _compact_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


# ---------------------------------------------------------------------------
# Lightweight token-based step extraction
# ---------------------------------------------------------------------------


def _extract_lightweight_steps(
    body_text: str,
    generated: object,
    visitor_type: type,
    lexer_type: object,
) -> tuple[ControlFlowStep, ...] | None:
    statement_spans = _split_top_level_statement_spans(body_text, lexer_type)
    if statement_spans is None:
        return None

    steps: list[ControlFlowStep] = []
    structured_starters = _structured_token_types(lexer_type)

    for statement_text, tokens, base_offset in statement_spans:
        if not tokens:
            continue

        if tokens[0].type in structured_starters:
            if _should_summarize_structured_statement(statement_text, tokens):
                steps.append(
                    _build_summarized_structured_step(
                        statement_text,
                        tokens,
                        base_offset,
                        lexer_type,
                    )
                )
                continue
            parse_result = parse_statement_text(statement_text, generated)
            visitor = _build_control_flow_visitor(
                visitor_type,
                _ExtractorContext(token_stream=parse_result.token_stream),
            )()
            extracted = visitor._extract_statement(parse_result.tree)
            if extracted is not None:
                steps.append(extracted)
            continue

        steps.append(ActionFlowStep(_compact_source_text(statement_text.strip().removesuffix(";"))))

    return tuple(steps)


def _should_summarize_structured_statement(
    statement_text: str,
    tokens: tuple[object, ...],
) -> bool:
    return (
        len(statement_text) > _MAX_STRUCTURED_PARSE_CHARS
        or len(tokens) > _MAX_STRUCTURED_PARSE_TOKENS
        or statement_text.count("\n") > _MAX_STRUCTURED_PARSE_LINES
    )


def _summarize_code_block_steps(
    body_text: str,
    lexer_type: object,
) -> tuple[ControlFlowStep, ...]:
    statement_spans = _split_top_level_statement_spans(body_text, lexer_type)
    if statement_spans is None:
        label = _compact_label_text(body_text.strip().strip("{}"))
        return (ActionFlowStep(label),) if label else ()

    steps: list[ControlFlowStep] = []
    structured_starters = _structured_token_types(lexer_type)

    for statement_text, tokens, base_offset in statement_spans:
        if not tokens:
            continue
        if tokens[0].type in structured_starters:
            steps.append(
                _build_summarized_structured_step(
                    statement_text,
                    tokens,
                    base_offset,
                    lexer_type,
                )
            )
            continue
        label = _compact_label_text(statement_text.strip().removesuffix(";"))
        if label:
            steps.append(ActionFlowStep(label))

    return tuple(steps)


def _build_summarized_structured_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    if not tokens:
        return ActionFlowStep(_compact_label_text(statement_text))

    starter = tokens[0].text
    if starter == "if":
        return _build_summarized_if_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "for":
        return _build_summarized_for_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "while":
        return _build_summarized_while_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "do":
        return _build_summarized_do_while_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "switch":
        return _build_summarized_switch_step(statement_text, tokens, base_offset, lexer_type)
    return ActionFlowStep(_summarize_structured_header(statement_text, tokens, base_offset, lexer_type))


def _build_summarized_if_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    # Skip past 'if' and find the parenthesized condition, then the body.
    paren_open = _find_token(tokens, 1, lexer_type.LeftParen, lexer_type)
    if paren_open is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    paren_close = _find_matching_paren(tokens, paren_open, lexer_type)
    if paren_close is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    condition = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, paren_open + 1, paren_close - 1)
    )

    # Find the body after the closing paren.
    block_range = _find_top_level_code_block(tokens, paren_close + 1, lexer_type)

    then_steps: tuple[ControlFlowStep, ...] = ()
    body_end: int | None = None

    if block_range is not None:
        open_index, close_index = block_range
        then_steps = _summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        )
    else:
        # Single-statement body (no braces).
        body_end = _find_single_statement_end(tokens, paren_close + 1, lexer_type)
        if body_end is not None:
            body_text = _slice_token_text(statement_text, tokens, base_offset, paren_close + 1, body_end)
            if body_text.strip():
                then_steps = (ActionFlowStep(_compact_label_text(body_text.strip().removesuffix(";"))),)

    else_steps: tuple[ControlFlowStep, ...] = ()
    if block_range is not None:
        else_index = block_range[1] + 1
    else:
        else_index = (body_end + 1) if body_end is not None else len(tokens)

    if else_index < len(tokens) and tokens[else_index].type == lexer_type.Else:
        next_index = else_index + 1
        if next_index < len(tokens) and tokens[next_index].type == lexer_type.If:
            nested_text = _slice_token_text(
                statement_text,
                tokens,
                base_offset,
                next_index,
                len(tokens) - 1,
            )
            else_steps = (
                _build_summarized_structured_step(
                    nested_text,
                    tokens[next_index:],
                    tokens[next_index].start,
                    lexer_type,
                ),
            )
        else:
            else_block = _find_top_level_code_block(tokens, next_index, lexer_type)
            if else_block is not None:
                else_open, else_close = else_block
                else_steps = _summarize_code_block_steps(
                    _slice_token_text(
                        statement_text,
                        tokens,
                        base_offset,
                        else_open,
                        else_close,
                    ),
                    lexer_type,
                )

    return IfFlowStep(
        condition=condition or "condition",
        then_steps=then_steps,
        else_steps=else_steps,
    )


def _build_summarized_for_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    paren_open = _find_token(tokens, 1, lexer_type.LeftParen, lexer_type)
    if paren_open is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    paren_close = _find_matching_paren(tokens, paren_open, lexer_type)
    if paren_close is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    header = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 1, paren_close)
    )
    body_steps = _extract_body_steps(
        statement_text, tokens, base_offset, paren_close + 1, lexer_type
    )
    return ForFlowStep(
        header=header or "for (...)",
        body_steps=body_steps,
    )


def _build_summarized_while_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    paren_open = _find_token(tokens, 1, lexer_type.LeftParen, lexer_type)
    if paren_open is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    paren_close = _find_matching_paren(tokens, paren_open, lexer_type)
    if paren_close is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    condition = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, paren_open + 1, paren_close - 1)
    )
    body_steps = _extract_body_steps(
        statement_text, tokens, base_offset, paren_close + 1, lexer_type
    )
    return WhileFlowStep(
        condition=condition or "condition",
        body_steps=body_steps,
    )


def _build_summarized_do_while_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    # 'do' statement 'while' '(' expression ')' ';'
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    body_steps: tuple[ControlFlowStep, ...] = ()
    search_start = 1

    if block_range is not None:
        open_index, close_index = block_range
        body_steps = _summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        )
        search_start = close_index + 1
    else:
        # Single-statement body.
        body_end = _find_single_statement_end(tokens, 1, lexer_type)
        if body_end is not None:
            body_text = _slice_token_text(statement_text, tokens, base_offset, 1, body_end)
            if body_text.strip():
                body_steps = (ActionFlowStep(_compact_label_text(body_text.strip().removesuffix(";"))),)
            search_start = body_end + 1

    # Find 'while' after the body.
    condition = ""
    while_index = _find_token(tokens, search_start, lexer_type.While, lexer_type)
    if while_index is not None:
        paren_open = _find_token(tokens, while_index + 1, lexer_type.LeftParen, lexer_type)
        if paren_open is not None:
            paren_close = _find_matching_paren(tokens, paren_open, lexer_type)
            if paren_close is not None:
                condition = _compact_label_text(
                    _slice_token_text(
                        statement_text,
                        tokens,
                        base_offset,
                        paren_open + 1,
                        paren_close - 1,
                    )
                )

    return DoWhileFlowStep(
        condition=condition or "condition",
        body_steps=body_steps,
    )


def _build_summarized_switch_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    paren_open = _find_token(tokens, 1, lexer_type.LeftParen, lexer_type)
    if paren_open is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    paren_close = _find_matching_paren(tokens, paren_open, lexer_type)
    if paren_close is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    expression = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, paren_open + 1, paren_close - 1)
    )

    # Extract case groups from the switch body.
    block_range = _find_top_level_code_block(tokens, paren_close + 1, lexer_type)
    cases: list[SwitchCaseFlow] = []

    if block_range is not None:
        open_index, close_index = block_range
        body_text = _slice_token_text(statement_text, tokens, base_offset, open_index, close_index)
        inner_tokens = _lex_default_tokens(body_text, lexer_type)
        cases = _extract_switch_cases_from_tokens(body_text, inner_tokens, lexer_type)

    return SwitchFlowStep(
        expression=expression or "expression",
        cases=tuple(cases),
    )


def _extract_switch_cases_from_tokens(
    body_text: str,
    tokens: tuple[object, ...],
    lexer_type: object,
) -> list[SwitchCaseFlow]:
    """Extract case/default groups from the token stream inside a switch body."""
    if not tokens or len(tokens) < 2:
        return []

    # Skip the opening brace.
    start = 0
    if tokens[0].type == lexer_type.LeftBrace:
        start = 1

    # Find closing brace.
    end = len(tokens)
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].type == lexer_type.RightBrace:
            end = i
            break

    cases: list[SwitchCaseFlow] = []
    current_label: str | None = None
    current_start: int | None = None
    index = start

    while index < end:
        token = tokens[index]

        if token.type in {lexer_type.Case, lexer_type.Default}:
            # Flush previous case.
            if current_label is not None and current_start is not None:
                cases.append(SwitchCaseFlow(
                    label=current_label,
                    steps=_collect_case_steps(body_text, tokens, current_start, index, lexer_type),
                ))

            # Start new case label.
            if token.type == lexer_type.Case:
                label_parts = ["case"]
                index += 1
                while index < end and tokens[index].type != lexer_type.Colon:
                    label_parts.append(tokens[index].text)
                    index += 1
                current_label = _compact_label_text(" ".join(label_parts))
            else:
                current_label = "default"
                index += 1
                while index < end and tokens[index].type != lexer_type.Colon:
                    index += 1
            current_start = index + 1
            index += 1
            continue

        index += 1

    # Flush the last case.
    if current_label is not None and current_start is not None:
        cases.append(SwitchCaseFlow(
            label=current_label,
            steps=_collect_case_steps(body_text, tokens, current_start, end, lexer_type),
        ))

    return cases


def _collect_case_steps(
    body_text: str,
    tokens: tuple[object, ...],
    start: int,
    end: int,
    lexer_type: object,
) -> tuple[ControlFlowStep, ...]:
    """Collect the action steps between two positions in a switch body."""
    if start >= end:
        return ()

    segment_tokens = tokens[start:end]
    if not segment_tokens:
        return ()

    segment_text = body_text[
        segment_tokens[0].start : segment_tokens[-1].stop + 1
    ]
    return _summarize_code_block_steps(
        "{" + segment_text + "}",
        lexer_type,
    )


def _extract_body_steps(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    search_start: int,
    lexer_type: object,
) -> tuple[ControlFlowStep, ...]:
    """Extract body steps from either a braced block or a single statement."""
    block_range = _find_top_level_code_block(tokens, search_start, lexer_type)
    if block_range is not None:
        open_index, close_index = block_range
        return _summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        )

    # Single-statement body (no braces).
    body_end = _find_single_statement_end(tokens, search_start, lexer_type)
    if body_end is not None:
        body_text = _slice_token_text(statement_text, tokens, base_offset, search_start, body_end)
        if body_text.strip():
            return (ActionFlowStep(_compact_label_text(body_text.strip().removesuffix(";"))),)
    return ()


def _find_token(
    tokens: tuple[object, ...],
    start_index: int,
    token_type: int,
    lexer_type: object,
) -> int | None:
    """Find the first token of *token_type* starting at *start_index*."""
    for index in range(start_index, len(tokens)):
        if tokens[index].type == token_type:
            return index
    return None


def _find_matching_paren(
    tokens: tuple[object, ...],
    open_index: int,
    lexer_type: object,
) -> int | None:
    """Find the ')' matching the '(' at *open_index*."""
    depth = 1
    index = open_index + 1
    while index < len(tokens):
        if tokens[index].type == lexer_type.LeftParen:
            depth += 1
        elif tokens[index].type == lexer_type.RightParen:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _find_single_statement_end(
    tokens: tuple[object, ...],
    start_index: int,
    lexer_type: object,
) -> int | None:
    """Find the end of a single (non-braced) statement (terminated by ';')."""
    brace_depth = 0
    paren_depth = 0
    for index in range(start_index, len(tokens)):
        token = tokens[index]
        if token.type == lexer_type.LeftBrace:
            brace_depth += 1
        elif token.type == lexer_type.RightBrace:
            if brace_depth == 0:
                return None
            brace_depth -= 1
        elif token.type == lexer_type.LeftParen:
            paren_depth += 1
        elif token.type == lexer_type.RightParen:
            paren_depth = max(paren_depth - 1, 0)
        elif token.text == ";" and brace_depth == 0 and paren_depth == 0:
            return index
    return None


def _summarize_structured_header(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> str:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return _compact_label_text(statement_text.strip().removesuffix(";"))
    open_index, _ = block_range
    return _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 0, open_index - 1)
    )


def _find_top_level_code_block(
    tokens: tuple[object, ...],
    start_index: int,
    lexer_type: object,
) -> tuple[int, int] | None:
    paren_depth = 0

    for index in range(start_index, len(tokens)):
        token = tokens[index]
        if token.type == lexer_type.LeftParen:
            paren_depth += 1
        elif token.type == lexer_type.RightParen:
            paren_depth = max(paren_depth - 1, 0)
        elif token.type == lexer_type.LeftBrace and paren_depth == 0:
            close_index = _find_matching_brace(tokens, index, lexer_type)
            if close_index is not None:
                return index, close_index
            return None

    return None


def _slice_token_text(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    start_index: int,
    end_index: int,
) -> str:
    if start_index < 0 or end_index < start_index or end_index >= len(tokens):
        return ""
    start = tokens[start_index].start - base_offset
    end = tokens[end_index].stop + 1 - base_offset
    return statement_text[start:end]


def _compact_label_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _split_top_level_statement_spans(
    body_text: str,
    lexer_type: object,
) -> tuple[tuple[str, tuple[object, ...], int], ...] | None:
    tokens = _lex_default_tokens(body_text, lexer_type)
    if not tokens or tokens[0].type != lexer_type.LeftBrace:
        return None

    close_index = _find_matching_brace(tokens, 0, lexer_type)
    if close_index is None:
        return None

    spans: list[tuple[str, tuple[object, ...], int]] = []
    brace_depth = 1
    paren_depth = 0
    statement_start_index: int | None = None

    for index in range(1, close_index):
        token = tokens[index]
        if statement_start_index is None:
            statement_start_index = index

        if token.type == lexer_type.LeftParen:
            paren_depth += 1
        elif token.type == lexer_type.RightParen:
            paren_depth = max(paren_depth - 1, 0)
        elif token.type == lexer_type.LeftBrace:
            brace_depth += 1
        elif token.type == lexer_type.RightBrace:
            brace_depth -= 1

        next_token = tokens[index + 1] if index + 1 < close_index else None
        at_statement_end = False

        if (
            token.text == ";"
            and brace_depth == 1
            and paren_depth == 0
        ):
            at_statement_end = True
        elif (
            next_token is not None
            and brace_depth == 1
            and paren_depth == 0
            and next_token.type != lexer_type.Else
            and next_token.line > token.line
        ):
            at_statement_end = True
        elif next_token is None:
            at_statement_end = True

        if at_statement_end and statement_start_index is not None:
            statement_tokens = tokens[statement_start_index : index + 1]
            statement_text = body_text[
                statement_tokens[0].start : statement_tokens[-1].stop + 1
            ]
            if statement_text.strip():
                spans.append((statement_text, statement_tokens, statement_tokens[0].start))
            statement_start_index = None

    return tuple(spans)


def _structured_token_types(lexer_type: object) -> set[int]:
    return {
        token_type
        for token_type in {
            getattr(lexer_type, "If", None),
            getattr(lexer_type, "For", None),
            getattr(lexer_type, "While", None),
            getattr(lexer_type, "Do", None),
            getattr(lexer_type, "Switch", None),
        }
        if token_type is not None
    }


def _lex_default_tokens(source_text: str, lexer_type: object) -> tuple[object, ...]:
    lexer = lexer_type(InputStream(source_text))
    token_stream = CommonTokenStream(lexer)
    token_stream.fill()
    return tuple(
        token
        for token in token_stream.tokens
        if token.type != Token.EOF and token.channel == Token.DEFAULT_CHANNEL
    )


# ---------------------------------------------------------------------------
# Full ANTLR parse tree visitor for C control flow
# ---------------------------------------------------------------------------


def _build_control_flow_visitor(visitor_base: type, context: _ExtractorContext) -> type:
    class CControlFlowVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.functions: list[FunctionControlFlow] = []
            self._containers: list[str] = []

        def visitStructOrUnionSpecifier(self, ctx):
            # struct/union with a name and body
            name_ctx = ctx.Identifier()
            name = name_ctx.getText() if name_ctx is not None else "anonymous"
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitEnumSpecifier(self, ctx):
            name_ctx = ctx.Identifier()
            name = name_ctx.getText() if name_ctx is not None else "anonymous"
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitFunctionDefinition(self, ctx):
            compound = ctx.compoundStatement()
            if compound is None:
                return None

            name = self._extract_function_name(ctx)
            signature = context.compact(ctx.declarator())
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=signature,
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_compound_statement(compound),
                )
            )
            return None

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_function_name(self, func_ctx) -> str:
            """Extract the function name from a functionDefinition context.

            Walk the declarator to find the directDeclarator that contains
            the function name (the Identifier before the parameter list).
            """
            declarator = func_ctx.declarator()
            if declarator is None:
                return "unknown"

            # Navigate: declarator -> directDeclarator which has Identifier and '('
            direct = declarator.directDeclarator()
            if direct is not None:
                return self._drill_declarator_name(direct)

            return declarator.getText().split("(")[0].strip()

        def _drill_declarator_name(self, direct_ctx) -> str:
            """Recursively drill into directDeclarator to find the identifier."""
            # directDeclarator can be:
            #   Identifier
            #   '(' declarator ')'
            #   directDeclarator '[' ... ']'
            #   directDeclarator '(' ... ')'
            ident = direct_ctx.Identifier()
            if ident is not None:
                return ident.getText()

            # Try nested directDeclarator
            inner = direct_ctx.directDeclarator()
            if inner is not None:
                return self._drill_declarator_name(inner)

            return direct_ctx.getText().split("(")[0].strip()

        def _extract_compound_statement(self, compound_ctx) -> tuple[ControlFlowStep, ...]:
            if compound_ctx is None:
                return ()
            block_item_list = compound_ctx.blockItemList()
            if block_item_list is None:
                return ()
            return self._extract_block_item_list(block_item_list)

        def _extract_block_item_list(self, block_item_list_ctx) -> tuple[ControlFlowStep, ...]:
            steps: list[ControlFlowStep] = []
            for block_item_ctx in block_item_list_ctx.blockItem():
                extracted = self._extract_block_item(block_item_ctx)
                if extracted is not None:
                    steps.append(extracted)
            return tuple(steps)

        def _extract_block_item(self, block_item_ctx) -> ControlFlowStep | None:
            stmt = block_item_ctx.statement()
            if stmt is not None:
                return self._extract_statement(stmt)
            decl = block_item_ctx.declaration()
            if decl is not None:
                return ActionFlowStep(context.compact(decl))
            return None

        def _extract_statement(self, statement_ctx) -> ControlFlowStep | None:
            if statement_ctx.labeledStatement() is not None:
                return self._extract_labeled_statement(statement_ctx.labeledStatement())
            if statement_ctx.compoundStatement() is not None:
                steps = self._extract_compound_statement(statement_ctx.compoundStatement())
                return ActionFlowStep("{ ... }") if not steps else None
            if statement_ctx.expressionStatement() is not None:
                expr = statement_ctx.expressionStatement().expression()
                if expr is not None:
                    return ActionFlowStep(context.compact(expr))
                return ActionFlowStep(";")
            if statement_ctx.selectionStatement() is not None:
                return self._extract_selection_statement(statement_ctx.selectionStatement())
            if statement_ctx.iterationStatement() is not None:
                return self._extract_iteration_statement(statement_ctx.iterationStatement())
            if statement_ctx.jumpStatement() is not None:
                return ActionFlowStep(context.compact(statement_ctx.jumpStatement()))
            return ActionFlowStep(context.compact(statement_ctx))

        def _extract_labeled_statement(self, labeled_ctx) -> ControlFlowStep:
            # Label: identifier ':' statement
            ident = labeled_ctx.Identifier()
            if ident is not None:
                stmt = labeled_ctx.statement()
                if stmt is not None:
                    return self._extract_statement(stmt) or ActionFlowStep(f"label {ident.getText()}")
                return ActionFlowStep(f"label {ident.getText()}")

            # case / default -- these appear inside switch bodies.
            # When visiting a switch, we handle cases directly,
            # so reaching here means it is a standalone labeled statement.
            return ActionFlowStep(context.compact(labeled_ctx))

        def _extract_selection_statement(self, selection_ctx) -> ControlFlowStep:
            # 'if' '(' expression ')' statement ('else' statement)?
            if selection_ctx.If() is not None:
                return self._extract_if_statement(selection_ctx)

            # 'switch' '(' expression ')' statement
            if selection_ctx.Switch() is not None:
                return self._extract_switch_statement(selection_ctx)

            return ActionFlowStep(context.compact(selection_ctx))

        def _extract_if_statement(self, if_ctx) -> IfFlowStep:
            expression = if_ctx.expression()
            condition = context.compact(expression) if expression is not None else "condition"

            statements = if_ctx.statement()
            then_steps: tuple[ControlFlowStep, ...] = ()
            else_steps: tuple[ControlFlowStep, ...] = ()

            if len(statements) >= 1:
                then_steps = self._extract_statement_as_steps(statements[0])

            if if_ctx.Else() is not None and len(statements) >= 2:
                else_steps = self._extract_statement_as_steps(statements[1])

            return IfFlowStep(
                condition=condition,
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_statement_as_steps(self, stmt_ctx) -> tuple[ControlFlowStep, ...]:
            """Extract a statement, returning it as a tuple of steps.

            If the statement is a compound statement, flatten its contents.
            Otherwise, wrap the single step in a tuple.
            """
            if stmt_ctx.compoundStatement() is not None:
                return self._extract_compound_statement(stmt_ctx.compoundStatement())
            extracted = self._extract_statement(stmt_ctx)
            return (extracted,) if extracted is not None else ()

        def _extract_switch_statement(self, switch_ctx) -> SwitchFlowStep:
            expression = switch_ctx.expression()
            expr_text = context.compact(expression) if expression is not None else "expression"

            cases: list[SwitchCaseFlow] = []
            statements = switch_ctx.statement()
            if len(statements) >= 1:
                cases = self._extract_switch_cases(statements[0])

            return SwitchFlowStep(
                expression=expr_text,
                cases=tuple(cases),
            )

        def _extract_switch_cases(self, body_stmt) -> list[SwitchCaseFlow]:
            """Extract cases from the switch body statement.

            The body is typically a compoundStatement containing labeledStatements
            with case/default labels.
            """
            compound = body_stmt.compoundStatement()
            if compound is not None:
                return self._extract_switch_cases_from_compound(compound)

            # Single-statement switch body (unusual but valid).
            return [SwitchCaseFlow(label="body", steps=self._extract_statement_as_steps(body_stmt))]

        def _extract_switch_cases_from_compound(self, compound_ctx) -> list[SwitchCaseFlow]:
            block_item_list = compound_ctx.blockItemList()
            if block_item_list is None:
                return []

            cases: list[SwitchCaseFlow] = []
            current_label: str | None = None
            current_steps: list[ControlFlowStep] = []

            for block_item_ctx in block_item_list.blockItem():
                stmt = block_item_ctx.statement()
                if stmt is None:
                    # Declaration inside switch -- treat as action step.
                    decl = block_item_ctx.declaration()
                    if decl is not None:
                        current_steps.append(ActionFlowStep(context.compact(decl)))
                    continue

                labeled = stmt.labeledStatement()
                if labeled is not None:
                    # Check if this is a case or default label.
                    case_token = labeled.Case()
                    default_token = labeled.Default()

                    if case_token is not None or default_token is not None:
                        # Flush previous case.
                        if current_label is not None:
                            cases.append(SwitchCaseFlow(
                                label=current_label,
                                steps=tuple(current_steps),
                            ))
                            current_steps = []

                        if case_token is not None:
                            const_expr = labeled.constantExpression()
                            current_label = f"case {const_expr.getText()}" if const_expr is not None else "case"
                        else:
                            current_label = "default"

                        # A case/default label may have a statement after it.
                        labeled_stmt = labeled.statement()
                        if labeled_stmt is not None:
                            step = self._extract_statement(labeled_stmt)
                            if step is not None:
                                current_steps.append(step)
                        continue

                    # Regular label (identifier ':').
                    step = self._extract_labeled_statement(labeled)
                    if step is not None:
                        current_steps.append(step)
                    continue

                # Regular statement inside a case.
                step = self._extract_statement(stmt)
                if step is not None:
                    current_steps.append(step)

            # Flush the last case.
            if current_label is not None:
                cases.append(SwitchCaseFlow(
                    label=current_label,
                    steps=tuple(current_steps),
                ))

            return cases

        def _extract_iteration_statement(self, iter_ctx) -> ControlFlowStep:
            # do ... while (check before while since do-while also has a While token)
            if iter_ctx.Do() is not None:
                return self._extract_do_while_statement(iter_ctx)

            # while
            if iter_ctx.While() is not None:
                return self._extract_while_statement(iter_ctx)

            # for
            if iter_ctx.For() is not None:
                return self._extract_for_statement(iter_ctx)

            return ActionFlowStep(context.compact(iter_ctx))

        def _extract_while_statement(self, while_ctx) -> WhileFlowStep:
            expression = while_ctx.expression()
            condition = context.compact(expression) if expression is not None else "condition"

            stmt = while_ctx.statement()
            body_steps = self._extract_statement_as_steps(stmt) if stmt is not None else ()

            return WhileFlowStep(
                condition=condition,
                body_steps=body_steps,
            )

        def _extract_do_while_statement(self, do_ctx) -> DoWhileFlowStep:
            stmt = do_ctx.statement()
            body_steps = self._extract_statement_as_steps(stmt) if stmt is not None else ()

            expression = do_ctx.expression()
            condition = context.compact(expression) if expression is not None else "condition"

            return DoWhileFlowStep(
                condition=condition,
                body_steps=body_steps,
            )

        def _extract_for_statement(self, for_ctx) -> ForFlowStep:
            for_condition = for_ctx.forCondition()
            header = context.compact(for_condition) if for_condition is not None else "for (...)"

            stmt = for_ctx.statement()
            body_steps = self._extract_statement_as_steps(stmt) if stmt is not None else ()

            return ForFlowStep(
                header=header,
                body_steps=body_steps,
            )

    return CControlFlowVisitor
