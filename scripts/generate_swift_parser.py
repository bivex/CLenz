"""Generate Python parser artifacts from the vendored Swift grammar."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from textwrap import dedent
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "tools"
GRAMMAR_DIR = ROOT / "resources" / "grammars" / "swift5"
OUTPUT_DIR = ROOT / "src" / "swifta" / "infrastructure" / "antlr" / "generated" / "swift5"
ANTLR_VERSION = "4.13.2"
ANTLR_JAR = TOOLS_DIR / f"antlr-{ANTLR_VERSION}-complete.jar"
ANTLR_JAR_URL = f"https://www.antlr.org/download/antlr-{ANTLR_VERSION}-complete.jar"


def main() -> None:
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    _ensure_grammar_exists()
    _ensure_antlr_jar_exists()
    _generate_parser()
    _write_support_modules()
    _patch_generated_parser()
    _patch_generated_lexer()
    _ensure_package_files()


def _ensure_grammar_exists() -> None:
    required = (
        GRAMMAR_DIR / "Swift5Lexer.g4",
        GRAMMAR_DIR / "Swift5Parser.g4",
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise SystemExit(f"missing grammar files: {', '.join(missing)}")


def _ensure_antlr_jar_exists() -> None:
    if ANTLR_JAR.exists():
        return
    print(f"Downloading ANTLR {ANTLR_VERSION}...")
    urlretrieve(ANTLR_JAR_URL, ANTLR_JAR)


def _generate_parser() -> None:
    command = [
        "java",
        "-jar",
        str(ANTLR_JAR),
        "-Dlanguage=Python3",
        "-visitor",
        "-no-listener",
        "-o",
        str(OUTPUT_DIR),
        str(GRAMMAR_DIR / "Swift5Lexer.g4"),
        str(GRAMMAR_DIR / "Swift5Parser.g4"),
    ]
    subprocess.run(command, check=True, cwd=ROOT)


def _ensure_package_files() -> None:
    init_file = OUTPUT_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""Generated Swift ANTLR parser."""\n', encoding="utf-8")


