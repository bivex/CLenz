"""Extract structured control flow from Swift source through ANTLR."""

from __future__ import annotations

import re
from dataclasses import dataclass

from antlr4 import CommonTokenStream, InputStream
from antlr4.Token import Token

from swifta.domain.control_flow import (
    ActionFlowStep,
    CatchClauseFlow,
    ControlFlowDiagram,
    ControlFlowStep,
    DeferFlowStep,
    DoCatchFlowStep,
    ForInFlowStep,
    FunctionControlFlow,
    GuardFlowStep,
    IfFlowStep,
    RepeatWhileFlowStep,
    SwitchCaseFlow,
    SwitchFlowStep,
    WhileFlowStep,
)
from swifta.domain.model import SourceUnit
from swifta.domain.ports import SwiftControlFlowExtractor
from swifta.infrastructure.antlr.runtime import (
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

    def compact(self, ctx, *, limit: int = 96) -> str:
        text = re.sub(r"\s+", " ", self.text(ctx)).strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1]}..."


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
_MAX_EXPANDED_CLOSURE_CHARS = 1800
_MAX_EXPANDED_CLOSURE_LINES = 36
_SUMMARY_LABEL_LIMIT = 96


class AntlrSwiftControlFlowExtractor(SwiftControlFlowExtractor):
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
            # Fallback to the slower whole-file parser when the lightweight scanner
            # cannot safely isolate function bodies.
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
            steps=visitor._extract_code_block(parse_result.tree),
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

        if token.type == lexer_type.LCURLY:
            brace_depth += 1
            if pending_container is not None:
                container_stack.append(
                    _ContainerScope(name=pending_container.name, body_depth=brace_depth)
                )
                pending_container = None
            index += 1
            continue

        if token.type == lexer_type.RCURLY:
            if container_stack and container_stack[-1].body_depth == brace_depth:
                container_stack.pop()
            brace_depth = max(brace_depth - 1, 0)
            index += 1
            continue

        if token.type in {
            lexer_type.CLASS,
            lexer_type.STRUCT,
            lexer_type.ENUM,
            lexer_type.PROTOCOL,
            lexer_type.EXTENSION,
        }:
            pending_container = _PendingContainer(
                name=_extract_container_name(tokens, index + 1, lexer_type)
            )
            index += 1
            continue

        if token.type == lexer_type.FUNC:
            function_slice, next_index = _try_scan_function_slice(
                source_text,
                tokens,
                index,
                container_stack,
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

    parts = [token.text]
    index = start_index + 1
    while index + 1 < len(tokens):
        if tokens[index].text != "." or tokens[index + 1].type != lexer_type.Identifier:
            break
        parts.append(tokens[index].text)
        parts.append(tokens[index + 1].text)
        index += 2

    return "".join(parts)


def _try_scan_function_slice(
    source_text: str,
    tokens: tuple[object, ...],
    func_index: int,
    container_stack: list[_ContainerScope],
    lexer_type: object,
) -> tuple[_FunctionSlice | None, int]:
    name = _extract_function_name(tokens, func_index + 1, lexer_type)
    if name is None:
        return None, func_index + 1

    body_open_index = _find_function_body_open(tokens, func_index + 1, lexer_type)
    if body_open_index is None:
        return None, func_index + 1

    body_close_index = _find_matching_brace(tokens, body_open_index, lexer_type)
    if body_close_index is None:
        return None, func_index + 1

    signature_text = source_text[tokens[func_index].start : tokens[body_open_index].start]
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


def _extract_function_name(
    tokens: tuple[object, ...],
    start_index: int,
    lexer_type: object,
) -> str | None:
    index = start_index
    while index < len(tokens):
        token = tokens[index]
        if token.type == lexer_type.Identifier:
            return token.text
        if token.type == lexer_type.LPAREN:
            return None
        if token.type in {lexer_type.LCURLY, lexer_type.RCURLY}:
            return None
        index += 1
    return None


def _find_function_body_open(
    tokens: tuple[object, ...],
    start_index: int,
    lexer_type: object,
) -> int | None:
    paren_depth = 0
    square_depth = 0
    angle_depth = 0
    index = start_index

    while index < len(tokens):
        token = tokens[index]
        text = token.text

        if token.type == lexer_type.LPAREN:
            paren_depth += 1
        elif token.type == lexer_type.RPAREN:
            paren_depth = max(paren_depth - 1, 0)
        elif text == "[":
            square_depth += 1
        elif text == "]":
            square_depth = max(square_depth - 1, 0)
        elif text == "<":
            angle_depth += 1
        elif text == ">":
            angle_depth = max(angle_depth - 1, 0)
        elif token.type == lexer_type.LCURLY and paren_depth == square_depth == angle_depth == 0:
            return index
        elif token.type == lexer_type.RCURLY and paren_depth == square_depth == angle_depth == 0:
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
        if token.type == lexer_type.LCURLY:
            depth += 1
        elif token.type == lexer_type.RCURLY:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _compact_source_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


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

        closure_body = _extract_autoreleasepool_body(
            statement_text,
            tokens,
            base_offset,
            lexer_type,
        )
        if closure_body is not None:
            if _should_summarize_code_block(closure_body):
                steps.extend(_summarize_code_block_steps(closure_body, lexer_type))
                continue
            nested_steps = _extract_lightweight_steps(
                closure_body,
                generated,
                visitor_type,
                lexer_type,
            )
            if nested_steps is None:
                parse_result = parse_code_block_text(closure_body, generated)
                visitor = _build_control_flow_visitor(
                    visitor_type,
                    _ExtractorContext(token_stream=parse_result.token_stream),
                )()
                nested_steps = visitor._extract_code_block(parse_result.tree)
            steps.extend(nested_steps)
            continue

        trailing_body = _extract_trailing_closure_body(
            statement_text,
            tokens,
            base_offset,
            lexer_type,
        )
        if trailing_body is not None:
            if _should_summarize_code_block(trailing_body):
                steps.extend(_summarize_code_block_steps(trailing_body, lexer_type))
                continue
            nested_steps = _extract_lightweight_steps(
                trailing_body,
                generated,
                visitor_type,
                lexer_type,
            )
            if nested_steps is None:
                parse_result = parse_code_block_text(trailing_body, generated)
                visitor = _build_control_flow_visitor(
                    visitor_type,
                    _ExtractorContext(token_stream=parse_result.token_stream),
                )()
                nested_steps = visitor._extract_code_block(parse_result.tree)
            steps.extend(nested_steps)
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


def _should_summarize_code_block(body_text: str) -> bool:
    return (
        len(body_text) > _MAX_EXPANDED_CLOSURE_CHARS
        or body_text.count("\n") > _MAX_EXPANDED_CLOSURE_LINES
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
    if starter == "guard":
        return _build_summarized_guard_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "for":
        return _build_summarized_for_in_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "while":
        return _build_summarized_while_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "repeat":
        return _build_summarized_repeat_while_step(statement_text, tokens, base_offset, lexer_type)
    if starter == "defer":
        return _build_summarized_defer_step(statement_text, tokens, base_offset, lexer_type)
    return ActionFlowStep(_summarize_structured_header(statement_text, tokens, base_offset, lexer_type))


def _build_summarized_if_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    condition = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 1, open_index - 1)
    )
    then_steps = _summarize_code_block_steps(
        _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
        lexer_type,
    )

    else_steps: tuple[ControlFlowStep, ...] = ()
    else_index = close_index + 1
    if else_index < len(tokens) and tokens[else_index].text == "else":
        next_index = else_index + 1
        if next_index < len(tokens) and tokens[next_index].text == "if":
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


