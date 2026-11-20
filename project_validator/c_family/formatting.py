"""clang-format: the C and C++ formatter, with no style but the one a `.clang-format` file defines."""

from __future__ import annotations

import re

from project_validator.ecosystems.model import C_FAMILY
from project_validator.facts import Command, Facts, resolved
from project_validator.facts.arguments import has_option, program, starts_with
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
    if starts_with(argv, ("git", "clang-format")):
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


# Artistic Style and uncrustify are recognised where a project uses them, never suggested: clang-format is. Each
# defines its style in its own file.
# `astyle` rewrites the files with the options of its `.astylerc` (or `--project=<file>`); nothing makes it fail on an
# unformatted file, so it enforces what a later step fails on or commits (nlohmann/json).
ASTYLE_FILES = file_reader("astyle", (".astylerc", "_astylerc"))


def _astyle(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) != "astyle":
        return None
    return formatted(command, facts, checks=False, applies=not has_option(argv, "--dry-run", "-n"))


ASTYLE = format_tool(
    name="astyle",
    languages=C_FAMILY,
    can={Enforcement.APPLY: ""},
    formats=_astyle,
    style=defined_by(files=("astyle",), default=False),
)

# uncrustify: `--check` fails on a file its configuration (`-c uncrustify.cfg`) would change, `--replace` rewrites the
# files (neovim's lint target).
UNCRUSTIFY_FILES = file_reader("uncrustify", ("uncrustify.cfg", ".uncrustify.cfg"))


def _uncrustify(command: Command, facts: Facts) -> Run | None:
    argv = resolved(command)
    if program(argv) != "uncrustify":
        return None
    return formatted(
        command, facts, checks=has_option(argv, "--check"), applies=has_option(argv, "--replace", "--no-backup")
    )


UNCRUSTIFY = format_tool(
    name="uncrustify",
    languages=C_FAMILY,
    can={Enforcement.CHECK: "", Enforcement.APPLY: ""},
    formats=_uncrustify,
    style=defined_by(files=("uncrustify",), default=False),
)