def _write_support_modules() -> None:
    (OUTPUT_DIR / "SwiftSupportLexer.py").write_text(
        dedent(
            '''
            from __future__ import annotations

            import sys

            from antlr4 import Lexer

            if sys.version_info[1] > 5:
                from typing import TextIO
            else:
                from typing.io import TextIO


            class SwiftSupportLexer(Lexer):
                def __init__(self, input=None, output: TextIO = sys.stdout):
                    super().__init__(input, output)
                    self.parenthesis: list[int] = []

                def reset(self):
                    super().reset()
                    self.parenthesis.clear()
            '''
        ).lstrip(),
        encoding="utf-8",
    )

    (OUTPUT_DIR / "SwiftSupport.py").write_text(
        dedent(
            '''
            from __future__ import annotations

            from dataclasses import dataclass

            from antlr4 import Parser, Token


            @dataclass(frozen=True, slots=True)
            class _SyntheticToken:
                type: int
                text: str
                channel: int


            class SwiftSupport(Parser):
                _LEFT_WS_NAMES = (
                    "WS",
                    "LPAREN",
                    "Interpolation_multi_line",
                    "Interpolation_single_line",
                    "LBRACK",
                    "LCURLY",
                    "COMMA",
                    "COLON",
                    "SEMI",
                )
                _RIGHT_WS_NAMES = (
                    "WS",
                    "RPAREN",
                    "RBRACK",
                    "RCURLY",
                    "COMMA",
                    "COLON",
                    "SEMI",
                    "Line_comment",
                    "Block_comment",
                )
                _OPERATOR_HEAD_RANGES = (
                    (ord("/"), ord("/")),
                    (ord("="), ord("=")),
                    (ord("-"), ord("-")),
                    (ord("+"), ord("+")),
                    (ord("!"), ord("!")),
                    (ord("*"), ord("*")),
                    (ord("%"), ord("%")),
                    (ord("&"), ord("&")),
                    (ord("|"), ord("|")),
                    (ord("<"), ord("<")),
                    (ord(">"), ord(">")),
                    (ord("^"), ord("^")),
                    (ord("~"), ord("~")),
                    (ord("?"), ord("?")),
                    (0x00A1, 0x00A7),
                    (0x00A9, 0x00A9),
                    (0x00AB, 0x00AB),
                    (0x00AC, 0x00AC),
                    (0x00AE, 0x00AE),
                    (0x00B0, 0x00B1),
                    (0x00B6, 0x00B6),
                    (0x00BB, 0x00BB),
                    (0x00BF, 0x00BF),
                    (0x00D7, 0x00D7),
                    (0x00F7, 0x00F7),
                    (0x2016, 0x2017),
                    (0x2020, 0x2027),
                    (0x2030, 0x203E),
                    (0x2041, 0x2053),
                    (0x2055, 0x205E),
                    (0x2190, 0x23FF),
                    (0x2500, 0x2775),
                    (0x2794, 0x2BFF),
                    (0x2E00, 0x2E7F),
                    (0x3001, 0x3003),
                    (0x3008, 0x3020),
                    (0x3030, 0x3030),
                )
                _OPERATOR_CHARACTER_EXTRA_RANGES = (
                    (0x0300, 0x036F),
                    (0x1DC0, 0x1DFF),
                    (0x20D0, 0x20FF),
                    (0xFE00, 0xFE0F),
                    (0xFE20, 0xFE2F),
                    (0xE0100, 0xE01EF),
                )

                @staticmethod
                def _in_ranges(codepoint: int, ranges: tuple[tuple[int, int], ...]) -> bool:
                    return any(start <= codepoint <= end for start, end in ranges)

                @staticmethod
                def _token_text(token) -> str:
                    return getattr(token, "text", "") or ""

                def _token_at(self, tokens, index: int):
                    self.fillUp(tokens)
                    if index < 0:
                        return _SyntheticToken(Token.EOF, "", Token.DEFAULT_CHANNEL)
                    buffered = getattr(tokens, "tokens", [])
                    if index >= len(buffered):
                        return _SyntheticToken(Token.EOF, "", Token.DEFAULT_CHANNEL)
                    return tokens.get(index)

                def isCharacterFromSet(self, token, ranges: tuple[tuple[int, int], ...]) -> bool:
                    if token.type == Token.EOF:
                        return False
                    text = self._token_text(token)
                    if len(text) != 1:
                        return False
                    return self._in_ranges(ord(text), ranges)

                def isOperatorHead(self, token) -> bool:
                    return self.isCharacterFromSet(token, self._OPERATOR_HEAD_RANGES)

                def isOperatorCharacter(self, token) -> bool:
                    ranges = self._OPERATOR_HEAD_RANGES + self._OPERATOR_CHARACTER_EXTRA_RANGES
                    return self.isCharacterFromSet(token, ranges)

                def isOpNext(self, tokens) -> bool:
                    return self.getLastOpTokenIndex(tokens) != -1

                def getLastOpTokenIndex(self, tokens) -> int:
                    self.fillUp(tokens)
                    current_token_index = tokens.index
                    current_token = self._token_at(tokens, current_token_index)

                    if (
                        current_token.type == self.DOT
                        and self._token_at(tokens, current_token_index + 1).type == self.DOT
                    ):
                        current_token_index += 2
                        current_token = self._token_at(tokens, current_token_index)
                        while current_token.type == self.DOT or self.isOperatorCharacter(current_token):
                            current_token_index += 1
                            current_token = self._token_at(tokens, current_token_index)
                        return current_token_index - 1

                    if self.isOperatorHead(current_token):
                        while self.isOperatorCharacter(current_token):
                            current_token_index += 1
                            current_token = self._token_at(tokens, current_token_index)
                        return current_token_index - 1

                    return -1

                def isBinaryOp(self, tokens) -> bool:
                    self.fillUp(tokens)
                    stop = self.getLastOpTokenIndex(tokens)
                    if stop == -1:
                        return False

                    start = tokens.index
                    current_token = self._token_at(tokens, start)
                    prev_token = self._token_at(tokens, start - 1)
                    next_token = self._token_at(tokens, stop + 1)
                    prev_is_ws = self.isLeftOperatorWS(prev_token)
                    next_is_ws = self.isRightOperatorWS(next_token)

                    if current_token.type == self.QUESTION and start == stop:
                        return False
                    if prev_is_ws:
                        return next_is_ws
                    if current_token.type in {self.BANG, self.QUESTION}:
                        return False
                    if not next_is_ws:
                        return next_token.type != self.DOT
                    return False

                def isPrefixOp(self, tokens) -> bool:
                    self.fillUp(tokens)
                    stop = self.getLastOpTokenIndex(tokens)
                    if stop == -1:
                        return False
                    start = tokens.index
                    prev_token = self._token_at(tokens, start - 1)
                    next_token = self._token_at(tokens, stop + 1)
                    return self.isLeftOperatorWS(prev_token) and not self.isRightOperatorWS(next_token)

                def isPostfixOp(self, tokens) -> bool:
                    self.fillUp(tokens)
                    stop = self.getLastOpTokenIndex(tokens)
                    if stop == -1:
                        return False
                    start = tokens.index
                    prev_token = self._token_at(tokens, start - 1)
                    next_token = self._token_at(tokens, stop + 1)
                    prev_is_ws = self.isLeftOperatorWS(prev_token)
                    next_is_ws = self.isRightOperatorWS(next_token)
                    return (not prev_is_ws and next_is_ws) or (
                        not prev_is_ws and next_token.type == self.DOT
                    )

                def isOperator(self, tokens, op: str) -> bool:
                    self.fillUp(tokens)
                    stop = self.getLastOpTokenIndex(tokens)
                    if stop == -1:
                        return False
                    start = tokens.index
                    text = "".join(self._token_text(tokens.get(index)) for index in range(start, stop + 1))
                    return text == op

                def isLeftOperatorWS(self, token) -> bool:
                    left_types = {
                        getattr(self, name)
                        for name in self._LEFT_WS_NAMES
                        if hasattr(self, name)
                    }
                    return token.type in left_types

                def isRightOperatorWS(self, token) -> bool:
                    right_types = {
                        getattr(self, name)
                        for name in self._RIGHT_WS_NAMES
                        if hasattr(self, name)
                    }
                    return token.type == Token.EOF or token.type in right_types

                def isSeparatedStatement(self, tokens, index_of_previous_statement: int) -> bool:
                    self.fillUp(tokens)
                    index_from = index_of_previous_statement - 1
                    index_to = tokens.index - 1

                    if index_from < 0:
                        return True

                    while index_from >= 0 and self._token_at(tokens, index_from).channel == Token.HIDDEN_CHANNEL:
                        index_from -= 1

                    for index in range(index_to, index_from - 1, -1):
                        token_text = self._token_text(self._token_at(tokens, index))
                        if "\\n" in token_text or ";" in token_text:
                            return True
                    return False

                def fillUp(self, tokens) -> None:
                    if hasattr(tokens, "fill"):
                        tokens.fill()
            '''
        ).lstrip(),
        encoding="utf-8",
    )