def _build_summarized_guard_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    condition = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 1, open_index - 1)
    )
    return GuardFlowStep(
        condition=condition or "condition",
        else_steps=_summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        ),
    )


def _build_summarized_for_in_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    header = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 1, open_index - 1)
    )
    return ForInFlowStep(
        header=header or "item in collection",
        body_steps=_summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        ),
    )


def _build_summarized_while_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    condition = _compact_label_text(
        _slice_token_text(statement_text, tokens, base_offset, 1, open_index - 1)
    )
    return WhileFlowStep(
        condition=condition or "condition",
        body_steps=_summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        ),
    )


def _build_summarized_repeat_while_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    while_index = close_index + 1
    condition = ""
    if while_index < len(tokens) and tokens[while_index].text == "while":
        condition = _compact_label_text(
            _slice_token_text(
                statement_text,
                tokens,
                base_offset,
                while_index + 1,
                len(tokens) - 1,
            ).removesuffix(";")
        )
    return RepeatWhileFlowStep(
        condition=condition or "condition",
        body_steps=_summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        ),
    )


def _build_summarized_defer_step(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> ControlFlowStep:
    block_range = _find_top_level_code_block(tokens, 1, lexer_type)
    if block_range is None:
        return ActionFlowStep(_compact_label_text(statement_text.strip().removesuffix(";")))

    open_index, close_index = block_range
    return DeferFlowStep(
        body_steps=_summarize_code_block_steps(
            _slice_token_text(statement_text, tokens, base_offset, open_index, close_index),
            lexer_type,
        )
    )


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
    square_depth = 0

    for index in range(start_index, len(tokens)):
        token = tokens[index]
        if token.type == lexer_type.LPAREN:
            paren_depth += 1
        elif token.type == lexer_type.RPAREN:
            paren_depth = max(paren_depth - 1, 0)
        elif token.text == "[":
            square_depth += 1
        elif token.text == "]":
            square_depth = max(square_depth - 1, 0)
        elif token.type == lexer_type.LCURLY and paren_depth == square_depth == 0:
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


def _compact_label_text(text: str, *, limit: int = _SUMMARY_LABEL_LIMIT) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[: limit - 1]}..."


