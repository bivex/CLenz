"""Generate Python parser artifacts from the vendored C grammar."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from urllib.request import urlretrieve


ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "build" / "tools"
GRAMMAR_DIR = ROOT / "resources" / "grammars" / "c"
OUTPUT_DIR = ROOT / "src" / "clenz" / "infrastructure" / "antlr" / "generated" / "c"
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
    _ensure_package_files()

    print(f"Generated C parser at {OUTPUT_DIR}")


def _ensure_grammar_exists() -> None:
    grammar = GRAMMAR_DIR / "C.g4"
    if not grammar.exists():
        raise FileNotFoundError(f"C grammar not found at {grammar}")


def _ensure_antlr_jar_exists() -> None:
    if ANTLR_JAR.exists():
        return
    print(f"Downloading ANTLR {ANTLR_VERSION}...")
    ANTLR_JAR.parent.mkdir(parents=True, exist_ok=True)
    urlretrieve(ANTLR_JAR_URL, ANTLR_JAR)
    print(f"Downloaded to {ANTLR_JAR}")


def _generate_parser() -> None:
    print("Generating C parser...")
    subprocess.run(
        [
            "java",
            "-jar",
            str(ANTLR_JAR),
            "-Dlanguage=Python3",
            "-visitor",
            "-no-listener",
            str(GRAMMAR_DIR / "C.g4"),
            "-o",
            str(OUTPUT_DIR),
        ],
        check=True,
    )


def _ensure_package_files() -> None:
    init = OUTPUT_DIR / "__init__.py"
    init.write_text('"""Generated ANTLR C parser artifacts."""\n', encoding="utf-8")


if __name__ == "__main__":
    main()
