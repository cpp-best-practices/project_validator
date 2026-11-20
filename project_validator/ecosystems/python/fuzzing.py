"""Python's fuzzing: atheris fuzz targets, run as scripts, and Hypothesis property tests."""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from project_validator.ecosystems.python import _INTERPRETER_VALUES, _PYTHON, PYTHON_ONLY
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import program
from project_validator.facts.fuzzing import FuzzTargets, PropertyTests, fuzz_kinds, fuzzed, fuzzer
from project_validator.facts.testing import TestFile
from project_validator.facts.tools import Run

PYTHON_FUZZ_TARGETS = FuzzTargets(
    name="atheris fuzz targets (atheris.Setup or atheris.Fuzz)",
    languages=PYTHON_ONLY,
    path=re.compile(r"\.py$"),
    contains=re.compile(r"^\s*atheris\.(?:Setup|Fuzz)\(", re.MULTILINE),
)
PYTHON_PROPERTY_TESTS = PropertyTests(
    name="Hypothesis tests",
    languages=PYTHON_ONLY,
    path=re.compile(r"\.py$"),
    contains=re.compile(r"^\s*from hypothesis import|^\s*import hypothesis\b|@given\(", re.MULTILINE),
)


def _script(argv: tuple[str, ...]) -> str | None:
    """The script `python` runs: its first argument that is not an option (or an option's value); None when it
    runs a module or a command (`-m`, `-c`) instead."""
    words = iter(argv[1:])
    for word in words:
        if word in _INTERPRETER_VALUES:
            next(words, None)
        elif word.startswith(("-m", "-c")):
            return None
        elif not word.startswith("-"):
            return word
    return None


def _normalised(command: Command, path: str) -> str:
    joined = PurePosixPath(command.directory or ".") / path
    return PurePosixPath(*[part for part in joined.parts if part != "."]).as_posix() or "."


# `coverage run`'s options that take a value as their own word.
_COVERAGE_VALUES = frozenset(
    {"--rcfile", "--source", "--omit", "--include", "--context", "--data-file", "--concurrency", "--debug"}
)


def _script_run(argv: tuple[str, ...]) -> str | None:
    """The script a command runs with Python: `python <script>`, or `coverage run <script>` (black's fuzz
    environment), which runs it with Python under coverage."""
    if argv and _PYTHON.fullmatch(program(argv)):
        return _script(argv)
    if argv[:2] != ("coverage", "run"):
        return None
    words = iter(argv[2:])
    for word in words:
        if word in _COVERAGE_VALUES:
            next(words, None)
        elif word == "-m":
            return None
        elif not word.startswith("-"):
            return word
    return None


def _runs_target(command: Command, facts: Facts) -> Run | None:
    """`python <fuzz target>.py ...` (or `coverage run <fuzz target>.py`): the script is a fuzz target's file. A path
    holding an expression the validator cannot evaluate is taken to be one, as a heuristic, only when it names
    fuzzing (`fuzz` in the path)."""
    script = _script_run(resolved(command))
    if script is None:
        return None
    if "${" in script or "$(" in script:
        return fuzzed(heuristic=True) if "fuzz" in script.lower() else None
    path = _normalised(command, script.replace("\\", "/"))
    targets = {test.origin.path for test in facts.of(TestFile) if test.kind in fuzz_kinds()}
    return fuzzed() if path in targets else None


ATHERIS = fuzzer(
    name="atheris",
    languages=PYTHON_ONLY,
    how="python <fuzz target>.py",
    runs=_runs_target,
    targets=(PYTHON_FUZZ_TARGETS,),
)
