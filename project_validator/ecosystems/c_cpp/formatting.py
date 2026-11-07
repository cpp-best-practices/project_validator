"""clang-format: the C and C++ formatter, with no style but the one a `.clang-format` file defines."""

import re

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option, program
from project_validator.facts.expansion import Action
from project_validator.facts.formatting import Enforcement, format_tool, formatted
from project_validator.facts.settings import file_reader
from project_validator.facts.tools import Run, defined_by

CLANG_FORMAT_FILES = file_reader("clang-format", (".clang-format", "_clang-format"))
_CLANG_FORMAT = re.compile(r"clang-format(?:-\d+(?:\.\d+)*)?")


def _clang_format(command: Command, facts: Facts) -> Run | None:
    """`clang-format --dry-run -Werror` checks; `clang-format -i` applies. `git clang-format --diff` (which fails on
    a difference) and run-clang-format check; `git clang-format` applies to what changed."""
    argv = resolved(command)
    name = program(argv)
    if name in ("run-clang-format", "run-clang-format.py"):
        return formatted(command, facts, checks=True)
    if name == "git" and argv[1:2] == ("clang-format",):
        return formatted(command, facts, checks=has_option(argv, "--diff"))
    if not _CLANG_FORMAT.fullmatch(name):
        return None
    dry_run = has_option(argv, "--dry-run", "-n")
    errors = has_option(argv, "--Werror", "-Werror")
    return formatted(command, facts, checks=dry_run and errors, applies=has_option(argv, "-i"))


CLANG_FORMAT = format_tool(
    name="clang-format",
    languages=C_FAMILY,
    can={Enforcement.CHECK: "clang-format --dry-run -Werror", Enforcement.APPLY: "clang-format -i"},
    formats=_clang_format,
    style=defined_by(files=("clang-format",), default=False),
)


def _checks_formatting(_inputs: object) -> tuple[tuple[str, ...], ...]:
    return (("clang-format", "--dry-run", "-Werror"),)


CLANG_FORMAT_LINT_ACTION = Action(name="DoozyX/clang-format-lint-action", runs=_checks_formatting)
CLANG_FORMAT_ACTION = Action(name="jidicula/clang-format-action", runs=_checks_formatting)