def _split_top_level_statement_spans(
    body_text: str,
    lexer_type: object,
) -> tuple[tuple[str, tuple[object, ...], int], ...] | None:
    tokens = _lex_default_tokens(body_text, lexer_type)
    if not tokens or tokens[0].type != lexer_type.LCURLY:
        return None

    close_index = _find_matching_brace(tokens, 0, lexer_type)
    if close_index is None:
        return None

    spans: list[tuple[str, tuple[object, ...], int]] = []
    brace_depth = 1
    paren_depth = 0
    square_depth = 0
    statement_start_index: int | None = None

    for index in range(1, close_index):
        token = tokens[index]
        if statement_start_index is None:
            statement_start_index = index

        if token.type == lexer_type.LPAREN:
            paren_depth += 1
        elif token.type == lexer_type.RPAREN:
            paren_depth = max(paren_depth - 1, 0)
        elif token.text == "[":
            square_depth += 1
        elif token.text == "]":
            square_depth = max(square_depth - 1, 0)
        elif token.type == lexer_type.LCURLY:
            brace_depth += 1
        elif token.type == lexer_type.RCURLY:
            brace_depth -= 1

        next_token = tokens[index + 1] if index + 1 < close_index else None
        at_statement_end = False

        if (
            token.text == ";"
            and brace_depth == 1
            and paren_depth == square_depth == 0
        ):
            at_statement_end = True
        elif (
            next_token is not None
            and brace_depth == 1
            and paren_depth == square_depth == 0
            and next_token.text not in {"else", "catch"}
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
            getattr(lexer_type, "IF", None),
            getattr(lexer_type, "GUARD", None),
            getattr(lexer_type, "FOR", None),
            getattr(lexer_type, "WHILE", None),
            getattr(lexer_type, "REPEAT", None),
            getattr(lexer_type, "SWITCH", None),
            getattr(lexer_type, "DO", None),
            getattr(lexer_type, "DEFER", None),
        }
        if token_type is not None
    }