def _patch_generated_parser() -> None:
    parser_path = OUTPUT_DIR / "Swift5Parser.py"
    content = parser_path.read_text(encoding="utf-8")
    content = content.replace("this.", "self.")

    replacements = [
        (
            "self.isSeparatedStatement(_input, localctx.indexBefore)",
            "self.isSeparatedStatement(self._input, localctx.indexBefore)",
        ),
        (
            "localctx.indexBefore =  _input.index()",
            "localctx.indexBefore = self._input.index",
        ),
        (
            "!self.isBinaryOp(_input) && _input.get(_input.index()-1).getType()!=WS",
            "not self.isBinaryOp(self._input) and "
            "self._input.get(self._input.index - 1).type != self.WS",
        ),
        (
            "!self.isBinaryOp(_input)",
            "not self.isBinaryOp(self._input)",
        ),
        (
            "_input.get(_input.index()-1).getType()!=WS",
            "self._input.get(self._input.index - 1).type != self.WS",
        ),
        (
            "self.isPrefixOp(_input)",
            "self.isPrefixOp(self._input)",
        ),
        (
            "self.isPostfixOp(_input)",
            "self.isPostfixOp(self._input)",
        ),
        (
            "self.isBinaryOp(_input)",
            "self.isBinaryOp(self._input)",
        ),
        (
            'self.isOperator(_input,"&&")',
            'self.isOperator(self._input,"&&")',
        ),
        (
            'self.isOperator(_input,"||")',
            'self.isOperator(self._input,"||")',
        ),
        (
            'self.isOperator(_input,">=")',
            'self.isOperator(self._input,">=")',
        ),
        (
            'self.isOperator(_input,"<")',
            'self.isOperator(self._input,"<")',
        ),
        (
            'self.isOperator(_input,"->")',
            'self.isOperator(self._input,"->")',
        ),
        (
            'self.isOperator(_input,"...")',
            'self.isOperator(self._input,"...")',
        ),
        (
            'self.isOperator(_input,"==")',
            'self.isOperator(self._input,"==")',
        ),
    ]
    for old, new in replacements:
        content = content.replace(old, new)

    parser_path.write_text(content, encoding="utf-8")