def _extract_autoreleasepool_body(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> str | None:
    if not tokens:
        return None

    index = 0
    if tokens[0].text == "return":
        index = 1
    if index >= len(tokens) or tokens[index].text != "autoreleasepool":
        return None

    open_index = None
    for candidate_index in range(index + 1, len(tokens)):
        if tokens[candidate_index].type == lexer_type.LCURLY:
            open_index = candidate_index
            break
    if open_index is None:
        return None

    close_index = _find_matching_brace(tokens, open_index, lexer_type)
    if close_index != len(tokens) - 1:
        return None

    return statement_text[
        tokens[open_index].start - base_offset : tokens[close_index].stop + 1 - base_offset
    ]


def _extract_trailing_closure_body(
    statement_text: str,
    tokens: tuple[object, ...],
    base_offset: int,
    lexer_type: object,
) -> str | None:
    """Return the ``{ ... }`` text of a trailing closure, or ``None``.

    A trailing closure is detected when:
    - The last token is ``RCURLY``
    - The first token is NOT a structured keyword (if/guard/for/while/...)
    - The matching ``LCURLY`` for that final ``RCURLY`` is at index > 0
    """
    if len(tokens) < 3:
        return None

    if tokens[-1].type != lexer_type.RCURLY:
        return None

    structured = _structured_token_types(lexer_type)
    if tokens[0].type in structured:
        return None

    # Walk backwards from the end to find the matching LCURLY.
    depth = 0
    open_index: int | None = None
    for i in range(len(tokens) - 1, -1, -1):
        if tokens[i].type == lexer_type.RCURLY:
            depth += 1
        elif tokens[i].type == lexer_type.LCURLY:
            depth -= 1
            if depth == 0:
                open_index = i
                break

    if open_index is None or open_index == 0:
        return None

    return statement_text[
        tokens[open_index].start - base_offset : tokens[-1].stop + 1 - base_offset
    ]


def _lex_default_tokens(source_text: str, lexer_type: object) -> tuple[object, ...]:
    lexer = lexer_type(InputStream(source_text))
    token_stream = CommonTokenStream(lexer)
    token_stream.fill()
    return tuple(
        token
        for token in token_stream.tokens
        if token.type != Token.EOF and token.channel == Token.DEFAULT_CHANNEL
    )


def _build_control_flow_visitor(visitor_base: type, context: _ExtractorContext) -> type:
    class SwiftControlFlowVisitor(visitor_base):
        def __init__(self) -> None:
            super().__init__()
            self.functions: list[FunctionControlFlow] = []
            self._containers: list[str] = []

        def visitStruct_declaration(self, ctx):
            name = ctx.struct_name().getText()
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitClass_declaration(self, ctx):
            name = ctx.class_name().getText()
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitEnum_declaration(self, ctx):
            name = self._extract_enum_name(ctx)
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitProtocol_declaration(self, ctx):
            name = ctx.protocol_name().getText()
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitExtension_declaration(self, ctx):
            name = ctx.type_identifier().getText()
            return self._with_container(name, lambda: self.visitChildren(ctx))

        def visitFunction_declaration(self, ctx):
            if ctx.function_body() is None:
                return None

            name = ctx.function_name().getText()
            signature = context.compact(ctx.function_signature())
            code_block = ctx.function_body().code_block()
            self.functions.append(
                FunctionControlFlow(
                    name=name,
                    signature=f"func {name}{signature}",
                    container=".".join(self._containers) if self._containers else None,
                    steps=self._extract_code_block(code_block),
                )
            )
            return None

        def _with_container(self, name: str, callback):
            self._containers.append(name)
            try:
                return callback()
            finally:
                self._containers.pop()

        def _extract_enum_name(self, enum_ctx) -> str:
            if enum_ctx.union_style_enum() is not None:
                return enum_ctx.union_style_enum().enum_name().getText()
            if enum_ctx.raw_value_style_enum() is not None:
                return enum_ctx.raw_value_style_enum().enum_name().getText()
            return "enum"

        def _extract_code_block(self, code_block_ctx) -> tuple[ControlFlowStep, ...]:
            if code_block_ctx is None or code_block_ctx.statements() is None:
                return ()
            return self._extract_statements(code_block_ctx.statements())

        def _extract_statements(self, statements_ctx) -> tuple[ControlFlowStep, ...]:
            steps: list[ControlFlowStep] = []
            for statement_ctx in statements_ctx.statement():
                extracted = self._extract_statement(statement_ctx)
                if extracted is not None:
                    steps.append(extracted)
            return tuple(steps)

        def _extract_statement(self, statement_ctx) -> ControlFlowStep | None:
            if statement_ctx.loop_statement() is not None:
                return self._extract_loop_statement(statement_ctx.loop_statement())
            if statement_ctx.branch_statement() is not None:
                return self._extract_branch_statement(statement_ctx.branch_statement())
            if statement_ctx.labeled_statement() is not None:
                return self._extract_labeled_statement(statement_ctx.labeled_statement())
            if statement_ctx.control_transfer_statement() is not None:
                return ActionFlowStep(context.compact(statement_ctx.control_transfer_statement()))
            if statement_ctx.defer_statement() is not None:
                return DeferFlowStep(
                    body_steps=self._extract_code_block(statement_ctx.defer_statement().code_block())
                )
            if statement_ctx.do_statement() is not None:
                return self._extract_do_statement(statement_ctx.do_statement())
            if statement_ctx.declaration() is not None:
                return ActionFlowStep(context.compact(statement_ctx.declaration()))
            if statement_ctx.expression() is not None:
                return ActionFlowStep(context.compact(statement_ctx.expression()))
            if statement_ctx.compiler_control_statement() is not None:
                return ActionFlowStep(context.compact(statement_ctx.compiler_control_statement()))
            return ActionFlowStep(context.compact(statement_ctx))

        def _extract_labeled_statement(self, labeled_ctx) -> ControlFlowStep:
            label = labeled_ctx.label_name().getText()
            if labeled_ctx.loop_statement() is not None:
                inner = self._extract_loop_statement(labeled_ctx.loop_statement())
                return ActionFlowStep(f"label {label}") if inner is None else inner
            if labeled_ctx.if_statement() is not None:
                return self._extract_if_statement(labeled_ctx.if_statement())
            if labeled_ctx.switch_statement() is not None:
                return self._extract_switch_statement(labeled_ctx.switch_statement())
            if labeled_ctx.do_statement() is not None:
                return self._extract_do_statement(labeled_ctx.do_statement())
            return ActionFlowStep(f"label {label}")

        def _extract_loop_statement(self, loop_ctx) -> ControlFlowStep:
            if loop_ctx.for_in_statement() is not None:
                return self._extract_for_in_statement(loop_ctx.for_in_statement())
            if loop_ctx.while_statement() is not None:
                return self._extract_while_statement(loop_ctx.while_statement())
            return self._extract_repeat_while_statement(loop_ctx.repeat_while_statement())

        def _extract_branch_statement(self, branch_ctx) -> ControlFlowStep:
            if branch_ctx.if_statement() is not None:
                return self._extract_if_statement(branch_ctx.if_statement())
            if branch_ctx.guard_statement() is not None:
                return self._extract_guard_statement(branch_ctx.guard_statement())
            return self._extract_switch_statement(branch_ctx.switch_statement())

        def _extract_if_statement(self, if_ctx) -> IfFlowStep:
            then_steps = self._extract_code_block(if_ctx.code_block())
            else_steps: tuple[ControlFlowStep, ...] = ()
            if if_ctx.else_clause() is not None:
                else_clause = if_ctx.else_clause()
                if else_clause.code_block() is not None:
                    else_steps = self._extract_code_block(else_clause.code_block())
                elif else_clause.if_statement() is not None:
                    else_steps = (self._extract_if_statement(else_clause.if_statement()),)
            return IfFlowStep(
                condition=context.compact(if_ctx.condition_list()),
                then_steps=then_steps,
                else_steps=else_steps,
            )

        def _extract_guard_statement(self, guard_ctx) -> GuardFlowStep:
            return GuardFlowStep(
                condition=context.compact(guard_ctx.condition_list()),
                else_steps=self._extract_code_block(guard_ctx.code_block()),
            )

        def _extract_switch_statement(self, switch_ctx) -> SwitchFlowStep:
            cases: list[SwitchCaseFlow] = []
            for switch_case_ctx in self._flatten_switch_cases(switch_ctx.switch_cases()):
                cases.append(self._extract_switch_case(switch_case_ctx))
            return SwitchFlowStep(
                expression=context.compact(switch_ctx.expression()),
                cases=tuple(cases),
            )

        def _extract_switch_case(self, switch_case_ctx) -> SwitchCaseFlow:
            if switch_case_ctx.conditional_switch_case() is not None:
                return SwitchCaseFlow(
                    label=context.compact(switch_case_ctx.conditional_switch_case()),
                    steps=(),
                )

            label_ctx = switch_case_ctx.case_label() or switch_case_ctx.default_label()
            steps = ()
            if switch_case_ctx.statements() is not None:
                steps = self._extract_statements(switch_case_ctx.statements())
            return SwitchCaseFlow(
                label=context.compact(label_ctx),
                steps=steps,
            )

        def _flatten_switch_cases(self, switch_cases_ctx) -> tuple[object, ...]:
            cases: list[object] = []
            current = switch_cases_ctx
            while current is not None:
                cases.append(current.switch_case())
                current = current.switch_cases()
            return tuple(cases)

        def _extract_for_in_statement(self, for_ctx) -> ForInFlowStep:
            return ForInFlowStep(
                header=f"{context.compact(for_ctx.pattern())} in {context.compact(for_ctx.expression())}",
                body_steps=self._extract_code_block(for_ctx.code_block()),
            )

        def _extract_while_statement(self, while_ctx) -> WhileFlowStep:
            return WhileFlowStep(
                condition=context.compact(while_ctx.condition_list()),
                body_steps=self._extract_code_block(while_ctx.code_block()),
            )

        def _extract_repeat_while_statement(self, repeat_ctx) -> RepeatWhileFlowStep:
            return RepeatWhileFlowStep(
                condition=context.compact(repeat_ctx.expression()),
                body_steps=self._extract_code_block(repeat_ctx.code_block()),
            )

        def _extract_do_statement(self, do_ctx) -> DoCatchFlowStep:
            catches: list[CatchClauseFlow] = []
            if do_ctx.catch_clauses() is not None:
                for catch_clause_ctx in do_ctx.catch_clauses().catch_clause():
                    catches.append(
                        CatchClauseFlow(
                            pattern=context.compact(catch_clause_ctx.catch_pattern_list())
                            if catch_clause_ctx.catch_pattern_list() is not None
                            else "catch",
                            steps=self._extract_code_block(catch_clause_ctx.code_block()),
                        )
                    )

            return DoCatchFlowStep(
                body_steps=self._extract_code_block(do_ctx.code_block()),
                catches=tuple(catches),
            )

    return SwiftControlFlowVisitor