def _patch_generated_lexer() -> None:
    lexer_path = OUTPUT_DIR / "Swift5Lexer.py"
    content = lexer_path.read_text(encoding="utf-8")

    content = re.sub(
        r"(?ms)^    def LPAREN_action\(self, localctx:RuleContext , actionIndex:int\):\n"
        r"        if actionIndex == 0:\n"
        r".*?(?=^    def RPAREN_action)",
        "    def LPAREN_action(self, localctx:RuleContext , actionIndex:int):\n"
        "        if actionIndex == 0:\n"
        "            if self.parenthesis:\n"
        "                self.parenthesis[-1] += 1\n\n",
        content,
        count=1,
    )
    content = re.sub(
        r"(?ms)^    def RPAREN_action\(self, localctx:RuleContext , actionIndex:int\):\n"
        r"        if actionIndex == 1:\n"
        r".*?(?=^    def Interpolation_single_line_action)",
        "    def RPAREN_action(self, localctx:RuleContext , actionIndex:int):\n"
        "        if actionIndex == 1:\n"
        "            if self.parenthesis:\n"
        "                self.parenthesis[-1] -= 1\n"
        "                if self.parenthesis[-1] == 0:\n"
        "                    self.parenthesis.pop()\n"
        "                    self.popMode()\n\n",
        content,
        count=1,
    )
    content = re.sub(
        r"(?ms)^    def Interpolation_single_line_action\(self, localctx:RuleContext , actionIndex:int\):\n"
        r"        if actionIndex == 2:\n"
        r".*?(?=^    def Interpolation_multi_line_action)",
        "    def Interpolation_single_line_action(self, localctx:RuleContext , actionIndex:int):\n"
        "        if actionIndex == 2:\n"
        "            self.parenthesis.append(1)\n\n",
        content,
        count=1,
    )
    content = re.sub(
        r"(?ms)^    def Interpolation_multi_line_action\(self, localctx:RuleContext , actionIndex:int\):\n"
        r"        if actionIndex == 3:\n"
        r".*\Z",
        "    def Interpolation_multi_line_action(self, localctx:RuleContext , actionIndex:int):\n"
        "        if actionIndex == 3:\n"
        "            self.parenthesis.append(1)\n",
        content,
        count=1,
    )
    lexer_path.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    main()
